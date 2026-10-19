"""Explicit same-time/provider resource replacement, without moving a patient."""
from collections import Counter
from copy import copy
from types import SimpleNamespace
from datetime import datetime
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from accounts.policies import lock_clinic_grant,require_clinic
from adc_core.rules import RuleError
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from care.audit import emit
from scheduling.models import Visit
from scheduling.resource_models import ResourcePlan,ResourceClaim,ResourceCoordination,ResourceAction
from scheduling.resources import ResourceCalendar,lock_physical,release_expired_locked,claim_locked
from scheduling.coordination import lock_slots
from coordination.reservations import lock_resources

CONTRACT='adc.resource.coordination.v1'

def scope(actor,front=False):
    ctx=getattr(actor,'_adc_workspace',None)
    if not ctx or ctx.role not in (('FRONT_DESK',) if front else ('MANAGER','FRONT_DESK')) or not ctx.clinic_id:raise PermissionDenied
    require_clinic(actor,ctx.clinic_id,roles=(ctx.role,));return ctx.clinic_id

def plans_for(actor):
    clinic=scope(actor)
    return ResourcePlan.objects.filter(Q(visit__clinic_id=clinic)|Q(offer__request__clinic_id=clinic)).select_related(
        'visit','offer__request','offer__slot','service__department','room')

def live(plan):
    if plan.visit_id:
        return plan.visit.status in ('SCHEDULED','CHECKED_IN')
    return plan.offer.state=='PENDING' and plan.offer.expires_at>timezone.now()

def replacement_options(actor,plan_id):
    plan=plans_for(actor).get(pk=plan_id,is_current=True)
    if not live(plan):raise RuleError('原承诺已结束，请保留协调历史并核对最终业务结果。')
    if plan.visit_id and plan.visit.status=='CHECKED_IN':raise RuleError('患者正在接诊，请由医护人工处置并记录；本阶段不自动搬迁患者。')
    a,b=(plan.visit.scheduled_start,plan.visit.scheduled_end) if plan.visit_id else (plan.offer.starts_at,plan.offer.ends_at)
    dentist=plan.visit.dentist_id if plan.visit_id else plan.offer.slot.dentist_id
    service=copy(plan.service);service.duration_minutes=plan.snapshot['service']['duration']
    counts=Counter(r['category'] for r in plan.snapshot['resources'] if r['category']!='CHAIR')
    requirements=[SimpleNamespace(category=k,quantity=v) for k,v in sorted(counts.items())]
    calendar=ResourceCalendar(plan.service.department.clinic_id,a,b,ignore_visit=plan.visit_id,ignore_offer=plan.offer_id)
    bundles=calendar.bundles(service,dentist,a,b,limit=20,requirements=requirements)
    current=sorted(r['id'] for r in plan.snapshot['resources'])
    return plan,[x for x in bundles if sorted(r['id'] for r in x['resources'])!=current]

def prepare_coordination(*,actor,plan_id,action,fields):
    clinic=scope(actor,front=True);plan=plans_for(actor).get(pk=plan_id,is_current=True)
    note=str(fields.get('note','')).strip()
    if not 1<=len(note)<=500:raise RuleError('请记录本次资源协调依据（1至500字）。')
    data={'plan':plan.pk,'version':plan.version,'action':action,'note':note,'issue':None,'issue_revision':None}
    if action=='REPLACE':
        _,options=replacement_options(actor,plan_id)
        chosen=[int(x) for x in fields.get('assets',[])]
        bundle=next((x for x in options if sorted(r['id'] for r in x['resources'])==sorted(chosen)),None)
        if not bundle:raise RuleError('替换组合当前不可用，请重新核对；医师和时间未改变。')
        data['bundle']=bundle
    elif action=='OPEN':
        from reception.services import _owner,_at
        asset=int(fields['asset'])
        if not plan.claims.filter(asset_id=asset).exists():raise RuleError('请从原资源方案选择协调设备。')
        owner=int(fields['owner']);_owner(owner,clinic)
        data.update(asset=asset,owner=owner,due_at=_at(fields['due_at']).isoformat())
    elif action in ('CONTACT','RESOLVE'):
        issue=ResourceCoordination.objects.get(pk=int(fields['issue']),plan=plan,state__in=['OPEN','CONTACT'])
        data.update(issue=issue.pk,issue_revision=issue.revision)
        if action=='CONTACT':
            from reception.services import _owner
            owner=int(fields['owner']);_owner(owner,clinic)
            due=datetime.fromisoformat(fields['due_at']) if isinstance(fields['due_at'],str) else fields['due_at']
            if timezone.is_naive(due):raise RuleError('联系期限必须有明确时区。')
            data.update(owner=owner,due_at=due.isoformat())
    else:raise RuleError('资源协调操作无效。')
    return {'plan':plan,'data':data,'proposal_token':proposal(actor,CONTRACT,('FRONT_DESK',),data)}

