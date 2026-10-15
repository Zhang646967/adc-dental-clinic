"""Synthetic capacity fixture, only in an explicitly marked empty rehearsal.

Run inside the pinned rehearsal container, capture stdout NDJSON to an owner-only file; the final line is the manifest.
Partial failures retain committed synthetic history and private actor records.
Never rerun into a partially seeded database.
Bootstrap history is model-seeded with all PostgreSQL guards enabled; bills,
receipts, equipment and day closes use existing business commands. This is not
an import tool and never updates or deletes an existing fixture.
"""
import argparse,json,os,secrets,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from datetime import date,datetime,time,timedelta
from decimal import Decimal as D

def require_empty(condition):
    if not condition:
        raise SystemExit('Only the exact initial empty synthetic rehearsal is accepted; existing data retained.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--project',required=True);p.add_argument('--synthetic-empty-only',action='store_true');a=p.parse_args()
    if not a.synthetic_empty_only or os.environ.get('ADC_CAPACITY_REHEARSAL')!=a.project or os.environ.get('ADC_RC_INSTANCE')!=a.project or not a.project.startswith('adc_rc1_'):
        raise SystemExit('Explicit independent synthetic capacity instance required.')
    import django;django.setup()
    from django.conf import settings
    from django.db import connection
    from django.utils import timezone
    from accounts.models import UserAccount,RoleAssignment
    from registry.models import Clinic,Dentist,TreatmentType
    from patients.models import Patient
    from scheduling.models import AvailabilitySlot,Visit
    from scheduling.services import create_slot,create_appointment,change_appointment
    from care.services import review_allergies,add_treatment,complete_visit,save_clinical_note
    from care.models import Invoice
    from equipment.models import EquipmentAsset
    from equipment.services import prepare_registration,confirm_equipment,prepare_change
    from equipment.maintenance_services import prepare_maintenance,confirm_maintenance
    from finance.cash_models import CashEntry
    from finance.payment_account_services import prepare_account,confirm_account
    from finance.cash_services import prepare_cash,confirm_cash_request,prepare_review,confirm_cash_review
    from finance.daily_services import prepare_close,confirm_close,prepare_close_review,confirm_close_review
    from finance.daily_facts import day_facts
    from workspaces.models import WorkspaceContext
    from portal.models import PatientAccess
    from adc_core.rules import BUSINESS_TZ
    require_empty(connection.settings_dict['NAME']=='adc_rc_demo' and not settings.ADC_READ_ONLY and settings.AI_MODE=='demo')
    require_empty(not any(m.objects.exists() for m in (Visit,Invoice,EquipmentAsset,CashEntry)))
    require_empty(not UserAccount.objects.filter(username__startswith='capacity_').exists())
    require_empty(set(Clinic.objects.values_list("clinic_code",flat=True))=={"DEMO-1","DEMO-2"} and Patient.objects.count()==4 and Patient.objects.filter(patient_no__in=["PORTAL-DEMO-1","PORTAL-DEMO-2"]).count()==2)
    actors=[];cases=[];today=timezone.localdate();now=timezone.now()
    def actor(name,role,clinic=None,dentist=None,patient=None,measured=True):
        password=secrets.token_urlsafe(24);u=UserAccount.objects.create_user(username=name,password=password,dentist=dentist)
        if role=='PATIENT':PatientAccess.objects.create(user=u,patient=patient)
        else:RoleAssignment.objects.create(user=u,role=role,scope_kind='CLINIC' if clinic else 'SELF_DENTIST' if dentist else 'TECHNICAL' if role=='SYSADMIN' else 'CHAIN',clinic=clinic)
        u._adc_workspace=WorkspaceContext.objects.create(user=u,role=role,clinic=clinic)
        actors.append(dict(username=name,password=password,role=role,clinic=clinic.pk if clinic else None,id=u.pk,measured=measured))
        print(json.dumps({"actor":actors[-1]}),flush=True)
        return u
    def equipment(manager,code):
        v=prepare_registration(actor=manager,asset_code=code,name='SYNTHETIC '+code,category='OTHER',location='合成设备区',acquired_on=today-timedelta(days=60),acquisition_cost=D('10.01'),next_service_due=today,note='合成容量台账')
        return confirm_equipment(actor=manager,proposal_token=v['proposal_token'],confirmed=True)[0]
    def maintenance(manager,asset):
        v=prepare_change(actor=manager,asset_id=asset.pk,kind='MAINTENANCE',performed_on=today,cost=None,next_service_due=None,note='合成送修')
        confirm_equipment(actor=manager,proposal_token=v['proposal_token'],confirmed=True)
        v=prepare_maintenance(actor=manager,asset_id=asset.pk,action='OPEN',fields=dict(owner=manager.pk,due=today,issue='合成多诊所工单'),note='明确维修责任')
        return confirm_maintenance(actor=manager,proposal_token=v['proposal_token'],confirmed=True)[0]
    finance=actor('capacity_finance_0','FINANCE');actor('capacity_finance_1','FINANCE');actor('capacity_finance_2','FINANCE')
    actor('capacity_hq_0','HQ');actor('capacity_hq_1','HQ')
    treatment=TreatmentType.objects.create(code='CAP-T',name='合成容量治疗',unit_definition='一次',standard_unit_price=D('100.00'))
    for i in range(5):
        clinic=Clinic.objects.get(clinic_code='DEMO-'+str(i+1)) if i<2 else Clinic.objects.create(clinic_code='CAP-'+str(i+1),name='合成容量诊所'+str(i+1),postal_address='合成地址',supervisor_name='合成主管',phone='000',email='capacity@example.invalid',area_sqm=120)
        account=confirm_account(actor=finance,proposal_token=prepare_account(actor=finance,clinic_id=clinic.pk,code='CAP-CASH',method='CASH')['proposal_token'],confirmed=True)[0]
        front=actor('capacity_front_'+str(i),'FRONT_DESK',clinic)
        manager=actor('capacity_manager_'+str(i),'MANAGER',clinic)
        dentists=[Dentist.objects.create(employee_no=f'CAP-D{i}-{j}',name=f'合成牙医{i}-{j}',date_of_birth=date(1990,1,1),home_address='合成地址',phone='000',email='capacity@example.invalid') for j in range(2)]
        doctor=actor('capacity_doctor_'+str(i),'DENTIST',dentist=dentists[0])
        patients=Patient.objects.bulk_create([Patient(name=f'CAP-P{i}-{j}',date_of_birth=date(2000,1,1),billing_address='合成地址',phone='000',email='capacity@example.invalid',emergency_name='合成人',emergency_phone='000',created_in_clinic=clinic) for j in range(2000)])
        # 100 days, two dentists, ten visits per dentist/day. Repeat some
        # patient associations to exercise shared-patient visibility joins.
        slots=[];visits=[]
        for day in range(100):
            begin=datetime.combine(today-timedelta(days=101-day),time(8),BUSINESS_TZ)
            for j,dentist in enumerate(dentists):slots.append(AvailabilitySlot(clinic=clinic,dentist=dentist,starts_at=begin,ends_at=begin+timedelta(hours=8)))
        AvailabilitySlot.objects.bulk_create(slots)
        for index,slot in enumerate(slots):
            for k in range(10):
                start=slot.starts_at+timedelta(minutes=30*k)
                visits.append(Visit(patient=patients[(index*10+k)%400],dentist=slot.dentist,clinic=clinic,availability_slot=slot,scheduled_start=start,scheduled_end=start+timedelta(minutes=30),status='NO_SHOW'))
        Visit.objects.bulk_create(visits)
        start=datetime.combine(today+timedelta(days=10),time(8),BUSINESS_TZ)
        future=create_slot(actor=manager,clinic_id=clinic.pk,dentist_id=dentists[0].pk,start=start,end=start+timedelta(days=4))
        first_invoice=None
        for j in range(100):
            at=start+timedelta(minutes=30*j)
            visit=create_appointment(actor=front,patient_no=patients[500+j].patient_no,slot_id=future.pk,start=at,end=at+timedelta(minutes=30))
            visit=change_appointment(actor=front,visit_id=visit.pk,expected_version=visit.lock_version,action='check_in')
            review_allergies(actor=doctor,visit_id=visit.pk,expected_version=visit.lock_version,patient_version=patients[500+j].allergy_info_version,status='NO_KNOWN')
            visit.refresh_from_db();add_treatment(actor=doctor,visit_id=visit.pk,expected_version=visit.lock_version,treatment_id=treatment.pk,quantity=D('1'))
            visit.refresh_from_db();bill=complete_visit(actor=doctor,visit_id=visit.pk,expected_version=visit.lock_version,outcome='TREATED')
            first_invoice=first_invoice or bill
            v=prepare_cash(actor=front,source_type='invoice',source_id=bill.pk,kind='RECEIPT',amount=D('100.00'),occurred_on=today,reason='合成容量收款',payment_account_id=account.pk,reference=f'CAP-C{i}-{j}')
            entry=confirm_cash_request(actor=front,proposal_token=v['proposal_token'],confirmed=True)[0]
            v=prepare_review(actor=finance,entry_id=entry.pk,decision='approve',reason='合成独立财务复核');confirm_cash_review(actor=finance,proposal_token=v['proposal_token'],confirmed=True)
        # A separate editable visit is used only for signed HTTP note saves.
        at=start+timedelta(days=3);editable=create_appointment(actor=front,patient_no=patients[1999].patient_no,slot_id=future.pk,start=at,end=at+timedelta(minutes=30))
        editable=change_appointment(actor=front,visit_id=editable.pk,expected_version=0,action='check_in')
        save_clinical_note(actor=doctor,visit_id=editable.pk,expected_version=editable.lock_version,clinical_note='CAPACITY-INITIAL')
        editable.refresh_from_db();actors[-1].update(visit=editable.pk,version=editable.lock_version)
        assets=[equipment(manager,f'CAP-E{i}-{j}') for j in range(30)]
        order=maintenance(manager,assets[0])
        for offset in range(22):
            day=today-timedelta(days=offset);facts=day_facts(clinic.pk,day)
            v=prepare_close(actor=manager,business_date=day,declared=facts['totals'],evidence='合成四类独立凭据',reason='合成容量日结')
            close=confirm_close(actor=manager,proposal_token=v['proposal_token'],confirmed=True)[0]
            v=prepare_close_review(actor=finance,close_id=close.pk,decision='approve',reason='合成独立核对');confirm_close_review(actor=finance,proposal_token=v['proposal_token'],confirmed=True)
        patient_actor=actor('capacity_patient_'+str(i),'PATIENT',patient=first_invoice.visit.patient,measured=False)
        cases.append(dict(clinic=clinic.pk,account=account.pk,front=front.username,manager=manager.username,doctor=doctor.username,patient=patient_actor.username,patient_id=first_invoice.visit.patient_id,patient_no=first_invoice.visit.patient.patient_no,private_patient=patients[1500].pk,private_name=patients[1500].name,visit=first_invoice.visit_id,editable=editable.pk,invoice=first_invoice.pk,asset=assets[0].pk,maintenance=order.pk,slot=future.pk,first_patient=patients[0].pk))
        print('Seeded clinic '+str(i+1),file=sys.stderr,flush=True)
    # Preserve IDs privately. No credential or raw clinical details in public evidence.
    with connection.cursor() as c:c.execute('ANALYZE')
    print(json.dumps(dict(project=a.project,actors=actors,cases=cases,seed_method='guarded model history + normal commands for 500 bills/receipts, 150 assets and 110 daily closes',counts={m._meta.label:m.objects.count() for m in (Clinic,Patient,Visit,Invoice,EquipmentAsset,CashEntry)})))

if __name__=='__main__':main()
