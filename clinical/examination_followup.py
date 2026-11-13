"""Report decisions use existing instructions, appointments and clinical authority."""
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent
from clinical.authority import professional_scope, visit_service_id
from clinical.continuity_rules import moment
from clinical.examination_models import ExaminationFollowup, ExaminationNotice, ExaminationOrder
from clinical.next_visits import check_instruction_step, current_promise, instruction_fields, promise_ids, record_instruction
from clinical.plan_locks import require_plan_service
from clinical.plan_payload import text
from clinical.plan_models import NextVisitInstruction, PlanAppointment

FOLLOWUP = 'FOLLOWUP'
CONTACT_RESULT = 'CONTACT_RESULT'
CONTACT_EVENT = 'EXAMINATION_CONTACT_RECORDED'
CONTACT_OUTCOMES = {'REACHED': '已联系', 'NO_ANSWER': '联系未果'}
Kind = ExaminationFollowup.Kind


def current_decision(order):
    return (ExaminationFollowup.objects.filter(release_id=order.active_release_id)
        .select_related('instruction__service', 'instruction__step_version', 'instruction__recall').order_by('-pk').first())


def order_for_instruction(instruction_id, *, lock=False):
    order_id = ExaminationFollowup.objects.filter(instruction_id=instruction_id).values_list('release__order_id', flat=True).first()
    if order_id is None:
        return None
    rows = ExaminationOrder.objects
    if lock:
        rows = rows.select_for_update()
    return rows.get(pk=order_id)


def decision_values(actor, order, fields, *, lock=False):
    kind = fields.get('followup_kind')
    if kind not in Kind.values:
        raise RuleError('请选择报告发布后的安排。')
    if kind == Kind.NONE:
        return dict(kind=kind)
    if kind == Kind.CONTACT:
        return dict(kind=kind, due_at=moment(fields.get('contact_due_at'), '门店联系期限', future=True).isoformat())
    visit = order.source_record.encounter.visit
    instruction_id = fields.get('instruction')
    if instruction_id:
        rows = NextVisitInstruction.objects.filter(source_record__encounter__visit=visit)
        if lock:
            rows = rows.select_for_update()
        row = rows.get(pk=instruction_id)
        if (row.state != 'OPEN' or row.completion_rule == 'UNSPECIFIED' or row.latest_on < timezone.localdate()
                or getattr(getattr(row, 'recall', None), 'state', '') == 'COMPLETED'):
            raise RuleError('原复诊指示已经关闭或缺少有效窗口及完成目标，请追加本次指示。')
        bound = order_for_instruction(row.pk)
        if bound and bound.pk != order.pk:
            raise RuleError('此复诊指示已用于其他检查单，请追加本次指示。')
        values = dict(service=row.service_id, step_version=row.step_version_id)
        require_plan_service(actor, visit, check_instruction_step(visit, values), lock=lock)
        return dict(kind=kind, instruction=row.pk, instruction_revision=row.revision)
    values = instruction_fields(fields)
    if values['latest_on'] < timezone.localdate().isoformat():
        raise RuleError('复诊建议最晚日期须为今天或以后。')
    service = check_instruction_step(visit, values)
    require_plan_service(actor, visit, service, lock=lock)
    return dict(kind=kind, values=values)


def save_decision(*, release, actor, data, operation):
    instruction_id = data.get('instruction')
    if 'values' in data:
        order = release.order
        values = data['values']
        service = check_instruction_step(order.source_record.encounter.visit, values)
        row = record_instruction(actor=actor, record=order.source_record, service=service,
            values=values, operation_id=operation)
        instruction_id = row.pk
    return ExaminationFollowup.objects.create(release=release, actor=actor, kind=data['kind'],
        instruction_id=instruction_id, due_at=data.get('due_at'), operation_id=operation)


def publish_notice(event, *, corrected=False):
    kind = ExaminationNotice.Kind
    return ExaminationNotice.objects.create(event=event, kind=kind.WITHDRAWN if event.action == 'WITHDRAW'
        else kind.CORRECTED if corrected else kind.RELEASED)


def contact_events(decision):
    return AuditEvent.objects.filter(subject_type='examinationfollowup', subject_key=str(decision.pk),
        event_type=CONTACT_EVENT).order_by('-pk')


def contact_progress(decision, *, now=None):
    event = contact_events(decision).first()
    outcome = event.change_summary['outcome'] if event else None
    due = parse_datetime(event.change_summary['due_at']) if outcome == 'NO_ANSWER' else decision.due_at
    return dict(state=CONTACT_OUTCOMES.get(outcome, '待联系'), outcome=outcome, due_at=due,
        overdue=outcome != 'REACHED' and due <= (now or timezone.now()), event=event)


def contact_values(decision, fields):
    if decision is None or decision.kind != Kind.CONTACT:
        raise RuleError('当前报告没有待联系事项。')
    current = contact_progress(decision)
    if current['outcome'] == 'REACHED':
        raise RuleError('此报告已记录联系结果，请核对后续安排。')
    outcome = fields.get('contact_outcome')
    if outcome not in CONTACT_OUTCOMES:
        raise RuleError('请选择实际联系结果。')
    due = moment(fields.get('contact_due_at'), '下次联系期限', future=True) if outcome == 'NO_ANSWER' else None
    return dict(decision=decision.pk, previous=current['event'].pk if current['event'] else None,
        outcome=outcome, due_at=due.isoformat() if due else None,
        note=text(fields.get('contact_note'), 500, '联系记录', True))


