from dataclasses import dataclass
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.utils import timezone
from accounts.policies import bindings,clinic_ids
from adc_core.snapshots import reporting_snapshot
from registry.models import Clinic
from scheduling.models import Visit
from operations.policies import summarize,period_bounds,POLICY_VERSION

def allowed_clinics(actor):
    grants=bindings(actor)
    if grants.filter(role='HQ',scope_kind='CHAIN').exists():return Clinic.objects.all()
    ids=clinic_ids(actor,('MANAGER',))
    if not grants.filter(role='MANAGER',scope_kind='CLINIC').exists():
        raise PermissionDenied('需要诊所主管或总部运营查询授权。')
    return Clinic.objects.filter(pk__in=ids)

def operation_report(actor,start_date,end_date,clinic_id=None):
    with reporting_snapshot():
        clinics=allowed_clinics(actor).order_by('clinic_code')
        permitted=tuple(clinics.values('id','name','clinic_code'))
        ids={x['id'] for x in permitted}
        if clinic_id is not None and clinic_id not in ids:raise PermissionDenied('不能查询未授权诊所。')
        selected=[clinic_id] if clinic_id is not None else list(ids)
        start,end=period_bounds(start_date,end_date);now=timezone.now()
        base=Visit.objects.filter(clinic_id__in=selected,scheduled_start__gte=start,scheduled_start__lt=end)
        mature=base.filter(scheduled_end__lte=now).exclude(status='RESCHEDULED')
        grouped=list(mature.values('clinic_id','status','cancellation_party').annotate(n=Count('id')).order_by())
        metrics=summarize((g['status'],g['cancellation_party'],g['n']) for g in grouped)
        rows=tuple({'name':c['name'],'code':c['clinic_code'],'metrics':summarize((g['status'],g['cancellation_party'],g['n']) for g in grouped if g['clinic_id']==c['id'])} for c in permitted if c['id'] in selected)
        return {'metrics':metrics,'rows':rows,'clinics':permitted,'start':start_date,'end':end_date,'as_of':now,
            'future':base.filter(scheduled_end__gt=now).exclude(status='RESCHEDULED').count(),
            'replaced':base.filter(status='RESCHEDULED').count(),'policy_version':POLICY_VERSION,'clinic_id':clinic_id}
