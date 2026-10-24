"""C1.2 executed PostgreSQL decisions, effective scopes and bounded disclosure."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import transaction,connection,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts.governance import change_account,target_token
from adc_core.rules import RuleError
from care.models import Invoice,VisitRecordVersion
from care.services import save_clinical_note,complete_visit
from clinical.models import *
from clinical import authority_services as auth,referrals
from clinical.authority import professional_scope,require_visit_authority
from scheduling.models import Visit
from scheduling.resource_models import ResourceClaim
from tests.test_reception_resources import ResourceFixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext


class AuthorityFixture(ResourceFixture):
    def setup_authority(self):
        self.resources()
        self.doc=UserAccount.objects.create_user(username='clinical_d1',dentist=self.d1,password='synthetic-pass-123')
        self.reviewer=UserAccount.objects.create_user(username='clinical_d2',dentist=self.d2,password='synthetic-pass-123')
        for u in (self.doc,self.reviewer):
            RoleAssignment.objects.create(user=u,role='DENTIST',scope_kind='SELF_DENTIST')
            self.ctx(u,'DENTIST')
        self.ctx(self.tech,'SYSADMIN')
        for clinic in (self.a,self.b):self.appoint(self.reviewer,clinic)
        self.ctx(self.reviewer,'DENTIST')
    def ctx(self,u,role,clinic=None):
        u._adc_workspace=WorkspaceContext.objects.create(user=u,role=role,clinic=clinic)
        return u
    def appoint(self,u,clinic,enabled=True):
        change_account(actor=self.tech,target_id=u.pk,token=target_token(self.tech,u),action='clinical_reviewer',
            operator_password='test-only-pass-abc',reason='机构明确委任的合成审核职责',clinic_id=clinic.pk,reviewer_enabled=enabled,
            reviewer_reference='SYNTHETIC-APPOINTMENT',reviewer_from=timezone.now()-timedelta(days=1),reviewer_until=timezone.now()+timedelta(days=180))
    def fields(self,user=None,clinic=None,service='default',**kw):
        now=timezone.now()
        data=dict(user_id=(user or self.doc).pk,service_id=self.service.pk if service=='default' else service,
            source_kind='SYNTHETIC',source_reference='SYNTHETIC-CREDENTIAL',issuer='合成来源机构，仅用于自动化验证',
            credential_from=now-timedelta(days=3),credential_until=now+timedelta(days=180),
            valid_from=now-timedelta(days=1),valid_until=now+timedelta(days=90),can_read=True,can_record=True,can_refer=True)
        data.update(kw);return data
    def authorize(self,user=None,service='default',**kw):
        fields=self.fields(user,service=service,**kw)
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=fields)
        row,_=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.decide(row,'APPROVE')
        user=user or self.doc;self.ctx(user,'DENTIST');row.refresh_from_db();return row
    def decide(self,row,action,actor=None,token=None):
        actor=actor or self.reviewer
        p=auth.prepare_authority(actor=actor,action=action,case_id=row.pk,fields={'note':'已按机构原始依据核对范围与期限'}) if token is None else {'proposal_token':token}
        return auth.confirm_authority(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
    def activate(self,clinic=None):
        p=auth.prepare_authority(actor=self.reviewer,action='ACTIVATE',fields={'clinic_id':(clinic or self.a).pk,'note':'合成诊所资源与专业范围逐项核对'})
        return auth.confirm_authority(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)[0]
    def checked_visit(self):
        row=self.booking()
        Visit.objects.filter(pk=row.pk).update(status='CHECKED_IN',attended=True,attended_at=timezone.now()-timedelta(minutes=2))
        row.refresh_from_db();return row
    def source(self):
        self.authorize();self.activate();row=self.checked_visit()
        save_clinical_note(actor=self.doc,visit_id=row.pk,expected_version=0,clinical_note='PRIVATE_SOURCE_CLINICAL_NOTE')
        row.refresh_from_db()
        invoice=complete_visit(actor=self.doc,visit_id=row.pk,expected_version=row.lock_version,outcome='NO_TREATMENT',reason='合成咨询后转诊')
        return row,invoice.current_record_version
    def receiver_scope(self):
        # A different named clinician receives a legacy-scoped request at B.
        p=self.fields(user=self.reviewer,service=None)
        self.ctx(self.manager,'MANAGER',self.b)
        RoleAssignment.objects.get_or_create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        token=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=p)['proposal_token']
        row,_=auth.confirm_authority(actor=self.manager,proposal_token=token,confirmed=True)
        self.appoint(self.doc,self.b);self.ctx(self.doc,'DENTIST')
        self.decide(row,'APPROVE',actor=self.doc)
        self.ctx(self.reviewer,'DENTIST');self.ctx(self.manager,'MANAGER',self.a)
        return row
    def new_referral(self):
        visit,record=self.source();self.receiver_scope()
        fields=dict(source_visit_id=visit.pk,source_record_id=record.pk,destination_clinic_id=self.b.pk,
            destination_service_id=None,receiver_id=self.reviewer.pk,consent_basis='PATIENT',
            consent_reference='SYNTHETIC-CLINICAL-CONSENT',purpose='PRIVATE_SOURCE_REFERRAL_PURPOSE',valid_until=timezone.now()+timedelta(days=7))
        p=referrals.prepare_referral(actor=self.doc,action='CREATE',fields=fields)
        return referrals.confirm_referral(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0],fields
    def ref_step(self,row,action,actor=None,**fields):
        actor=actor or self.front
        if actor.pk==self.front.pk:
            self.ctx(self.front,'FRONT_DESK',self.b)
            RoleAssignment.objects.filter(user=self.front,clinic=self.b).update(can_verify_patient_relationships=True)
        p=referrals.prepare_referral(actor=actor,action=action,referral_id=row.pk,fields={'note':'合成核对依据与办理结果',**fields})
        return referrals.confirm_referral(actor=actor,proposal_token=p['proposal_token'],confirmed=True)


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ClinicalAuthorityTests(AuthorityFixture,TransactionTestCase):
    def setUp(self):self.setup_authority()
    def test_manager_prepares_but_independent_professional_approves(self):
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
        row,_=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(PermissionDenied):professional_scope(self.doc.pk,self.a.pk,self.service.pk,'RECORD')
        self.decide(row,'APPROVE');self.assertEqual(row.events.count(),2)
        self.assertEqual(professional_scope(self.doc.pk,self.a.pk,self.service.pk,'RECORD').pk,row.pk)
    def test_directory_or_role_alone_is_not_professional_authority(self):
        with self.assertRaises(PermissionDenied):professional_scope(self.doc.pk,self.a.pk,self.service.pk,'READ')
    def test_self_review_is_denied_after_role_switch(self):
        self.appoint(self.doc,self.a);self.ctx(self.doc,'DENTIST')
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
        row,_=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(PermissionDenied):self.decide(row,'APPROVE',actor=self.doc)
    def test_preparer_cannot_switch_into_reviewer(self):
        self.manager.dentist=self.d2;self.reviewer.dentist=None;self.reviewer.save(update_fields=['dentist']);self.manager.save(update_fields=['dentist'])
        RoleAssignment.objects.create(user=self.manager,role='DENTIST',scope_kind='SELF_DENTIST')
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
        row,_=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.appoint(self.manager,self.a);self.ctx(self.manager,'DENTIST')
        with self.assertRaises(PermissionDenied):self.decide(row,'APPROVE',actor=self.manager)
    def test_source_expiry_bounds_action_scope(self):
        with self.assertRaises(RuleError):auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields(credential_until=timezone.now()+timedelta(hours=1)))
    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_synthetic_evidence_refused_outside_explicit_synthetic_environment(self):
        with self.assertRaises(RuleError):auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
    def test_non_synthetic_clinic_requires_scope_before_any_legacy_activation(self):
        v=self.checked_visit()
        with override_settings(ADC_CLINICAL_SYNTHETIC=False):
            with self.assertRaises(PermissionDenied):require_visit_authority(self.doc,v,'READ')
            with self.assertRaises(PermissionDenied):save_clinical_note(actor=self.doc,visit_id=v.pk,expected_version=0,clinical_note='no implicit scope')
            from patients.selectors import visible_patients
            self.assertFalse(visible_patients(self.doc).exists())
    def test_approved_synthetic_source_cannot_be_promoted_into_real_authority(self):
        self.authorize();v=self.checked_visit()
        with override_settings(ADC_CLINICAL_SYNTHETIC=False):
            with self.assertRaises(PermissionDenied):require_visit_authority(self.doc,v,'READ')
            with self.assertRaises(PermissionDenied):professional_scope(self.doc.pk,self.a.pk,self.service.pk,'RECORD')
    def test_wrong_clinic_service_refused(self):
        from scheduling.resource_models import Department,BookingService
        dep=Department.objects.create(clinic=self.b,code='B',name='乙科')
        service=BookingService.objects.create(department=dep,code='B',name='乙服务',duration_minutes=30)
        service.dentists.add(self.d1)
        with self.assertRaises(RuleError):auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields(service=service.pk))
    def test_no_service_scope_is_exact_not_wildcard(self):
        self.authorize(service=None)
        with self.assertRaises(PermissionDenied):professional_scope(self.doc.pk,self.a.pk,self.service.pk,'RECORD')
        self.assertTrue(professional_scope(self.doc.pk,self.a.pk,None,'READ'))
    def test_read_only_scope_does_not_allow_record_or_refer(self):
        self.authorize(can_record=False,can_refer=False)
        for action in ['RECORD','REFER']:
            with self.assertRaises(PermissionDenied):professional_scope(self.doc.pk,self.a.pk,self.service.pk,action)
    def test_reviewer_duty_revoked_after_preview(self):
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
        row,_=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        token=auth.prepare_authority(actor=self.reviewer,action='APPROVE',case_id=row.pk,fields={'note':'已核对合成原始资质'})['proposal_token']
        self.appoint(self.reviewer,self.a,enabled=False)
        self.ctx(self.reviewer,'DENTIST')
        with self.assertRaises((PermissionDenied,RuleError)):self.decide(row,'APPROVE',token=token)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING')
    def test_subject_role_revoked_after_preview(self):
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
        RoleAssignment.objects.filter(user=self.doc).update(is_active=False)
        with self.assertRaises(RuleError):auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(ProfessionalAuthorization.objects.exists())
    def test_duplicate_creation_confirmation_one_case(self):
        p=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())
        a,_=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        b,replay=auth.confirm_authority(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(a.pk,b.pk);self.assertEqual(ProfessionalAuthorization.objects.count(),1)
    def test_stale_decision_does_not_overwrite(self):
        row=self.authorize()
        token=auth.prepare_authority(actor=self.reviewer,action='SUSPEND',case_id=row.pk,fields={'note':'合成暂停依据已核对'})['proposal_token']
        self.decide(row,'REVOKE')
        with self.assertRaises(RuleError):self.decide(row,'SUSPEND',token=token)
    def test_activation_requires_coverage_of_existing_future_visits(self):
        self.booking()
        with self.assertRaises(RuleError):self.activate()
        self.authorize();self.activate();self.assertTrue(ClinicalAuthorityPolicy.objects.filter(clinic=self.a).exists())
    def test_expiry_rechecks_at_operation_without_changing_booking(self):
        row=self.authorize();self.activate();v=self.checked_visit()
        with patch('clinical.authority.timezone.now',return_value=row.valid_until+timedelta(seconds=1)):
            with self.assertRaises(PermissionDenied):save_clinical_note(actor=self.doc,visit_id=v.pk,expected_version=0,clinical_note='must not save')
        v.refresh_from_db();self.assertEqual(v.status,'CHECKED_IN');self.assertEqual(v.lock_version,0)
        self.assertFalse(VisitRecordVersion.objects.exists());self.assertTrue(ResourceClaim.objects.filter(plan__visit=v,active=True).exists())
    def test_suspend_stops_existing_clinical_commands(self):
        row=self.authorize();self.activate();v=self.checked_visit();self.decide(row,'SUSPEND');self.ctx(self.doc,'DENTIST')
        with self.assertRaises(PermissionDenied):save_clinical_note(actor=self.doc,visit_id=v.pk,expected_version=0,clinical_note='must not save')
        self.assertFalse(VisitRecordVersion.objects.exists())
    def test_sql_history_source_and_activation_are_retained(self):
        row=self.authorize();self.activate()
        statements=[('UPDATE adc_professional_authorization SET source_reference=%s WHERE id=%s',['rewrite',row.pk]),
            ('DELETE FROM adc_professional_authorization WHERE id=%s',[row.pk]),
            ('DELETE FROM adc_clinical_authority_event',[]),('DELETE FROM adc_clinical_authority_policy',[])]
        for sql,args in statements:
            with self.assertRaises(DatabaseError),transaction.atomic():
                with connection.cursor() as cur:cur.execute(sql,args)
    def test_security_departure_drops_session_but_keeps_authorship_and_care(self):
        self.authorize();self.activate();v=self.checked_visit()
        save_clinical_note(actor=self.doc,visit_id=v.pk,expected_version=0,clinical_note='retained author')
        change_account(actor=self.tech,target_id=self.doc.pk,token=target_token(self.tech,self.doc),action='security_suspend',
            operator_password='test-only-pass-abc',reason='离岗立即停用临床访问')
        with self.assertRaises(PermissionDenied):require_visit_authority(self.doc,v,'READ')
        self.assertEqual(VisitRecordVersion.objects.get().prepared_by_id,self.doc.pk)
        self.assertEqual(Visit.objects.get(pk=v.pk).status,'CHECKED_IN')
    def test_http_audits_allowed_and_denied_reads_without_medical_text(self):
        row=self.authorize();self.activate();v=self.checked_visit()
        save_clinical_note(actor=self.doc,visit_id=v.pk,expected_version=0,clinical_note='SECRET_123_NO_RUNTIME_OR_READ_LOG')
        c=WorkspaceClient();c.force_login(self.doc)
        self.assertEqual(c.get(reverse('care_workspace',args=[v.pk])).status_code,200)
        self.decide(row,'SUSPEND');c.force_login(self.doc)
        self.assertEqual(c.get(reverse('care_workspace',args=[v.pk])).status_code,403)
        events=SensitiveReadEvent.objects.filter(object_kind='CARE',object_id=v.pk)
        self.assertEqual(set(events.values_list('outcome',flat=True)),{'ALLOW','DENY'})
        self.assertNotIn('SECRET_123',str(list(events.values())))
    def test_technical_and_finance_do_not_get_clinical_access(self):
        self.authorize();self.activate();v=self.checked_visit()
        c=WorkspaceClient();c.force_login(self.tech)
        self.assertEqual(c.get(reverse('care_workspace',args=[v.pk])).status_code,403)
        event=SensitiveReadEvent.objects.get(actor=self.tech,object_kind='CARE',object_id=v.pk)
        self.assertEqual((event.outcome,event.role),('DENY','SYSADMIN'))
        self.assertFalse(Invoice.objects.exists())
    def test_reviewer_appointment_alone_does_not_grant_chart_access(self):
        self.authorize();self.activate();v=self.checked_visit()
        with self.assertRaises(PermissionDenied):require_visit_authority(self.reviewer,v,'READ')
    def test_independent_confirmation_is_atomic_under_duplicate_requests(self):
        token=auth.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields())['proposal_token']
        barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.manager.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=self.manager._adc_workspace.pk)
                barrier.wait(timeout=10)
                row,replay=auth.confirm_authority(actor=actor,proposal_token=token,confirmed=True)
                return row.pk,replay
            finally:close_old_connections()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(len({pk for pk,_ in results}),1);self.assertEqual(sorted(r for _,r in results),[False,True])
        self.assertEqual(ProfessionalAuthorization.objects.count(),1)
    def test_suspension_and_care_write_serialize_without_partial_effects(self):
        row=self.authorize();self.activate();v=self.checked_visit()
        token=auth.prepare_authority(actor=self.reviewer,action='SUSPEND',case_id=row.pk,fields={'note':'合成并发暂停核验'})['proposal_token']
        barrier=Barrier(2)
        def run(kind):
            close_old_connections()
            try:
                source=self.doc if kind=='write' else self.reviewer
                actor=UserAccount.objects.get(pk=source.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=source._adc_workspace.pk)
                barrier.wait(timeout=10)
                try:
                    if kind=='write':save_clinical_note(actor=actor,visit_id=v.pk,expected_version=0,clinical_note='only-if-authorized')
                    else:auth.confirm_authority(actor=actor,proposal_token=token,confirmed=True)
                    return 'written' if kind=='write' else 'suspended'
                except PermissionDenied:
                    if kind!='write':raise
                    return 'denied'
            finally:close_old_connections()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(run,['write','suspend']))
        self.assertEqual(results[1],'suspended');v.refresh_from_db();row.refresh_from_db()
        self.assertEqual(row.state,'SUSPENDED');self.assertEqual(v.lock_version,1 if results[0]=='written' else 0)
        self.assertEqual(VisitRecordVersion.objects.count(),1 if results[0]=='written' else 0)
    def test_managed_patient_profile_rejects_expired_scope(self):
        row=self.authorize();self.activate();self.checked_visit();self.decide(row,'SUSPEND')
        c=WorkspaceClient();c.force_login(self.doc)
        self.assertIn(c.get(reverse('patient_detail',args=[self.p1.pk])).status_code,[403,404])
        r=c.get(reverse('patients'));self.assertEqual(r.status_code,200)
        self.assertNotContains(r,self.p1.patient_no)
    def test_patient_list_requires_exact_current_or_legacy_service_scope(self):
        from patients.selectors import visible_patients
        self.authorize(service=None)
        self.authorize()
        self.activate();self.booking()
        legacy=Visit.objects.create(patient=self.p2,dentist=self.d1,clinic=self.a,availability_slot=self.slot1,
            scheduled_start=self.t+timedelta(hours=2),scheduled_end=self.t+timedelta(hours=2,minutes=30))
        self.assertEqual(set(visible_patients(self.doc).values_list('pk',flat=True)),{self.p1.pk,self.p2.pk})
        grant=ProfessionalAuthorization.objects.get(user=self.doc,service=self.service)
        self.decide(grant,'SUSPEND');self.ctx(self.doc,'DENTIST')
        self.assertEqual(set(visible_patients(self.doc).values_list('pk',flat=True)),{self.p2.pk})
    def test_professional_form_uses_active_current_clinic_and_two_step_confirmation(self):
        c=WorkspaceClient();c.force_login(self.manager)
        r=c.get(reverse('clinical_authority_new'));self.assertEqual(r.status_code,200)
        d=self.fields();d['user']=d.pop('user_id');d['service']=d.pop('service_id')
        d={k:v.isoformat() if hasattr(v,'isoformat') else v for k,v in d.items()}
        r=c.post(reverse('clinical_authority_new'),d);self.assertEqual(r.status_code,200)
        self.assertFalse(ProfessionalAuthorization.objects.exists())
        token=r.context['form'].initial['proposal_token']
        r=c.post(reverse('clinical_authority_confirm'),{'proposal_token':token,'confirmed':'on'})
        self.assertEqual(r.status_code,302);self.assertEqual(ProfessionalAuthorization.objects.get().state,'PENDING')


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ClinicalReferralTests(AuthorityFixture,TransactionTestCase):
    def setUp(self):self.setup_authority()
    def test_identity_then_named_receiver_opens_only_selected_version(self):
        row,_=self.new_referral()
        with self.assertRaises(PermissionDenied):referrals.released_record(self.reviewer,row)
        row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no)
        row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        record=referrals.released_record(self.reviewer,row)
        self.assertIn('PRIVATE_SOURCE_CLINICAL_NOTE',record['record']['clinical_note'])
        self.assertNotIn('total_amount',record['record']);self.assertNotIn('billing_header_snapshot',record['record'])
        self.assertEqual(Visit.objects.count(),1);self.assertEqual(Invoice.objects.count(),1)
    def test_different_identifier_records_dispute_never_merges(self):
        row,_=self.new_referral()
        with self.assertRaises(RuleError):self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p2.patient_no)
        row,_=self.ref_step(row,'IDENTITY_DISPUTE')
        self.assertEqual(row.state,'IDENTITY_DISPUTED');self.assertEqual(row.patient_id,self.p1.pk)
        with self.assertRaises(RuleError):self.ref_step(row,'ACCEPT',actor=self.reviewer)
    def test_frontdesk_and_manager_cannot_read_released_clinical_text(self):
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        for actor in [self.front,self.manager,self.tech]:
            c=WorkspaceClient();c.force_login(actor)
            r=c.get(reverse('clinical_referral_record',args=[row.pk]));self.assertIn(r.status_code,[403,404])
            self.assertNotIn('PRIVATE_SOURCE',r.content.decode())
    def test_frontdesk_sees_identity_without_clinical_purpose(self):
        row,_=self.new_referral();self.ctx(self.front,'FRONT_DESK',self.b)
        c=WorkspaceClient();c.force_login(self.front)
        c.post(reverse('activate_clinic'),{'clinic':self.b.pk})
        r=c.get(reverse('clinical_referral_detail',args=[row.pk]));self.assertEqual(r.status_code,200)
        self.assertContains(r,self.p1.patient_no);self.assertNotContains(r,'PRIVATE_SOURCE')
    def test_unassigned_doctor_cannot_open_referral_or_chain_search(self):
        row,_=self.new_referral()
        from registry.models import Dentist
        third_dentist=Dentist.objects.create(employee_no='D3',name='第三医师',date_of_birth=self.d1.date_of_birth,
            home_address='合成地址',phone='000',email='third@example.invalid')
        third=UserAccount.objects.create_user(username='third',password='synthetic-pass-123',dentist=third_dentist)
        RoleAssignment.objects.create(user=third,role='DENTIST',scope_kind='SELF_DENTIST')
        self.ctx(third,'DENTIST')
        self.assertFalse(referrals.visible_referrals(third).exists())
    def test_source_manager_can_revoke_without_acquiring_chart(self):
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        row,_=self.ref_step(row,'REVOKE',actor=self.manager)
        with self.assertRaises(PermissionDenied):referrals.released_record(self.reviewer,row)
        self.assertEqual(row.state,'REVOKED');self.assertEqual(row.events.count(),4)
    def test_same_account_cannot_receive_its_own_referral(self):
        row,fields=self.new_referral();fields['receiver_id']=self.doc.pk
        with self.assertRaises(RuleError):referrals.prepare_referral(actor=self.doc,action='CREATE',fields=fields)
    def test_receiver_scope_expiry_closes_read_and_keeps_history(self):
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        with patch('clinical.referrals.timezone.now',return_value=row.valid_until+timedelta(seconds=1)):
            with self.assertRaises(PermissionDenied):referrals.released_record(self.reviewer,row)
        self.assertEqual(row.state,'ACCEPTED');self.assertEqual(Visit.objects.count(),1)
    def test_old_acceptance_preview_cannot_revive_withdrawal(self):
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no)
        p=referrals.prepare_referral(actor=self.reviewer,action='ACCEPT',referral_id=row.pk,fields={'note':'合成接收范围核对'})
        self.ref_step(row,'WITHDRAW',actor=self.doc)
        with self.assertRaises(RuleError):referrals.confirm_referral(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
    def test_importing_referral_never_grants_general_patient_selector(self):
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        from patients.selectors import visible_patients
        self.assertFalse(visible_patients(self.reviewer).filter(pk=self.p1.pk).exists())
    def test_patient_self_can_revoke_while_appointment_delegate_cannot_read(self):
        from portal.models import PatientAccess
        patient_user=UserAccount.objects.create_user(username='patient_self',password='synthetic-pass-123')
        PatientAccess.objects.create(user=patient_user,patient=self.p1)
        self.ctx(patient_user,'PATIENT')
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        row,_=self.ref_step(row,'REVOKE',actor=patient_user)
        with self.assertRaises(PermissionDenied):referrals.released_record(self.reviewer,row)
        c=WorkspaceClient();c.force_login(patient_user)
        self.assertEqual(c.get(reverse('clinical_referral_detail',args=[row.pk])).status_code,200)
    def test_frontdesk_duty_revocation_after_preview_prevents_identity_confirmation(self):
        row,_=self.new_referral()
        self.ctx(self.front,'FRONT_DESK',self.b)
        RoleAssignment.objects.filter(user=self.front,clinic=self.b).update(can_verify_patient_relationships=True)
        p=referrals.prepare_referral(actor=self.front,action='IDENTITY_CONFIRM',referral_id=row.pk,
            fields={'patient_no':self.p1.patient_no,'note':'合成现场身份核对'})
        RoleAssignment.objects.filter(user=self.front,clinic=self.b).update(can_verify_patient_relationships=False)
        with self.assertRaises(PermissionDenied):referrals.confirm_referral(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        row.refresh_from_db();self.assertEqual(row.state,'REQUESTED')
    def test_referral_source_and_read_history_reject_sql_rewriting(self):
        row,_=self.new_referral()
        c=WorkspaceClient();c.force_login(self.doc);c.get(reverse('clinical_referral_detail',args=[row.pk]))
        for sql,args in [('UPDATE adc_clinical_referral SET patient_id=%s WHERE id=%s',[self.p2.pk,row.pk]),
                         ('DELETE FROM adc_clinical_referral_event',[]),('DELETE FROM adc_sensitive_read_event',[])]:
            with self.assertRaises(DatabaseError),transaction.atomic():
                with connection.cursor() as cur:cur.execute(sql,args)
    def test_website_and_native_show_same_scope_and_native_stop_rechecks(self):
        from portal.models import PatientAccess
        u=UserAccount.objects.create_user(username='native_patient',password='synthetic-pass-123')
        PatientAccess.objects.create(user=u,patient=self.p1)
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no);row,_=self.ref_step(row,'ACCEPT',actor=self.reviewer)
        c=WorkspaceClient();c.force_login(u)
        r=c.get(reverse('mini_referrals'));self.assertEqual(r.status_code,200)
        d=r.json()['data']['rows'][0];self.assertEqual(d['id'],row.pk);self.assertEqual(d['status'],'ACCEPTED')
        self.assertNotIn('PRIVATE_SOURCE',r.content.decode())
        r=c.post(reverse('mini_referral_stop_preview',args=[row.pk]),{},HTTP_X_ADC_WORKSPACE=c.current_token())
        self.assertEqual(r.status_code,200,r.content);token=r.json()['data']['proposal_token']
        self.assertEqual(ClinicalReferral.objects.get(pk=row.pk).state,'ACCEPTED')
        for _ in range(2):
            r=c.post(reverse('mini_referral_stop_confirm',args=[row.pk]),{'proposal_token':token,'confirmed':'on'},HTTP_X_ADC_WORKSPACE=c.current_token())
            self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(ClinicalReferral.objects.get(pk=row.pk).state,'REVOKED')
        r=c.get(reverse('clinical_referral_detail',args=[row.pk]));self.assertEqual(r.status_code,200);self.assertContains(r,'查阅已撤销')
        self.assertEqual(row.events.count(),4)
    def test_another_patient_cannot_read_or_stop_referral(self):
        from portal.models import PatientAccess
        u=UserAccount.objects.create_user(username='other_patient',password='synthetic-pass-123')
        PatientAccess.objects.create(user=u,patient=self.p2)
        row,_=self.new_referral()
        c=WorkspaceClient();c.force_login(u)
        self.assertEqual(c.get(reverse('mini_referrals')).json()['data']['rows'],[])
        r=c.post(reverse('mini_referral_stop_preview',args=[row.pk]),{},HTTP_X_ADC_WORKSPACE=c.current_token())
        self.assertEqual(r.status_code,404)
    def test_referral_acceptance_duplicate_concurrent_one_effect(self):
        row,_=self.new_referral();row,_=self.ref_step(row,'IDENTITY_CONFIRM',patient_no=self.p1.patient_no)
        token=referrals.prepare_referral(actor=self.reviewer,action='ACCEPT',referral_id=row.pk,fields={'note':'合成接收医师明确核对'})['proposal_token']
        barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.reviewer.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=self.reviewer._adc_workspace.pk)
                barrier.wait(timeout=10)
                result,replay=referrals.confirm_referral(actor=actor,proposal_token=token,confirmed=True)
                return result.pk,replay
            finally:close_old_connections()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sorted(replay for _,replay in results),[False,True]);row.refresh_from_db()
        self.assertEqual(row.state,'ACCEPTED');self.assertEqual(row.events.filter(action='ACCEPT').count(),1)
