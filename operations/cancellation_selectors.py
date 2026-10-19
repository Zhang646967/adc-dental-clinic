from datetime import timedelta
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, F, Value, Case, When, CharField, OuterRef, Subquery
from django.db.models.functions import ExtractHour, ExtractIsoWeekDay, Coalesce
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import BUSINESS_TZ
from adc_core.proposals import workspace_binding
from adc_core.snapshots import reporting_snapshot
from care.models import AuditEvent
from scheduling.models import Visit
from operations.selectors import allowed_clinics
from operations.policies import period_bounds
from operations.models import CancellationFollowUp, AppointmentImprovement
from operations.cancellation_policy import BANDS, WEEKDAYS, REASONS, metric_dict, POLICY

def local_clinic(actor, roles=('MANAGER', 'FRONT_DESK')):
    binding = workspace_binding(actor, roles)
    if binding['clinic'] is None:
        raise PermissionDenied('请先选择当前诊所。')
    return binding['clinic']

def owners(clinic, roles=('MANAGER', 'FRONT_DESK')):
    return UserAccount.objects.filter(is_active=True, role_assignments__is_active=True,
        role_assignments__clinic_id=clinic, role_assignments__role__in=roles,
        role_assignments__scope_kind='CLINIC').distinct().order_by('username')

def period_visits(clinic, start, end):
    lo, hi = period_bounds(start, end)
    return Visit.objects.filter(clinic_id=clinic, scheduled_start__gte=lo, scheduled_start__lt=hi).annotate(
        weekday=ExtractIsoWeekDay('scheduled_start', tzinfo=BUSINESS_TZ),
        hour=ExtractHour('scheduled_start', tzinfo=BUSINESS_TZ)).annotate(
        band=Case(*[When(hour__gte=h, hour__lt=h+2, then=Value(code))
                    for h, (code, _) in zip(range(8, 20, 2), BANDS)],
                  default=Value('OTHER'), output_field=CharField()))

def counts(base, now):
    return list(base.filter(scheduled_end__lte=now).exclude(status='RESCHEDULED')
        .values('weekday', 'band', 'status', 'cancellation_party').annotate(n=Count('pk')).order_by())

def cell_metrics(clinic, start, end, weekday, band, now=None):
    now = now or timezone.now()
    base = period_visits(clinic, start, end).filter(weekday=weekday, band=band)
    groups = counts(base, now)
    return metric_dict((g['status'], g['cancellation_party'], g['n']) for g in groups)

def cancellation_report(actor, start, end, clinic_id=None, weekday=None, band=None):
    period_bounds(start, end)
    with reporting_snapshot():
        clinics = list(allowed_clinics(actor).order_by('clinic_code'))
        ids = {c.pk for c in clinics}
        if clinic_id is not None and clinic_id not in ids:
            raise PermissionDenied('不能查询未授权诊所。')
        if clinic_id is None and len(clinics) == 1:
            clinic_id = clinics[0].pk
        result = dict(clinics=clinics, clinic_id=clinic_id, start=start, end=end, as_of=timezone.now(), policy=POLICY)
        if clinic_id is None:
            result['choose_clinic'] = True
            return result
        base = period_visits(clinic_id, start, end)
        grouped = counts(base, result['as_of'])
        rows = []
        for day, label in WEEKDAYS:
            cells = []
            for code, band_label in BANDS:
                m = metric_dict((g['status'], g['cancellation_party'], g['n'])
                               for g in grouped if g['weekday'] == day and g['band'] == code)
                cells.append(dict(m, weekday=day, day_label=label, band=code, band_label=band_label))
            rows.append(dict(label=label, cells=cells))
        result['grid'] = rows
        result['ranking'] = sorted((c for r in rows for c in r['cells'] if c['eligible']),
            key=lambda c: (-c['cancel_rate'], -c['denominator'], c['weekday'], c['band']))[:5]
        selected = base
        if weekday: selected = selected.filter(weekday=weekday)
        if band: selected = selected.filter(band=band)
        scope = counts(selected, result['as_of'])
        result['metrics'] = metric_dict((g['status'], g['cancellation_party'], g['n']) for g in scope)
        result['future'] = selected.filter(scheduled_end__gt=result['as_of']).exclude(status='RESCHEDULED').count()
        result['replaced'] = selected.filter(status='RESCHEDULED').count()
        cancelled = selected.filter(status='CANCELLED', scheduled_end__lte=result['as_of'])
        reasons = dict(cancelled.annotate(code=Coalesce('cancellation_followup__reason_code', Value('UNSUPPLIED')))
            .values('code').annotate(n=Count('pk')).values_list('code', 'n'))
        result['reasons'] = [(code, label, reasons.get(code, 0)) for code, label in REASONS]
        result['followups'] = cancelled.aggregate(
            missing=Count('pk', filter=Q(cancellation_followup__isnull=True)),
            pending=Count('pk', filter=Q(cancellation_followup__state__in=['OPEN', 'WAITING'])),
            overdue=Count('pk', filter=Q(cancellation_followup__state__in=['OPEN', 'WAITING'],
                cancellation_followup__due_on__lt=timezone.localdate())))
        stamp = AuditEvent.objects.filter(visit_id=OuterRef('pk'), subject_type='visit',
            event_type__in=['VISIT_CANCELLED', 'PORTAL_CANCELLED'],
            occurred_at__lte=result['as_of']).order_by('occurred_at', 'pk').values('occurred_at')[:1]
        result['lead'] = cancelled.annotate(cancelled_at=Subquery(stamp)).aggregate(
            within24=Count('pk', filter=Q(cancelled_at__gte=F('scheduled_start')-timedelta(hours=24), cancelled_at__lte=F('scheduled_start'))),
            earlier=Count('pk', filter=Q(cancelled_at__lt=F('scheduled_start')-timedelta(hours=24))),
            after_start=Count('pk', filter=Q(cancelled_at__gt=F('scheduled_start'))),
            unknown=Count('pk', filter=Q(cancelled_at__isnull=True)))
        result['actions'] = list(AppointmentImprovement.objects.filter(clinic_id=clinic_id).values('state').annotate(n=Count('pk')).order_by('state'))
        return result

def followup_visits(actor):
    clinic = local_clinic(actor, ('FRONT_DESK',))
    return Visit.objects.filter(clinic_id=clinic, status='CANCELLED').select_related(
        'patient', 'dentist', 'clinic', 'cancellation_followup', 'cancellation_followup__assigned_to')

def improvement_scope(actor):
    clinic = local_clinic(actor)
    rows = AppointmentImprovement.objects.filter(clinic_id=clinic).select_related('clinic', 'assigned_to', 'submitted_by', 'reviewed_by')
    if actor._adc_workspace.role == 'FRONT_DESK':
        rows = rows.filter(assigned_to=actor)
    return rows
