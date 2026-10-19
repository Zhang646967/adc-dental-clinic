"""Bounded replacement-time search; never holds a time or changes a booking."""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from adc_core.rules import BUSINESS_TZ, OCCUPYING_STATUSES, RuleError, validate_slot
from adc_core.snapshots import reporting_snapshot
from coordination.models import WaitOffer
from scheduling.front_coordination_selectors import require_front_coordination
from scheduling.models import AvailabilitySlot, Visit
from scheduling.selectors import booking_slots
from scheduling.worklists import day_bounds

HORIZON_DAYS = 14
STEP = timedelta(minutes=30)
MAX_SLOTS = 80
MAX_RELATIONS = 1000
MAX_CELLS = 480
MAX_OPTIONS = 30
MAX_SEARCH_DURATION = timedelta(hours=12)


def owned_source(actor, visit_id):
    context = require_front_coordination(actor)
    # Scope first: foreign and absent IDs disclose the same result.
    return Visit.objects.select_related('patient', 'dentist', 'clinic').get(
        pk=visit_id, clinic_id=context.clinic_id)


def check_source(visit):
    if visit.status != 'SCHEDULED':
        raise RuleError('原预约状态已变化，请先核对当前记录及关联预约。')
    if not visit.patient.is_active:
        raise RuleError('患者资料已停用，不能办理新预约；原记录仍保留。')


def check_target(visit, slot, start, end, now):
    if (slot.clinic_id != visit.clinic_id or not slot.is_active or slot.booking_paused or
            not slot.clinic.is_active or not slot.dentist.is_active):
        raise RuleError('新的出诊不属于当前诊所，或已停止接收，请重新选择。')
    validate_slot(start, end, slot.starts_at, slot.ends_at, now)
    if (slot.dentist_id == visit.dentist_id and start == visit.scheduled_start and
            end == visit.scheduled_end):
        raise RuleError('新安排与原预约相同，请选择实际需要更改的时间或牙医。')
    busy = Visit.objects.filter(status__in=OCCUPYING_STATUSES,
        scheduled_start__lt=end, scheduled_end__gt=start).exclude(pk=visit.pk).filter(
        Q(patient_id=visit.patient_id) | Q(dentist_id=slot.dentist_id))
    held = WaitOffer.objects.filter(state='PENDING', expires_at__gt=now,
        starts_at__lt=end, ends_at__gt=start).filter(
        Q(request__patient_id=visit.patient_id) | Q(slot__dentist_id=slot.dentist_id))
    if busy.exists() or held.exists():
        raise RuleError('该时间已有患者／牙医安排或有效候补保留，请重新选择；原预约未改变。')


