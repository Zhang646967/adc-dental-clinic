"""Front-desk preview/confirmation, using the existing slot and audit history."""
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from accounts.policies import lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError,validate_interval
from care.models import AuditEvent
from registry.models import Dentist
from scheduling.models import AvailabilitySlot
from scheduling.availability_services import require_availability_actor
from scheduling.services import create_slot

CONTRACT='adc.front.slot-create.b131'

def prepare_slot_creation(*,actor,clinic_id,dentist_id,start,end):
    ctx=require_availability_actor(actor)
    if clinic_id!=ctx.clinic_id:raise RuleError('请在当前诊所登记出诊。')
    validate_interval(start,end)
    if start<=timezone.now():raise RuleError('新出诊安排必须位于未来。')
    dentist=Dentist.objects.get(pk=dentist_id,is_active=True)
    if AvailabilitySlot.objects.filter(dentist=dentist,is_active=True,starts_at__lt=end,ends_at__gt=start).exists():
        raise RuleError('该医师已有重叠出诊（含其他诊所），请核对时间。')
    data=dict(clinic=clinic_id,dentist=dentist_id,start=start.isoformat(),end=end.isoformat())
    return dict(clinic=ctx.clinic.name,dentist=dentist.name,start=start,end=end,
        proposal_token=proposal(actor,CONTRACT,('FRONT_DESK',),data))

@business_errors
@transaction.atomic
def confirm_slot_creation(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对医师工作安排和出诊时间后确认。')
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);d=p['data']
    lock_clinic_grant(actor,d['clinic'])
    old=AuditEvent.objects.filter(actor=actor,event_type='SLOT_CREATED',subject_type='availabilityslot',
        change_summary__operation=p['operation']).first()
    if old:return AvailabilitySlot.objects.get(pk=old.subject_key,clinic_id=d['clinic']),True
    slot=create_slot(actor=actor,clinic_id=d['clinic'],dentist_id=d['dentist'],
        start=datetime.fromisoformat(d['start']),end=datetime.fromisoformat(d['end']),operation_id=p['operation'])
    return slot,False
