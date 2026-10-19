"""Explicit verification of pre-existing promises during clinic preparation."""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from adc_core.rules import RuleError
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from equipment.policies import manager_clinic
from scheduling.models import Visit,AvailabilitySlot
from scheduling.resource_models import ResourcePolicy,ResourcePlan,ResourceAction
from scheduling.resources import choose_bundle,claim_locked,lock_physical
from scheduling.coordination import lock_slots
from coordination.reservations import lock_resources
from coordination.models import WaitOffer
from care.audit import emit

CONTRACT='adc.resource.existing-promise.v1'

def _source(clinic,kind,pk,locked=False):
    if kind=='visit':
        qs=Visit.objects.filter(clinic_id=clinic,status__in=['SCHEDULED','CHECKED_IN'])
        if locked:qs=qs.select_for_update()
        row=qs.get(pk=pk)
        if row.status=='SCHEDULED' and row.scheduled_end<=timezone.now():raise RuleError('原预约已到期，请先核实实际办理结果。')
        return row,row.availability_slot,row.patient_id,row.scheduled_start,row.scheduled_end,row.lock_version
    if kind=='offer':
        qs=WaitOffer.objects.filter(request__clinic_id=clinic,state='PENDING',expires_at__gt=timezone.now())
        if locked:qs=qs.select_for_update()
        row=qs.get(pk=pk)
        return row,row.slot,row.request.patient_id,row.starts_at,row.ends_at,0
    raise RuleError('请明确原预约或有效邀约。')

def prepare_mapping(*,actor,kind,source_id,service_id,note):
    clinic=manager_clinic(actor);p=ResourcePolicy.objects.get(clinic_id=clinic,state='PREPARING')
    row,slot,patient,a,b,v=_source(clinic,kind,source_id)
    if ResourcePlan.objects.filter(**{kind:row},is_current=True).exists():raise RuleError('原承诺已有资源核对结果。')
    if not 1<=len(note.strip())<=500:raise RuleError('请记录实际核实依据。不得补造原始来源或科室。')
    bundle=choose_bundle(slot=slot,start=a,end=b,service_id=service_id,preparing=True)
    d={'kind':kind,'source':source_id,'version':v,'policy_revision':p.revision,'service':service_id,'bundle':bundle,'note':note.strip()}
    return {'fields':d,'proposal_token':proposal(actor,CONTRACT,('MANAGER',),d)}

@business_errors
@transaction.atomic
def confirm_mapping(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请确认已经核实原承诺所需资源。')
    p=read_proposal(actor,CONTRACT,('MANAGER',),proposal_token);d=p['data'];clinic=manager_clinic(actor,lock=True)
    prior=ResourceAction.objects.filter(operation_id=p['operation'],actor=actor,clinic_id=clinic).first()
    if prior:return prior,True
    row,slot,patient,a,b,v=_source(clinic,d['kind'],d['source'])
    lock_slots([slot.pk]);lock_resources(patients=[patient],dentists=[slot.dentist_id]);lock_physical(clinic)
    row,slot,patient,a,b,v=_source(clinic,d['kind'],d['source'],True)
    policy=ResourcePolicy.objects.get(clinic_id=clinic,state='PREPARING')
    if v!=d['version'] or policy.revision!=d['policy_revision']:raise RuleError('原承诺或目录已有变化，请重新核实。')
    if ResourcePlan.objects.filter(**{d['kind']:row},is_current=True).exists():raise RuleError('原承诺已有其他资源核对结果，请刷新。')
    bundle=choose_bundle(slot=slot,start=a,end=b,service_id=d['service'],expected=d['bundle'],locked=True,preparing=True)
    plan=claim_locked(actor=actor,snapshot=bundle,start=a,end=b,reason='原承诺逐项核实：'+d['note'],**{d['kind']:row})
    action=ResourceAction.objects.create(clinic_id=clinic,operation_id=p['operation'],actor=actor,kind='MAP_EXISTING',result={'plan':plan.pk,'kind':d['kind'],'source':row.pk,'note':d['note']})
    emit(actor,'RESOURCE_PROMISE_VERIFIED',action,summary={'clinic_id':clinic,'plan_id':plan.pk,'kind':d['kind']})
    return action,False
