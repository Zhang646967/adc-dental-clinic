"""Transactional examination workflow for configured synthetic course cases."""
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.debug import sensitive_variables

from accounts.models import RoleAssignment
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from clinical.authority import professional_scope, require_reviewer, require_visit_authority, visit_service_id
from clinical.authority_services import lock_people
from clinical.examination_models import ExaminationDuty, ExaminationEvent, ExaminationOrder, ExaminationProject
from clinical.locking import lock_clinical_visit
from clinical.encounter_models import ClinicalRecordVersion
from workspaces.context import require_active

CONTRACT = 'adc.clinical.examinations.v1'
ROLES = ('DENTIST',)
Action = ExaminationEvent.Action
Kind = ExaminationDuty.Kind
REVIEW = (Action.APPROVE, Action.RETURN)
RELATED = 'source_record__encounter__visit'
DECISIONS = {Action.APPROVE: '审核通过，待发布', Action.RETURN: '结果已退回'}


def require_course():
    if not settings.ADC_CLINICAL_SYNTHETIC:
        raise Http404('检查结果流程尚未在此环境启用。')


def orders():
    return ExaminationOrder.objects.select_related(
        RELATED + '__clinic', RELATED + '__patient', 'project__service__department',
    )


def latest_report(order):
    return order.reports.order_by('-number').first()


def visit_record(visit):
    return ClinicalRecordVersion.objects.filter(encounter__visit=visit).order_by('-revision').first()


def report_decision(report):
    return report.events.filter(action__in=REVIEW).values_list('action', flat=True).first() if report else None


def last_publication(order):
    return order.events.filter(action=Action.PUBLISH).select_related('report').order_by('-pk').first()


def progress(order, report, decision):
    if report:
        return DECISIONS.get(decision, '待独立审核')
    return '待登记结果' if order.performed_at else '待执行检查'


def publication_status(order):
    if order.active_release_id:
        return '患者可查阅'
    return '已撤回' if last_publication(order) else '未发布'


def eligible_projects(visit):
    if not settings.ADC_CLINICAL_SYNTHETIC or visit.status != 'CHECKED_IN':
        return ExaminationProject.objects.none()
    return ExaminationProject.objects.filter(service_id=visit_service_id(visit),
        service__department__clinic_id=visit.clinic_id, service__is_active=True, is_active=True).order_by('name', 'pk')


def duties(actor, project, kind, *, lock=False):
    rows = ExaminationDuty.objects.filter(project=project, user=actor, kind=kind, is_active=True)
    return rows.select_for_update() if lock else rows


def check_duty(actor, project, kind, *, lock=False):
    duty = duties(actor, project, kind, lock=lock).first()
    if duty is None:
        raise PermissionDenied('没有此检查项目的有效办理职责。')
    return duty


def _scope(actor, order, action=None, *, lock=False):
    require_active(actor, ROLES)
    visit = order.source_record.encounter.visit
    project = order.project
    if project.service.department.clinic_id != visit.clinic_id:
        raise PermissionDenied('检查项目与原就诊门店不一致。')
    owner = actor.dentist_id == visit.dentist_id
    required = 'READ'
    if action in (Action.EXECUTE, Action.SUBMIT):
        check_duty(actor, project, Kind.EXECUTE, lock=lock)
        required = 'RECORD'
    elif action in REVIEW:
        check_duty(actor, project, Kind.REVIEW, lock=lock)
        require_reviewer(actor, visit.clinic_id, lock=lock)
    elif action in (Action.PUBLISH, Action.WITHDRAW):
        if not owner:
            raise PermissionDenied('请由原就诊负责医师办理患者发布。')
        required = 'RECORD'
    elif not owner and not duties(actor, project, Kind.EXECUTE).exists():
        check_duty(actor, project, Kind.REVIEW)
        require_reviewer(actor, visit.clinic_id)
    return professional_scope(actor.pk, visit.clinic_id, project.service_id, required, lock=lock)


def read_order(actor, order):
    require_course()
    _scope(actor, order)


def available_actions(actor, order, report, decision):
    last_release = last_publication(order)
    possible = []
    if not order.performed_at:
        possible.append(Action.EXECUTE)
    elif not report or decision:
        possible.append(Action.SUBMIT)
    if report and not decision:
        possible.extend(REVIEW)
    if decision == Action.APPROVE and (not last_release or report.number > last_release.report.number):
        possible.append(Action.PUBLISH)
    if order.active_release_id:
        possible.append(Action.WITHDRAW)
    allowed = []
    for action in possible:
        try:
            _scope(actor, order, action)
            if action in REVIEW:
                _independent(actor, order, report)
        except PermissionDenied:
            continue
        allowed.append(action)
    return allowed


def _independent(actor, order, report):
    if actor.pk == order.requested_by_id or report.events.filter(action=Action.SUBMIT, actor=actor).exists():
        raise PermissionDenied('请由申请人与结果登记人以外的具备职责医师独立审核。')


def _text(value, limit, label, *, optional=False):
    value = (value or '').strip()
    if (not value and not optional) or len(value) > limit:
        raise RuleError(f'请填写{label}，最多 {limit} 字。')
    return value


def _new_order_data(actor, visit, project_id, purpose, *, lock=False):
    scope = require_visit_authority(actor, visit, 'RECORD', lock=lock, always=True)
    projects = eligible_projects(visit)
    if lock:
        projects = projects.select_for_update(of=('self',))
    project = projects.filter(pk=project_id).first()
    record = visit_record(visit)
    if not project or not record or not visit.attended_at:
        raise RuleError('请核对本次到诊、已确认检查记录和开放的检查项目。')
    return dict(action=Action.ORDER, visit=visit.pk, patient=visit.patient_id, project=project.pk,
        project_name=project.name, record=record.pk, record_number=record.revision,
        scope=scope.pk, scope_revision=scope.revision, purpose=_text(purpose, 500, '申请目的'))