def replacement_options(*, actor, visit_id, day, dentist_id=None):
    with reporting_snapshot():
        visit = owned_source(actor, visit_id)
        check_source(visit)
        now = timezone.now()
        today = now.astimezone(BUSINESS_TZ).date()
        if day < today or day > today + timedelta(days=HORIZON_DAYS):
            raise RuleError('请选择今日起未来14天内的日期。')
        from scheduling.resources import policy,current_plan
        if policy(visit.clinic_id):
            plan=current_plan(visit)
            if plan is None:raise RuleError('原预约尚未核实服务和资源，请先进入资源协调。')
            from scheduling.resource_candidates import candidates
            rows=candidates(clinic_id=visit.clinic_id,service_id=plan.service_id,day=day,
                patient_id=visit.patient_id,dentist_id=dentist_id,ignore_visit=visit.pk)
            rows=[dict(r,dentist=r['slot'].dentist.name) for r in rows if not (r['slot'].dentist_id==visit.dentist_id and r['start']==visit.scheduled_start and r['end']==visit.scheduled_end)]
            return {'rows':rows[:MAX_OPTIONS],'observed_at':now,'limited':len(rows)>MAX_OPTIONS,'checked_cells':len(rows),
                'duration_minutes':plan.service.duration_minutes,'limit_reason':'按服务时长及诊疗资源核对'}
        duration = visit.scheduled_end - visit.scheduled_start
        result = {'rows': [], 'observed_at': now, 'limited': False, 'checked_cells': 0,
                  'duration_minutes': duration.total_seconds() / 60, 'limit_reason': ''}
        if not timedelta(0) < duration <= MAX_SEARCH_DURATION:
            return dict(result, limited=True, limit_reason='原预约时长超出自动搜索范围，请人工核对；不能据此认定没有空闲时段。')
        begin, finish = day_bounds(day)
        earliest = max(begin, now)
        horizon = now + timedelta(days=HORIZON_DAYS)
        latest_start = min(finish, horizon)
        slots = booking_slots(actor).filter(starts_at__lt=finish, ends_at__gt=earliest)
        if dentist_id is not None:
            slots = slots.filter(dentist_id=dentist_id)
        slots = list(slots.order_by('starts_at', 'dentist_id', 'pk')[:MAX_SLOTS + 1])
        if len(slots) > MAX_SLOTS:
            slots = slots[:MAX_SLOTS]
            result.update(limited=True, limit_reason='仅核对前80条出诊，请缩小日期或牙医范围。')
        if not slots:
            return result
        dentists = {slot.dentist_id for slot in slots}
        upper = latest_start + duration
        occupied = list(Visit.objects.filter(status__in=OCCUPYING_STATUSES,
            scheduled_start__lt=upper, scheduled_end__gt=earliest).exclude(pk=visit.pk).filter(
            Q(patient_id=visit.patient_id) | Q(dentist_id__in=dentists)).values(
                'patient_id', 'dentist_id', 'scheduled_start', 'scheduled_end')[:MAX_RELATIONS + 1])
        holds = list(WaitOffer.objects.filter(state='PENDING', expires_at__gt=now,
            starts_at__lt=upper, ends_at__gt=earliest).filter(
            Q(request__patient_id=visit.patient_id) | Q(slot__dentist_id__in=dentists)).values(
                'request__patient_id', 'slot__dentist_id', 'starts_at', 'ends_at')[:MAX_RELATIONS + 1])
        if len(occupied) > MAX_RELATIONS or len(holds) > MAX_RELATIONS:
            return dict(result, limited=True, limit_reason='关联安排超过本次核对上限，未返回候选；请缩小查询或人工核对。')
        intervals = [(v['patient_id'], v['dentist_id'], v['scheduled_start'], v['scheduled_end']) for v in occupied]
        intervals += [(v['request__patient_id'], v['slot__dentist_id'], v['starts_at'], v['ends_at']) for v in holds]
        for slot in slots:
            lower = max(slot.starts_at, earliest)
            start = slot.starts_at + ((lower - slot.starts_at) // STEP) * STEP
            if start < lower:
                start += STEP
            while start < finish and start <= horizon and start + duration <= slot.ends_at:
                if result['checked_cells'] >= MAX_CELLS:
                    return dict(result, limited=True, limit_reason='已达到480个开始时间的核对上限，请缩小查询。')
                result['checked_cells'] += 1
                end = start + duration
                unchanged = slot.dentist_id == visit.dentist_id and start == visit.scheduled_start and end == visit.scheduled_end
                blocked = any((patient == visit.patient_id or dentist == slot.dentist_id) and start < b and a < end
                              for patient, dentist, a, b in intervals)
                if not unchanged and not blocked:
                    if len(result['rows']) >= MAX_OPTIONS:
                        return dict(result, limited=True, limit_reason='先显示前30个候选，可更换日期或牙医继续查询。')
                    result['rows'].append({'slot_id': slot.pk, 'dentist': slot.dentist.name,
                        'start': start, 'end': end, 'start_iso': start.isoformat(), 'end_iso': end.isoformat()})
                start += STEP
        return result