def save_contact(*, actor, order, decision, data, operation):
    emit(actor, CONTACT_EVENT, decision, visit=order.source_record.encounter.visit,
        reason=data['note'], summary={'outcome': data['outcome'], 'due_at': data['due_at'], 'operation': operation})


def report_links(order):
    instruction_ids = ExaminationFollowup.objects.filter(release__order=order, instruction__isnull=False).values('instruction_id')
    return PlanAppointment.objects.filter(instruction_id__in=instruction_ids)


def report_appointments(order):
    links = report_links(order).select_related('visit').order_by('-pk')
    return list({visit.pk: visit for visit in (current_promise(link.visit) for link in links)}.values())


def current_plan_step(instruction):
    step = instruction.step_version
    if step is None:
        return True
    from clinical.plans import current_version
    return current_version(step.version.plan).pk == step.version_id


def check_report_appointment(order, visit=None):
    appointments = [row for row in report_appointments(order) if row.status in ('SCHEDULED', 'CHECKED_IN')]
    # Front desk can explicitly adopt the same suitable reservation after a
    # revision. A different active reservation still blocks a second promise.
    if any(visit is None or row.pk != visit.pk for row in appointments):
        raise RuleError('这张报告已有有效复诊，请核对原安排。')


def linked_instructions(visit):
    return PlanAppointment.objects.filter(visit_id__in=promise_ids(visit),
        instruction__source_record__encounter__visit__patient_id=visit.patient_id,
        instruction__source_record__encounter__visit__clinic_id=visit.clinic_id)


def linked_orders(visit):
    return ExaminationOrder.objects.filter(events__followup_decisions__instruction_id__in=
        linked_instructions(visit).values('instruction_id')).distinct()


def reschedule_window(visit, *, lock=False):
    """Only report-based promises inherit the report's clinical date window."""
    orders = linked_orders(visit)
    first, last = None, None
    rows = ExaminationOrder.objects.filter(pk__in=orders.values('pk')).order_by('pk')
    if lock:
        rows = rows.select_for_update()
    instructions = linked_instructions(visit).values('instruction_id')
    for order in rows:
        decision = current_decision(order)
        if (not decision or not decision.instruction_id or decision.instruction.state != 'OPEN'
                or not instructions.filter(instruction_id=decision.instruction_id).exists()):
            raise RuleError('原报告或复诊指示已变化，请联系原门店协调改期；原预约仍保留。')
        row = decision.instruction
        if row.latest_on < timezone.localdate() or not current_plan_step(row):
            raise RuleError('原复诊窗口或方案已变化，请联系原门店协调改期。')
        if lock:
            row = NextVisitInstruction.objects.select_for_update().get(pk=row.pk)
            if row.state != 'OPEN':
                raise RuleError('复诊指示已撤回，请联系原门店协调改期。')
        first = max(first, row.earliest_on) if first else row.earliest_on
        last = min(last, row.latest_on) if last else row.latest_on
    return (first, last) if first is not None else None


def treatment_basis(visit, step, *, lock=False):
    links = linked_instructions(visit)
    matches = Q(instruction__step_version__isnull=True)
    if step is not None:
        matches |= Q(instruction__step_version__step_id=step.step_id)
    else:
        # A plan-outside item cannot bypass a related instruction by omitting its step.
        matches = Q()
    instruction_ids = set(links.filter(matches).values_list('instruction_id', flat=True))
    order_ids = ExaminationFollowup.objects.filter(instruction_id__in=instruction_ids).values('release__order_id')
    orders = ExaminationOrder.objects.filter(pk__in=order_ids).select_related('project', 'active_release__report').order_by('pk')
    if lock:
        # Publication checks the same professional scopes before taking the order lock.
        for service_id in sorted(set(orders.values_list('project__service_id', flat=True))):
            professional_scope(visit.dentist.useraccount.pk, visit.clinic_id, service_id, 'READ', lock=True)
        orders = orders.select_for_update(of=('self',))
    basis = []
    for order in orders:
        professional_scope(visit.dentist.useraccount.pk, visit.clinic_id, order.project.service_id, 'READ')
        decision = current_decision(order)
        if (decision is None or decision.instruction_id not in instruction_ids
                or decision.instruction.service_id != visit_service_id(visit)
                or decision.instruction.state != 'OPEN' or not current_plan_step(decision.instruction)):
            raise RuleError('复诊所依据的报告或指示已变化，请先由医师核对当前安排。')
        if lock:
            instruction = NextVisitInstruction.objects.select_for_update().get(pk=decision.instruction_id)
            if instruction.state != 'OPEN':
                raise RuleError('复诊指示已撤回，请核对当前安排。')
        basis.append(dict(order=order.pk, release=order.active_release_id, revision=order.active_release.report.number,
            decision=decision.pk, instruction=decision.instruction_id, number=order.number))
    return basis