@sensitive_variables()
def prepare_order(actor, visit, project_id, purpose):
    require_course()
    data = _new_order_data(actor, visit, project_id, purpose)
    return data, proposal(actor, CONTRACT, ROLES, data)


@sensitive_variables()
def _action_data(actor, order, action, fields, *, lock=False):
    scope = _scope(actor, order, action, lock=lock)
    report = latest_report(order)
    decision = report_decision(report)
    visit = order.source_record.encounter.visit
    data = dict(action=action, order=order.pk, visit=visit.pk, patient=visit.patient_id,
        revision=order.revision, scope=scope.pk, scope_revision=scope.revision,
        report=report.pk if report else None)
    if action == Action.EXECUTE:
        if order.performed_at:
            raise RuleError('本申请已有实际执行记录，请从结果登记继续。')
        performed_at = parse_datetime(fields['performed_at'])
        if (not performed_at or timezone.is_naive(performed_at) or performed_at < visit.attended_at
                or performed_at > timezone.now() or (visit.completed_at and performed_at > visit.completed_at)):
            raise RuleError('实际检查时间须在本次到诊至就诊结束之间，且不能在未来。')
        data.update(performed_at=performed_at.isoformat(),
            source_reference=_text(fields['source_reference'], 120, '检查依据编号'))
    elif action == Action.SUBMIT:
        if not order.performed_at or (report and not decision):
            raise RuleError('请先登记实际检查，或等待在审版本处理完毕。')
        data['body'] = _text(fields['body'], 2000, '检查结果')
        data['reason'] = _text(fields.get('reason'), 500, '更正依据') if report else ''
    elif action in REVIEW:
        if not report or decision:
            raise RuleError('此结果已处理或尚未提交，请刷新后核对。')
        _independent(actor, order, report)
        data['reason'] = _text(fields.get('reason'), 500, '审核说明', optional=action == Action.APPROVE)
    elif action == Action.PUBLISH:
        last_release = last_publication(order)
        if decision != Action.APPROVE or (last_release and report.number <= last_release.report.number):
            raise RuleError('请发布经独立审核、尚未发布的新版本。')
    elif action == Action.WITHDRAW:
        if not order.active_release_id:
            raise RuleError('当前没有患者可查阅的版本。')
        data['report'] = order.active_release.report_id
        data['reason'] = _text(fields.get('reason'), 500, '撤回原因')
    else:
        raise RuleError('请选择可办理的检查动作。')
    return data


@sensitive_variables()
def prepare_action(actor, order, action, fields):
    require_course()
    data = _action_data(actor, order, action, fields)
    return data, proposal(actor, CONTRACT, ROLES, data)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(*, actor, proposal_token, confirmed):
    require_course()
    if not confirmed:
        raise RuleError('请核对本次办理内容后确认。')
    lock_people(actor)
    payload = read_proposal(actor, CONTRACT, ROLES, proposal_token)
    data, operation = payload['data'], payload['operation']
    action = Action(data['action'])
    if action == Action.ORDER:
        visit = lock_clinical_visit(actor, data['visit'])
        replay = ExaminationEvent.objects.filter(operation_id=operation, actor=actor, action=action).first()
        if replay:
            return replay.order, True
        current = _new_order_data(actor, visit, data['project'], data['purpose'], lock=True)
        if current != data:
            raise RuleError('病历版本或专业授权已变化，请重新核对。')
        order = ExaminationOrder.objects.create(source_record_id=data['record'], project_id=data['project'],
            project_name=data['project_name'], number='EX-' + uuid4().hex.upper(),
            requested_by=actor, purpose=data['purpose'])
        ExaminationEvent.objects.create(order=order, action=action, actor=actor, operation_id=operation)
        return order, False

    order = orders().get(pk=data['order'])
    # Changes to the current clinical role serialize with its existing revocation flow.
    if not RoleAssignment.objects.select_for_update().filter(
        user=actor, role='DENTIST', scope_kind='SELF_DENTIST', is_active=True,
    ).first():
        raise PermissionDenied('医师工作身份已撤回。')
    _scope(actor, order, action, lock=True)
    order = orders().select_for_update(of=('self',)).get(pk=order.pk)
    if order.events.filter(operation_id=operation, actor=actor, action=action).exists():
        return order, True
    if data['revision'] != order.revision:
        raise RuleError('检查结果或发布状态已变化，请刷新后重新核对。')
    current = _action_data(actor, order, action, data)
    if current != data:
        raise RuleError('就诊事实或专业授权已变化，请重新核对。')

    report_id = data['report']
    update = ['revision']
    if action == Action.EXECUTE:
        order.performed_at = parse_datetime(data['performed_at'])
        order.performed_by = actor
        order.source_reference = data['source_reference']
        update.extend(('performed_at', 'performed_by', 'source_reference'))
    elif action == Action.SUBMIT:
        previous = latest_report(order)
        report = order.reports.create(number=previous.number + 1 if previous else 1,
            body=data['body'], correction_reason=data['reason'])
        report_id = report.pk

    event = ExaminationEvent.objects.create(order=order, report_id=report_id,
        action=action, actor=actor, reason=data.get('reason', '') if action != Action.SUBMIT else '',
        operation_id=operation)
    if action in (Action.PUBLISH, Action.WITHDRAW):
        order.active_release = event if action == Action.PUBLISH else None
        update.append('active_release')
    order.revision += 1
    order.save(update_fields=update)
    return order, False
