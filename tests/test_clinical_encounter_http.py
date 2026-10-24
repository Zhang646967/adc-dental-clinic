from datetime import timedelta
import uuid
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from care.models import Invoice,TreatmentRecord
from clinical import encounters as cmd
from clinical.models import ClinicalEncounter,ClinicalDraft,ClinicalRecordVersion,ClinicalHistoryVersion,SensitiveReadEvent
from finance.cash_models import CashEntry
from portal.models import PatientAccess,PatientRelationship,PatientAppointmentGrant
from tests.test_clinical_authority import AuthorityFixture
from tests.workspace_client import WorkspaceClient


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ClinicalEncounterHTTPTests(AuthorityFixture,TransactionTestCase):
    def setUp(self):
        self.setup_authority();self.authorize();self.v=self.checked_visit()
        self.patient_user=UserAccount.objects.create_user(username='clinical_web_patient',password='synthetic-only-123')
        PatientAccess.objects.create(user=self.patient_user,patient=self.v.patient)
    def client_for(self,user):
        c=WorkspaceClient();c.force_login(user);return c
    def values(self,form):
        return {field.name:field.value() if field.value() is not None else '' for field in form}
    def begin(self,c):
        page=c.get(reverse('clinical_encounter',args=[self.v.pk]));self.assertEqual(page.status_code,200)
        data=self.values(page.context['start_form']);data.update(action='START',confirmed='on')
        response=c.post(reverse('clinical_encounter',args=[self.v.pk]),data);self.assertEqual(response.status_code,302,response.content)
    def note_data(self,c,text='PRIVATE_WEB_EXAM'):
        r=c.get(reverse('clinical_encounter',args=[self.v.pk]));data=self.values(r.context['notes_form'])
        data.update(action='NOTES',chief_complaint='PRIVATE_WEB_CHIEF',examination=text,history_assessment='尚未取得患者自述，相关情况仍未知。',history_review='UNAVAILABLE',history='',dentition='PERMANENT',observed_at='')
        return data
    def own_fields(self,**extra):
        fields=dict(medical_status='UNKNOWN',medical_history='',medication_status='UNKNOWN',medications='',allergy_status='UNKNOWN',reported_allergies='');fields.update(extra);return fields

    def test_seven_roles_do_not_share_the_clinical_worklist(self):
        finance=UserAccount.objects.create_user(username='clinical_finance');RoleAssignment.objects.create(user=finance,role='FINANCE',scope_kind='CHAIN')
        hq=UserAccount.objects.create_user(username='clinical_hq');RoleAssignment.objects.create(user=hq,role='HQ',scope_kind='CHAIN')
        for actor,allowed in [(self.doc,True),(self.front,False),(self.manager,False),(self.tech,False),(self.patient_user,False),(finance,False),(hq,False)]:
            with self.subTest(actor=actor.username):
                c=self.client_for(actor);r=c.get(reverse('clinical_worklist'));self.assertEqual(r.status_code,200 if allowed else 403)
                if not allowed:self.assertNotContains(r,self.v.patient.patient_no,status_code=403)
    def test_doctor_http_notes_finding_and_server_held_confirmation(self):
        c=self.client_for(self.doc);self.begin(c)
        self.assertEqual(c.post(reverse('clinical_encounter',args=[self.v.pk]),self.note_data(c)).status_code,302)
        r=c.get(reverse('clinical_encounter',args=[self.v.pk]));data=self.values(r.context['finding_form'])
        data.update(action='ADD_FINDING',tooth=16,surfaces=['M','O'],kind='OBSERVATION',detail='PRIVATE_WEB_FINDING')
        self.assertEqual(c.post(reverse('clinical_encounter',args=[self.v.pk]),data).status_code,302)
        r=c.get(reverse('clinical_record_preview',args=[self.v.pk]));self.assertEqual(r.status_code,200,r.content)
        self.assertContains(r,'PRIVATE_WEB_FINDING');self.assertFalse(ClinicalRecordVersion.objects.exists())
        data=self.values(r.context['form']);data['confirmed']='on'
        self.assertEqual(c.post(reverse('clinical_record_confirm'),data).status_code,302)
        self.assertEqual(ClinicalRecordVersion.objects.count(),1);self.assertFalse(ClinicalDraft.objects.exists())
        self.assertFalse(Invoice.objects.exists());self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(CashEntry.objects.exists())
        self.assertFalse(SensitiveReadEvent.objects.filter(actor=self.doc,object_kind='CARE',outcome='DENY').exists())
        complete=c.get(reverse('care_complete',args=[self.v.pk]))
        self.assertContains(complete,'已确认第 1 版')
        self.assertNotContains(complete,'尚无接诊备注')
    def test_old_patient_form_cannot_start_another_patient_encounter(self):
        c=self.client_for(self.doc);r=c.get(reverse('clinical_encounter',args=[self.v.pk]));data=self.values(r.context['start_form'])
        other=self.booking(patient=self.p2,start=self.t+timedelta(hours=1));data.update(action='START',confirmed='on')
        response=c.post(reverse('clinical_encounter',args=[other.pk]),data)
        self.assertEqual(response.status_code,403);self.assertFalse(ClinicalEncounter.objects.exists())
    def test_stale_form_preserves_entered_work_without_overwriting_saved_work(self):
        c=self.client_for(self.doc);self.begin(c);first=self.note_data(c,'first saved');second=self.note_data(c,'PRIVATE_UNSAVED_SECOND')
        self.assertEqual(c.post(reverse('clinical_encounter',args=[self.v.pk]),first).status_code,302)
        r=c.post(reverse('clinical_encounter',args=[self.v.pk]),second)
        self.assertEqual(r.status_code,409);self.assertContains(r,'PRIVATE_UNSAVED_SECOND',status_code=409)
        self.assertEqual(ClinicalDraft.objects.get().payload['examination'],'first saved')
        self.assertEqual(SensitiveReadEvent.objects.filter(actor=self.doc,object_kind='CARE').latest('pk').outcome,'ALLOW')
    def test_changed_payload_cannot_be_misreported_as_a_successful_old_retry(self):
        c=self.client_for(self.doc);self.begin(c);first=self.note_data(c,'first saved')
        self.assertEqual(c.post(reverse('clinical_encounter',args=[self.v.pk]),first).status_code,302)
        changed=dict(first,examination='PRIVATE_CHANGED_RETRY')
        r=c.post(reverse('clinical_encounter',args=[self.v.pk]),changed)
        self.assertEqual(r.status_code,409);self.assertContains(r,'PRIVATE_CHANGED_RETRY',status_code=409)
        self.assertEqual(ClinicalDraft.objects.get().payload['examination'],'first saved')
    def test_conflict_can_compare_and_resume_without_losing_entered_notes(self):
        c=self.client_for(self.doc);self.begin(c)
        first=self.note_data(c,'CURRENT_SAVED');second=self.note_data(c,'UNSAVED_CONTINUATION')
        c.post(reverse('clinical_encounter',args=[self.v.pk]),first)
        response=c.post(reverse('clinical_encounter',args=[self.v.pk]),second)
        self.assertContains(response,'核对最新草稿并保留本页填写',status_code=409)
        self.assertContains(response,'CURRENT_SAVED',status_code=409)
        response=c.post(reverse('clinical_encounter',args=[self.v.pk]),dict(second,review_current='yes'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(ClinicalDraft.objects.get().payload['examination'],'CURRENT_SAVED')
        continued=self.values(response.context['notes_form']);continued['action']='NOTES'
        self.assertEqual(continued['examination'],'UNSAVED_CONTINUATION')
        self.assertNotEqual(continued['operation_id'],second['operation_id'])
        self.assertEqual(c.post(reverse('clinical_encounter',args=[self.v.pk]),continued).status_code,302)
        self.assertEqual(ClinicalDraft.objects.get().payload['examination'],'UNSAVED_CONTINUATION')
    def test_self_history_conflict_can_resume_after_reviewing_latest_version(self):
        c=self.client_for(self.patient_user)
        a=self.values(c.get(reverse('portal_history')).context['form'])
        b=self.values(c.get(reverse('portal_history')).context['form'])
        a.update(self.own_fields(medical_status='REPORTED',medical_history='CURRENT_HISTORY'),confirmed='on')
        b.update(self.own_fields(medical_status='REPORTED',medical_history='UNSAVED_HISTORY'),confirmed='on')
        self.assertEqual(c.post(reverse('portal_history'),a).status_code,302)
        self.assertContains(c.post(reverse('portal_history'),b),'核对最新自述并保留本页填写',status_code=409)
        response=c.post(reverse('portal_history'),dict(b,review_current='yes'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(ClinicalHistoryVersion.objects.count(),1)
        data=self.values(response.context['form']);data['confirmed']='on'
        self.assertEqual(data['medical_history'],'UNSAVED_HISTORY')
        self.assertEqual(c.post(reverse('portal_history'),data).status_code,302)
        self.assertEqual(ClinicalHistoryVersion.objects.count(),2)
    def test_other_doctor_cannot_probe_assigned_patient_chart(self):
        c=self.client_for(self.reviewer)
        self.assertEqual(c.get(reverse('clinical_encounter',args=[self.v.pk])).status_code,404)
        self.assertEqual(c.get(reverse('clinical_encounter',args=[99999999])).status_code,404)
    def test_invalid_confirmation_never_claims_an_authorized_chart_read(self):
        c=self.client_for(self.doc)
        response=c.post(reverse('clinical_record_confirm'),{'proposal_token':'invalid','confirmed':'on'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(SensitiveReadEvent.objects.filter(actor=self.doc,object_kind='CARE').latest('pk').outcome,'DENY')
        self.assertNotContains(response,self.v.patient.patient_no,status_code=409)
    def test_patient_history_login_uses_the_patient_channel(self):
        response=WorkspaceClient().get(reverse('portal_history'))
        self.assertEqual(response.status_code,302)
        self.assertTrue(response.url.startswith(reverse('portal_login')))
    def test_self_report_from_web_is_same_fact_in_native_and_retry(self):
        c=self.client_for(self.patient_user);r=c.get(reverse('portal_history'));self.assertEqual(r.status_code,200)
        data=self.values(r.context['form']);data.update(self.own_fields(medical_status='REPORTED',medical_history='PRIVATE_SELF_WEB'),confirmed='on')
        self.assertEqual(c.post(reverse('portal_history'),data).status_code,302)
        native=c.get(reverse('mini_history'));self.assertEqual(native.status_code,200)
        d=native.json()['data'];self.assertEqual(d['rows'][0]['medical_history'],'PRIVATE_SELF_WEB')
        data=dict(self.own_fields(allergy_status='REPORTED',reported_allergies='PRIVATE_SELF_NATIVE'),expected_revision=d['current_revision'],operation_id=d['operation_id'],confirmed='on')
        for _ in range(2):
            r=c.post(reverse('mini_history_submit'),data,HTTP_X_ADC_WORKSPACE=c.current_token());self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(ClinicalHistoryVersion.objects.filter(source='SELF').count(),2)
        r=c.get(reverse('portal_history'));self.assertContains(r,'PRIVATE_SELF_NATIVE')
    def test_patient_report_projection_does_not_release_clinician_interview_text(self):
        cmd.submit_history(actor=self.doc,fields=self.own_fields(medical_status='REPORTED',medical_history='PRIVATE_CLINIC_INTERVIEW'),expected_revision=0,operation_id=uuid.uuid4(),confirmed=True,visit_id=self.v.pk)
        c=self.client_for(self.patient_user)
        self.assertNotContains(c.get(reverse('portal_history')),'PRIVATE_CLINIC_INTERVIEW')
        self.assertEqual(c.get(reverse('mini_history')).json()['data']['rows'],[])
    def test_appointment_delegate_cannot_report_clinical_history(self):
        case=PatientRelationship.objects.create(clinic=self.a,patient=self.p2,delegate_user=self.patient_user,related_name='合成预约委托',kind='DELEGATE',state='VERIFIED',created_by=self.front)
        grant=PatientAppointmentGrant.objects.create(relationship=case,valid_from=timezone.now()-timedelta(days=1),valid_until=timezone.now()+timedelta(days=1),created_by=self.front)
        c=self.client_for(self.patient_user)
        selected=c.post(reverse('portal_subjects'),{'subject':'grant:'+str(grant.pk)});self.assertEqual(selected.status_code,302)
        self.assertEqual(c.get(reverse('portal_history')).status_code,403)
        self.assertEqual(c.get(reverse('mini_history')).status_code,403)
        data=dict(self.own_fields(),expected_revision=0,operation_id=str(uuid.uuid4()),confirmed='on')
        self.assertEqual(c.post(reverse('mini_history_submit'),data,HTTP_X_ADC_WORKSPACE=c.current_token()).status_code,403)
        self.assertFalse(ClinicalHistoryVersion.objects.exists())