@business_errors
@transaction.atomic
def confirm_coordination(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对兼容性及原承诺后明确确认。')
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);d=p['data'];clinic=scope(actor,front=True)
    lock_clinic_grant(actor,clinic)
    old=ResourceAction.objects.filter(operation_id=p['operation'],actor=actor,clinic_id=clinic).first()
    if old:return old,True
    preview=plans_for(actor).get(pk=d['plan'])
    slot_id=preview.visit.availability_slot_id if preview.visit_id else preview.offer.slot_id
    lock_slots([slot_id])
    patient=preview.visit.patient_id if preview.visit_id else preview.offer.request.patient_id
    dentist=preview.visit.dentist_id if preview.visit_id else preview.offer.slot.dentist_id
    lock_resources(patients=[patient],dentists=[dentist]);lock_physical(clinic);release_expired_locked(clinic)
    plan=ResourcePlan.objects.select_for_update().get(pk=d['plan'])
    if not plan.is_current or plan.version!=d['version']:raise RuleError('资源方案已有更新，请刷新协调历史。')
    if plan.visit_id:
        Visit.objects.select_for_update().get(pk=plan.visit_id)
    action=d['action'];result={'plan':plan.pk,'note':d['note']}
    if action=='REPLACE':
        _,options=replacement_options(actor,plan.pk)
        if d['bundle'] not in options:raise RuleError('替换资源已被占用或配置变化，请重新查询；原承诺保留。')
        a,b=(preview.visit.scheduled_start,preview.visit.scheduled_end) if plan.visit_id else (preview.offer.starts_at,preview.offer.ends_at)
        plan.claims.filter(active=True).update(active=False,released_at=timezone.now(),release_reason='RESOURCE_REPLACED')
        plan.is_current=False;plan.save(update_fields=['is_current'])
        new=claim_locked(actor=actor,snapshot=d['bundle'],start=a,end=b,visit=preview.visit if plan.visit_id else None,
            offer=preview.offer if not plan.visit_id else None,reason=d['note'],version=plan.version+1)
        ResourceCoordination.objects.filter(plan=plan,state__in=['OPEN','CONTACT']).update(state='REPLACED',revision=F('revision')+1)
        result['new_plan']=new.pk
    elif action=='OPEN':
        from reception.services import _owner
        _owner(d['owner'],clinic,True)
        issue,_=ResourceCoordination.objects.get_or_create(plan=plan,asset_id=d['asset'],state__in=['OPEN','CONTACT'],
            defaults={'state':'OPEN','reason':d['note']})
        issue.state='CONTACT';issue.owner_id=d['owner'];issue.due_at=datetime.fromisoformat(d['due_at']);issue.revision+=1;issue.save()
        result.update(issue=issue.pk,owner=d['owner'],due_at=d['due_at'])
    else:
        issue=ResourceCoordination.objects.select_for_update().get(pk=d['issue'],plan=plan,state__in=['OPEN','CONTACT'])
        if issue.revision!=d['issue_revision']:raise RuleError('联系责任已有更新，请刷新。')
        if action=='CONTACT':
            from reception.services import _owner
            _owner(d['owner'],clinic,True);issue.owner_id=d['owner'];issue.due_at=datetime.fromisoformat(d['due_at']);issue.state='CONTACT'
            result.update(owner=d['owner'],due_at=d['due_at'])
        elif action=='RESOLVE':
            from scheduling.resources import plan_location_valid
            from scheduling.resource_models import ResourceBlock
            a,b=(preview.visit.scheduled_start,preview.visit.scheduled_end) if plan.visit_id else (preview.offer.starts_at,preview.offer.ends_at)
            ids=list(plan.claims.values_list('asset_id',flat=True))
            blocked=ResourceBlock.objects.filter(clinic_id=clinic,is_active=True,starts_at__lt=b,ends_at__gt=a).filter(Q(asset_id__in=ids)|Q(room_id=plan.room_id)|Q(department_id=plan.service.department_id)).exists()
            overrun=ResourceClaim.objects.filter(asset_id__in=ids,plan__is_current=True,plan__visit__status='CHECKED_IN').exclude(plan__visit_id=plan.visit_id).exists()
            if live(preview) and (issue.asset.state!='IN_SERVICE' or not plan_location_valid(preview) or blocked or overrun or ResourceClaim.objects.filter(plan=plan,active=True).count()==0):
                raise RuleError('设备仍不可用或原承诺尚未解决，请继续联系或明确替换。')
            issue.state='RESOLVED'
        issue.revision+=1;issue.save();result['issue']=issue.pk
    record=ResourceAction.objects.create(clinic_id=clinic,actor=actor,operation_id=p['operation'],kind='COORD_'+action,result=result)
    emit(actor,'RESOURCE_COORDINATED',record,summary={'clinic_id':clinic,'action':action,'plan_id':plan.pk})
    return record,False

from django.db.models import F
