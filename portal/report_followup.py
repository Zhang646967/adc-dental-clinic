"""A report-bound selection, projected identically for web and WeChat."""
from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.utils import timezone

from adc_core.rules import RuleError
from clinical import examination_followup as clinical
from clinical.examination_models import ExaminationOrder
from clinical.next_visits import has_completed_goal
from clinical.plan_models import NextVisitInstruction
from portal.policies import patient_access
from portal.rules import HORIZON_DAYS
from portal.service_catalogue import require_self_service
from scheduling.service_content import positive_id

FIELDS = ('followup_visit', 'followup_examination', 'followup_revision')
CAPTIONS = {'BOOK': '按建议日期预约复诊', 'CONTACT': '联系原门店',
    'VIEW_APPOINTMENT': '查看复诊预约', 'NONE': '后续安排'}


def binding(query):
    if not any(key in query for key in FIELDS):
        return None
    values = {key: positive_id(query.get(key)) for key in FIELDS}
    if not all(values.values()):
        raise RuleError('复诊链接不完整，请从原报告重新进入。')
    return values


def _order(visit_id, order_id, *, patient_id=None, lock=False):
    if not settings.ADC_CLINICAL_SYNTHETIC:
        raise Http404
    rows = ExaminationOrder.objects.filter(pk=order_id, source_record__encounter__visit_id=visit_id)
    if patient_id is not None:
        rows = rows.filter(source_record__encounter__visit__patient_id=patient_id)
    rows = rows.select_related('source_record__encounter__visit__clinic__public_directory', 'active_release__report')
    if lock:
        rows = rows.select_for_update(of=('self',))
    row = rows.first()
    if row is None:
        raise Http404
    return row


def _active_version(order, revision):
    event = order.active_release
    return bool(event and event.order_id == order.pk and event.action == 'PUBLISH'
        and event.report.order_id == order.pk and event.report.number == revision)


def window(instruction):
    today = timezone.localdate()
    return max(today, instruction.earliest_on), min(today + timedelta(days=HORIZON_DAYS), instruction.latest_on)


def _booking_reason(order, instruction, actor):
    if instruction.state != 'OPEN':
        return '当前复诊指示已变化，请联系原门店核对。'
    recall = getattr(instruction, 'recall', None)
    if not clinical.current_plan_step(instruction):
        return '复诊所依据的治疗方案已更新，请联系原门店。'
    if recall and recall.state in ('REVIEW', 'WITHDRAWN'):
        return '复诊安排待门店核对，请联系原门店。'
    if has_completed_goal(instruction) or (recall and recall.state == 'COMPLETED'):
        return '已有实际复诊记录，请联系原门店核对后续安排。'
    first, last = window(instruction)
    if first > last:
        return '建议复诊日期不在当前可预约范围内，请联系原门店安排。'
    try:
        require_self_service(instruction.service_id, clinic_id=order.source_record.encounter.visit.clinic_id, actor=actor)
    except RuleError as exc:
        return str(exc)
    if settings.ADC_READ_ONLY:
        return '当前实例仅供查阅，请联系原门店安排。'
    return ''


def _appointment_data(visit):
    return dict(id=visit.pk, visit_no=visit.visit_no, start=visit.scheduled_start,
        status=visit.status, status_label=visit.get_status_display()) if visit else None


def projection(visit, report, actor):
    order = _order(visit.pk, report['id'], patient_id=visit.patient_id)
    if not _active_version(order, report['revision']):
        raise Http404
    decision = clinical.current_decision(order)
    if decision is None:
        return None
    instruction = decision.instruction
    appointments = clinical.report_appointments(order)
    active = next((row for row in appointments if row.status in ('SCHEDULED', 'CHECKED_IN')), None)
    latest = active or next(iter(appointments), None)
    start, end = window(instruction) if instruction else (None, None)
    action, message = decision.kind, ''
    if active:
        if (instruction and instruction.state == 'OPEN' and clinical.current_plan_step(instruction)
                and getattr(getattr(instruction, 'recall', None), 'state', '') not in ('REVIEW', 'WITHDRAWN')
                and active.pk in {
                clinical.current_promise(link.visit).pk for link in instruction.appointment_links.select_related('visit')}):
            action, message = 'VIEW_APPOINTMENT', '已保存复诊安排，可查看当前预约。'
        else:
            action, message = 'CONTACT', '本报告的复诊安排已有变化，请联系原门店核对现有预约。'
    elif action == 'BOOK':
        if instruction and getattr(getattr(instruction, 'recall', None), 'state', None) == 'COMPLETED' and latest:
            action, message = 'VIEW_APPOINTMENT', '复诊目标已核对，可查看就诊结果。'
        else:
            message = _booking_reason(order, instruction, actor)
            action = 'CONTACT' if message else 'BOOK'
            message = message or '可在建议日期内选择有号时段。'
    elif action == 'CONTACT':
        message = '请联系原门店核对本报告的后续安排。'
    else:
        message = '本报告供查阅。'
    return dict(action=action, label=CAPTIONS[action], message=message, clinic_id=visit.clinic_id,
        clinic=visit.clinic.public_contact['name'], service_id=instruction.service_id if instruction else None,
        service=instruction.service.name if instruction else '', earliest_on=instruction.earliest_on if instruction else None,
        latest_on=instruction.latest_on if instruction else None, first_day=start if action == 'BOOK' else None,
        last_day=end if action == 'BOOK' else None, appointment=_appointment_data(latest))


def selection(actor, fields, *, clinic_id, service_id, day=None, lock=False):
    access = patient_access(actor, self_only=True)
    order = _order(fields['followup_visit'], fields['followup_examination'], patient_id=access.patient_id, lock=lock)
    if not _active_version(order, fields['followup_revision']):
        if lock:
            raise RuleError('报告版本已更新或撤回，请返回原就诊核对。')
        raise Http404
    decision = clinical.current_decision(order)
    if decision is None or decision.kind != 'BOOK':
        raise RuleError('当前报告没有可自助办理的复诊指示，请联系原门店。')
    instruction = decision.instruction
    if lock:
        instruction = NextVisitInstruction.objects.select_for_update(of=('self',)).select_related('service', 'recall').get(pk=instruction.pk)
    if clinic_id != order.source_record.encounter.visit.clinic_id or service_id != instruction.service_id:
        raise RuleError('复诊服务或门店已变化，请从原报告重新办理。')
    clinical.check_report_appointment(order)
    message = _booking_reason(order, instruction, actor)
    if message:
        raise RuleError(message)
    first, last = window(instruction)
    if day is not None and not first <= day <= last:
        raise RuleError('请选择建议窗口内可预约的日期。')
    return decision, instruction, first, last


def stamp(fields, decision, instruction):
    return dict(fields, release=decision.release_id, decision=decision.pk, instruction=instruction.pk,
        instruction_revision=instruction.revision)


def candidates(actor, fields, *, clinic_id, service_id, day=None, dentist_id=None):
    from portal.availability_search import future_options
    from portal.services import public_options
    _, _, first, last = selection(actor, fields, clinic_id=clinic_id, service_id=service_id, day=day)
    if day:
        return public_options(actor, clinic_id, day, service_id, dentist_id)
    return future_options(lambda date: public_options(actor, clinic_id, date, service_id, dentist_id),
        first_day=first, horizon_days=(last - first).days)
