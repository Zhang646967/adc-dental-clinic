"""Front-desk explicit booking preview, shared with telephone reception."""
from datetime import datetime
from django.db import transaction
from django.utils import timezone
from adc_core.proposals import proposal,read_proposal
from adc_core.commands import business_errors
from adc_core.rules import RuleError,validate_slot
from accounts.policies import lock_clinic_grant
from patients.models import Patient
from scheduling.models import AvailabilitySlot,Visit
from scheduling.resources import choose_bundle
from scheduling.resource_models import ResourceAction
from scheduling.services import create_appointment
from coordination.reservations import assert_free

CONTRACT='adc.front.booking.resources.v1'

def prepare_booking(*,actor,patient_no,slot_id,start,end,service_id,consent,
                    chief_complaint='',special_needs='',treatment_request=''):
    if consent is not True:raise RuleError('请先复述预约安排，并记录患者明确同意。')
    clinic=actor._adc_workspace.clinic_id
    from accounts.policies import require_clinic
    require_clinic(actor,clinic)
    patient=Patient.objects.get(patient_no=patient_no,is_active=True)
    patient.full_clean()
    slot=AvailabilitySlot.objects.select_related('clinic','dentist').get(pk=slot_id,clinic_id=clinic,is_active=True,booking_paused=False)
    validate_slot(start,end,slot.starts_at,slot.ends_at,timezone.now())
    assert_free(patient.pk,slot.dentist_id,start,end)
    bundle=choose_bundle(slot=slot,start=start,end=end,service_id=service_id)
    data={'patient':patient.pk,'patient_no':patient.patient_no,'slot':slot.pk,'intake_revision':slot.intake_revision,
        'start':start.isoformat(),'end':end.isoformat(),'service_id':service_id,'resources':bundle,
        'chief_complaint':chief_complaint,'special_needs':special_needs,'treatment_request':treatment_request}
    return {'patient':patient,'slot':slot,'start':start,'end':end,'resources':bundle,
        'proposal_token':proposal(actor,CONTRACT,('FRONT_DESK',),data)}

@business_errors
@transaction.atomic
def confirm_booking(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确确认患者已同意完整预约安排。')
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);d=p['data'];clinic=actor._adc_workspace.clinic_id
    lock_clinic_grant(actor,clinic)
    previous=ResourceAction.objects.filter(operation_id=p['operation'],actor=actor,clinic_id=clinic,kind='FRONT_BOOKING').first()
    if previous:return Visit.objects.get(pk=previous.result['visit']),True
    from scheduling.coordination import lock_slots
    slot=lock_slots([d['slot']])[d['slot']]
    if slot.clinic_id!=clinic or slot.intake_revision!=d['intake_revision']:raise RuleError('出诊接收状态已变化，请重新预览。')
    patient=Patient.objects.get(pk=d['patient'],patient_no=d['patient_no'],is_active=True);patient.full_clean()
    visit=create_appointment(actor=actor,patient_no=patient.patient_no,slot_id=slot.pk,
        start=datetime.fromisoformat(d['start']),end=datetime.fromisoformat(d['end']),service_id=d['service_id'],resource_snapshot=d['resources'],
        chief_complaint=d['chief_complaint'],special_needs=d['special_needs'],requests=[d['treatment_request']] if d['treatment_request'] else [])
    ResourceAction.objects.create(clinic_id=clinic,actor=actor,operation_id=p['operation'],kind='FRONT_BOOKING',result={'visit':visit.pk})
    return visit,False
