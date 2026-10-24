"""C2.1 business facts, scope boundaries, retained versions and contention."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
import uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice,TreatmentRecord
from clinical import encounters as cmd
from clinical.models import ClinicalEncounter,ClinicalHistoryVersion,ClinicalDraft,ClinicalRecordVersion,ClinicalRecordEvent,ToothFinding
from clinical.tooth_rules import validate_finding
from finance.cash_models import CashEntry
from portal.models import PatientAccess
from scheduling.models import Visit
from tests.test_clinical_authority import AuthorityFixture
from workspaces.models import WorkspaceContext


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ClinicalEncounterTests(AuthorityFixture,TransactionTestCase):
    def setUp(self):
        self.setup_authority();self.authority=self.authorize();self.v=self.checked_visit()
        self.patient_user=UserAccount.objects.create_user(username='clinical_patient',password='synthetic-only-123')
        PatientAccess.objects.create(user=self.patient_user,patient=self.v.patient)
        self.ctx(self.patient_user,'PATIENT')
    def start(self,**kw):
        return cmd.start_encounter(actor=kw.pop('actor',self.doc),visit_id=self.v.pk,
            expected_visit_version=self.v.lock_version,operation_id=kw.pop('operation_id',uuid.uuid4()),**kw)[0]
    def history(self,actor=None,fields=None,expected=0,**kw):
        data=dict(medical_status='UNKNOWN',medical_history='',medication_status='UNKNOWN',medications='',allergy_status='UNKNOWN',reported_allergies='')
        data.update(fields or {})
        return cmd.submit_history(actor=actor or self.patient_user,fields=data,expected_revision=expected,
            operation_id=kw.pop('operation_id',uuid.uuid4()),confirmed=True,**kw)[0]
    def notes(self,head,**fields):
        head.refresh_from_db();data=dict(chief_complaint='PRIVATE_CHIEF',examination='PRIVATE_EXAMINATION',
            history_review='UNAVAILABLE',history_id=None,history_assessment='未取得自述；相关情况仍未知，未推断为无异常。',
            history_discrepancy='',dentition='PERMANENT',observed_at=timezone.now().isoformat())
        data.update(fields)
        return cmd.change_draft(actor=self.doc,visit_id=self.v.pk,expected_revision=head.revision,
            operation_id=uuid.uuid4(),action='NOTES',fields=data)[0]
    def step(self,head,action,fields=None,**kw):
        head.refresh_from_db()
        return cmd.change_draft(actor=self.doc,visit_id=self.v.pk,expected_revision=head.revision,
            operation_id=kw.pop('operation_id',uuid.uuid4()),action=action,fields=fields or {},**kw)[0]
    def publish(self):
        p=cmd.prepare_record(actor=self.doc,visit_id=self.v.pk)
        return cmd.confirm_record(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]

    def test_scheduled_appointment_does_not_become_an_encounter(self):
        pending=self.booking(patient=self.p2,start=self.t+timedelta(hours=1))
        with self.assertRaises(RuleError):cmd.start_encounter(actor=self.doc,visit_id=pending.pk,expected_visit_version=0,operation_id=uuid.uuid4())
        self.assertFalse(ClinicalEncounter.objects.exists())
    def test_duplicate_start_keeps_one_actual_encounter(self):
        op=uuid.uuid4();a=self.start(operation_id=op);b=self.start(operation_id=op)
        self.assertEqual(a.pk,b.pk);self.assertEqual(ClinicalEncounter.objects.count(),1)
    def test_frontdesk_cannot_record_even_when_responsible_for_booking(self):
        with self.assertRaises(PermissionDenied):self.start(actor=self.front)
    def test_c2_requires_scope_even_before_synthetic_legacy_activation(self):
        self.decide(self.authority,'REVOKE');self.ctx(self.doc,'DENTIST')
        with self.assertRaises(PermissionDenied):self.start()
        self.assertFalse(ClinicalEncounter.objects.exists())
    def test_reported_and_reviewed_history_retain_disagreement(self):
        report=self.history(fields={'allergy_status':'NO_KNOWN','reported_allergies':'患者自述未发现过敏'})
        head=self.start();self.notes(head,history_id=report.pk,history_review='REVIEWED',history_discrepancy='面谈发现自述与原有资料有差异，须继续核实。')
        self.publish();record=ClinicalRecordVersion.objects.get()
        report.refresh_from_db();self.assertEqual(report.allergy_status,'NO_KNOWN')
        self.assertIn('差异',record.history_discrepancy);self.assertEqual(record.history_id,report.pk)
    def test_self_report_does_not_change_verified_allergy_or_money(self):
        before=(self.v.patient.allergy_status,self.v.patient.allergy_info_version,Invoice.objects.count(),TreatmentRecord.objects.count(),CashEntry.objects.count())
        self.history(fields={'allergy_status':'REPORTED','reported_allergies':'PRIVATE_REPORTED_ALLERGY'})
        self.v.patient.refresh_from_db()
        self.assertEqual(before,(self.v.patient.allergy_status,self.v.patient.allergy_info_version,Invoice.objects.count(),TreatmentRecord.objects.count(),CashEntry.objects.count()))
    def test_interview_history_stays_in_its_clinic_projection(self):
        row=self.history(actor=self.doc,visit_id=self.v.pk)
        self.assertEqual(row.scope_clinic_id,self.a.pk)
        self.assertTrue(cmd.visible_history(self.v.patient_id,self.a.pk).filter(pk=row.pk).exists())
        self.assertFalse(cmd.visible_history(self.v.patient_id,self.b.pk).filter(pk=row.pk).exists())
    def test_self_and_interview_revisions_do_not_overwrite_one_another(self):
        own=self.history();interview=self.history(actor=self.doc,visit_id=self.v.pk)
        self.assertEqual((own.revision,interview.revision),(1,1))
        newer=self.history(expected=1,fields={'medication_status':'REPORTED','medications':'PRIVATE_MEDICATION'})
        self.assertEqual(newer.previous_id,own.pk);self.assertEqual(ClinicalHistoryVersion.objects.count(),3)
    def test_history_retry_returns_original_version_without_duplicate(self):
        op=uuid.uuid4();a=self.history(operation_id=op);b=self.history(operation_id=op)
        self.assertEqual(a.pk,b.pk);self.assertEqual(ClinicalHistoryVersion.objects.count(),1)
    def test_two_history_forms_preserve_first_and_reject_stale_second(self):
        self.history()
        with self.assertRaises(RuleError):self.history(fields={'medical_status':'REPORTED','medical_history':'second unsaved draft'})
        self.assertEqual(ClinicalHistoryVersion.objects.count(),1)
    def test_structured_notes_never_manufacture_actual_treatment_or_cash(self):
        head=self.start();self.notes(head)
        self.step(head,'ADD_FINDING',{'tooth':16,'surface':'MO','kind':'OBSERVATION','detail':'PRIVATE_FINDING'})
        self.publish()
        self.assertEqual(ToothFinding.objects.count(),1)
        self.assertFalse(Invoice.objects.exists());self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def structured_referral(self):
        from clinical import referrals
        head=self.start();self.notes(head);self.publish();record=ClinicalRecordVersion.objects.get()
        self.receiver_scope()
        fields=dict(source_visit_id=self.v.pk,source_record_id=None,source_clinical_record_id=record.pk,
            destination_clinic_id=self.b.pk,destination_service_id=None,receiver_id=self.reviewer.pk,
            consent_basis='PATIENT',consent_reference='SYNTHETIC-C21-REFERRAL',purpose='PRIVATE_STRUCTURED_REFERRAL',valid_until=timezone.now()+timedelta(days=7))
        p=referrals.prepare_referral(actor=self.doc,action='CREATE',fields=fields)
        row,_=referrals.confirm_referral(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        return head,record,row
    def test_structured_referral_releases_only_selected_confirmed_version(self):
        from clinical import referrals
        head,record,row=self.structured_referral()
        with self.assertRaises(PermissionDenied):referrals.released_record(self.reviewer,row)
        row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.v.patient.patient_no)
        row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        released=referrals.released_record(self.reviewer,row)
        self.assertIsNone(released['record']);self.assertEqual(released['clinical_record']['examination'],'PRIVATE_EXAMINATION')
        self.assertNotIn('total_amount',released['clinical_record']);self.assertNotIn('billing_header',released['clinical_record'])
    def test_clinical_amendment_does_not_change_previously_selected_disclosure(self):
        from clinical import referrals
        head,record,row=self.structured_referral()
        row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.v.patient.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        self.ctx(self.doc,'DENTIST');self.step(head,'BEGIN_AMEND',{'reason':'补充新的检查观察，保留原始版本'})
        self.notes(head,examination='PRIVATE_NEW_CONFIRMED',amendment_reason='补充新的检查观察，保留原始版本');self.publish()
        self.assertEqual(referrals.released_record(self.reviewer,row)['clinical_record']['examination'],'PRIVATE_EXAMINATION')
        self.assertEqual(ClinicalRecordVersion.objects.count(),2)
    def test_revoking_structured_referral_stops_future_reads(self):
        from clinical import referrals
        head,record,row=self.structured_referral()
        row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.v.patient.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        row,_=self.ref_step(row,'REVOKE',actor=self.doc)
        with self.assertRaises(PermissionDenied):referrals.released_record(self.reviewer,row)
        self.assertEqual(ClinicalRecordVersion.objects.count(),1);self.assertFalse(Invoice.objects.exists())
    def test_unknown_survives_a_confirmed_encounter(self):
        before=self.v.patient.allergy_status
        head=self.start();self.notes(head,dentition='UNASSESSED');self.publish()
        self.v.patient.refresh_from_db();self.assertEqual(self.v.patient.allergy_status,before)
        self.assertEqual(ClinicalRecordVersion.objects.get().history_review,'UNAVAILABLE')
    def test_invalid_tooth_or_surface_preserves_saved_draft(self):
        head=self.start();self.notes(head)
        for tooth,surface in [(99,''),(11,'O'),(16,'I'),(16,'MM')]:
            with self.subTest(tooth=tooth,surface=surface):
                with self.assertRaises(RuleError):self.step(head,'ADD_FINDING',{'tooth':tooth,'surface':surface,'kind':'OBSERVATION','detail':'invalid'})
        self.assertEqual(ClinicalDraft.objects.get().payload['findings'],[])
    def test_primary_permanent_and_whole_tooth_missing_are_distinct(self):
        with self.assertRaises(RuleError):validate_finding(dict(tooth=51,surface='',kind='MISSING',detail='记录缺失'),'PERMANENT')
        with self.assertRaises(RuleError):validate_finding(dict(tooth=51,surface='M',kind='MISSING',detail='记录缺失'),'PRIMARY')
        self.assertEqual(validate_finding(dict(tooth=51,surface='',kind='MISSING',detail='记录缺失'),'PRIMARY')['tooth'],51)
    def test_duplicate_location_has_no_partial_effect(self):
        head=self.start();self.notes(head);data=dict(tooth=16,surface='MO',kind='OBSERVATION',detail='first')
        self.step(head,'ADD_FINDING',data)
        with self.assertRaises(RuleError):self.step(head,'ADD_FINDING',dict(data,detail='second'))
        self.assertEqual(len(ClinicalDraft.objects.get().payload['findings']),1)
    def test_old_draft_cannot_overwrite_acknowledged_work(self):
        head=self.start();old=head.revision;self.notes(head,chief_complaint='first saved')
        with self.assertRaises(RuleError):cmd.change_draft(actor=self.doc,visit_id=self.v.pk,expected_revision=old,operation_id=uuid.uuid4(),action='NOTES',fields={'chief_complaint':'second form'})
        self.assertEqual(ClinicalDraft.objects.get().payload['chief_complaint'],'first saved')
    def test_new_history_after_preview_preserves_work_and_requires_recheck(self):
        head=self.start();self.notes(head);p=cmd.prepare_record(actor=self.doc,visit_id=self.v.pk)
        report=self.history()
        with self.assertRaises(RuleError):cmd.confirm_record(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(ClinicalDraft.objects.exists());self.assertFalse(ClinicalRecordVersion.objects.exists())
        self.notes(head,history_id=report.pk,history_review='REVIEWED');self.publish()
        self.assertEqual(ClinicalRecordVersion.objects.get().history_id,report.pk)
    def test_existing_history_cannot_be_labeled_not_supplied(self):
        self.history();head=self.start();self.notes(head)
        with self.assertRaises(RuleError):cmd.prepare_record(actor=self.doc,visit_id=self.v.pk)
    def test_confirmation_retry_does_not_duplicate_version_or_finding(self):
        head=self.start();self.notes(head);self.step(head,'ADD_FINDING',dict(tooth=16,surface='O',kind='OBSERVATION',detail='retained'))
        p=cmd.prepare_record(actor=self.doc,visit_id=self.v.pk)
        for _ in range(2):cmd.confirm_record(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(ClinicalRecordVersion.objects.count(),1);self.assertEqual(ToothFinding.objects.count(),1)
    def test_amendment_retains_original_and_has_its_own_basis(self):
        head=self.start();self.notes(head);self.publish();first=ClinicalRecordVersion.objects.get()
        with self.assertRaises(RuleError):self.notes(head,chief_complaint='silent overwrite')
        self.step(head,'BEGIN_AMEND',{'reason':'患者补充信息，追加更正依据'})
        self.notes(head,chief_complaint='amended',amendment_reason='患者补充信息，追加更正依据')
        self.publish();first.refresh_from_db();second=ClinicalRecordVersion.objects.order_by('-revision').first()
        self.assertEqual(first.chief_complaint,'PRIVATE_CHIEF');self.assertEqual(second.previous_id,first.pk);self.assertEqual(second.chief_complaint,'amended')
    def test_database_retains_confirmed_facts_and_events(self):
        history=self.history();head=self.start();self.notes(head,history_id=history.pk,history_review='REVIEWED')
        self.step(head,'ADD_FINDING',dict(tooth=16,surface='O',kind='OBSERVATION',detail='retained'));self.publish()
        for model,field,value in [(ClinicalHistoryVersion,'medical_history','changed'),(ClinicalRecordVersion,'examination','changed'),(ToothFinding,'detail','changed'),(ClinicalRecordEvent,'note','changed')]:
            with self.subTest(model=model):
                with self.assertRaises(DatabaseError),transaction.atomic():model.objects.update(**{field:value})
    def test_observation_before_actual_attendance_is_not_confirmed(self):
        head=self.start();self.notes(head,observed_at=(self.v.attended_at-timedelta(minutes=1)).isoformat())
        with self.assertRaises(RuleError):self.publish()
        self.assertTrue(ClinicalDraft.objects.exists());self.assertFalse(ClinicalRecordVersion.objects.exists())
    def test_revoked_professional_scope_cannot_confirm_saved_preview(self):
        head=self.start();self.notes(head);p=cmd.prepare_record(actor=self.doc,visit_id=self.v.pk)
        self.decide(self.authority,'REVOKE');self.ctx(self.doc,'DENTIST')
        with self.assertRaises((PermissionDenied,RuleError)):cmd.confirm_record(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(ClinicalDraft.objects.exists());self.assertFalse(ClinicalRecordVersion.objects.exists())
    def test_settlement_waits_for_started_clinical_record_and_saved_draft(self):
        from care.services import complete_visit
        head=self.start();self.notes(head)
        with self.assertRaises(RuleError):complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='NO_TREATMENT',reason='咨询后无实际治疗')
        self.assertFalse(Invoice.objects.exists())
        self.publish()
        invoice=complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='NO_TREATMENT',reason='咨询后无实际治疗')
        self.assertEqual(invoice.current_record_version.total_amount,0)
        self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_new_patient_report_after_confirmation_requires_clinical_recheck_before_closure(self):
        from care.services import complete_visit
        head=self.start();self.notes(head);self.publish();self.history()
        with self.assertRaises(RuleError):complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='NO_TREATMENT',reason='咨询结束')
        self.assertFalse(Invoice.objects.exists());self.assertEqual(ClinicalRecordVersion.objects.count(),1)
    def test_read_only_professional_cannot_bypass_chart_through_old_care_route(self):
        from care.services import save_clinical_note
        head=self.start();self.decide(self.authority,'REVOKE');self.authorize(can_record=False,can_refer=False)
        with self.assertRaises(PermissionDenied):save_clinical_note(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,clinical_note='refused')
        self.assertFalse(self.v.record_versions.exists())
    def test_default_observation_time_keeps_precision_on_later_note_saves(self):
        head=self.start();self.notes(head,observed_at=None)
        initial=ClinicalDraft.objects.get().payload['observed_at'];self.notes(head,observed_at=None)
        self.assertEqual(ClinicalDraft.objects.get().payload['observed_at'],initial)
        self.publish()
    def test_historical_view_does_not_display_a_newer_working_draft(self):
        from clinical.encounter_selectors import encounter_details
        head=self.start();self.notes(head,chief_complaint='first confirmed');self.publish()
        self.step(head,'BEGIN_AMEND',{'reason':'患者补充信息，保留原始记录'})
        self.notes(head,chief_complaint='PRIVATE_NEW_DRAFT',amendment_reason='患者补充信息，保留原始记录')
        view=encounter_details(self.doc,self.v.pk,revision=1)
        self.assertEqual(view['payload']['chief_complaint'],'first confirmed');self.assertFalse(view['can_edit']);self.assertIsNone(view['draft'])
    def test_concurrent_confirmation_has_one_retained_effect(self):
        head=self.start();self.notes(head);p=cmd.prepare_record(actor=self.doc,visit_id=self.v.pk);barrier=Barrier(2);ctx_id=self.doc._adc_workspace.pk
        def run():
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.doc.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctx_id)
                barrier.wait();return cmd.confirm_record(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[1]
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sorted(results),[False,True]);self.assertEqual(ClinicalRecordVersion.objects.count(),1)
    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_instance_cannot_record_clinical_facts(self):
        with self.assertRaises(PermissionDenied):self.start()
        with self.assertRaises(PermissionDenied):self.history()
        self.assertFalse(ClinicalEncounter.objects.exists());self.assertFalse(ClinicalHistoryVersion.objects.exists())
