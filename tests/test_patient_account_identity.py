"""Real PostgreSQL account/channel boundaries; local provenance never grants care."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections,DatabaseError,transaction
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts.external_models import ExternalIdentity,LocalIdentityCode,AccountPhone,AccountIdentityEvent
from accounts import external_identity as identity
from adc_core.rules import RuleError
from care.models import Invoice
from finance.cash_models import CashEntry
from patients.models import Patient
from portal import enrollment
from portal.enrollment_models import PatientEnrollment,PatientEnrollmentEvent
from portal.models import PatientAccess
from portal.policies import has_patient_access,patient_access
from scheduling.models import Visit
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext


@override_settings(ADC_PATIENT_AUTH_MODE='demo',ADC_CLINICAL_SYNTHETIC=True,ADC_PATIENT_IDENTITY_PROVIDER='local',ADC_READ_ONLY=False)
class PatientAccountIdentityTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.make_fixture()
        self.front._adc_workspace=WorkspaceContext.objects.create(user=self.front,role='FRONT_DESK',clinic=self.a,login_channel='STAFF')
        self.front2._adc_workspace=WorkspaceContext.objects.create(user=self.front2,role='FRONT_DESK',clinic=self.b,login_channel='STAFF')
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_patient_relationships=True)
        self.user=self.new_user('local-new-1')
        self.details=dict(name='合成新患者',date_of_birth='2001-01-01',billing_address='合成账单地址',phone='00000000000',email='',emergency_name='合成联系人',emergency_phone='00000000001')

    def new_user(self,subject):
        code,_=identity.issue_local_code(subject=subject)
        user=identity.exchange_login(code=code)
        user._adc_workspace=WorkspaceContext.objects.create(user=user,role='',login_channel='PATIENT')
        return user

    def request(self,kind='NEW',actor=None,clinic=None):
        actor=actor or self.user
        preview=enrollment.prepare_submit(actor=actor,clinic_id=(clinic or self.a).pk,kind=kind,details=self.details)
        row,_=enrollment.confirm_submit(actor=actor,token=preview['proposal_token'],confirmed=True)
        return row,preview['proposal_token']

    def review(self,row,action='APPROVE',actor=None,patient=None,**kw):
        actor=actor or self.front
        token=enrollment.prepare_review(actor=actor,case_id=row.pk,action=action,basis='IN_PERSON',reference='SYNTHETIC-LOCAL-REVIEW',patient_no=patient.patient_no if patient else '',**kw)
        return enrollment.confirm_review(actor=actor,token=token,confirmed=True)

    def test_first_external_login_has_no_patient_employee_or_money_authority(self):
        self.assertFalse(self.user.has_usable_password());self.assertFalse(has_patient_access(self.user))
        self.assertFalse(RoleAssignment.objects.filter(user=self.user).exists())
        with self.assertRaises(PermissionDenied):patient_access(self.user)
        self.assertEqual(Patient.objects.count(),2);self.assertFalse(Visit.objects.exists());self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())

    def test_same_subject_fresh_code_logs_in_same_account(self):
        before=UserAccount.objects.count();code,_=identity.issue_local_code(subject='local-new-1')
        result=identity.exchange_login(code=code);self.assertEqual(result.pk,self.user.pk);self.assertEqual(UserAccount.objects.count(),before)

    def test_replayed_code_cannot_create_second_effect(self):
        code,_=identity.issue_local_code(subject='local-another');user=identity.exchange_login(code=code);before=UserAccount.objects.count()
        with self.assertRaises(RuleError):identity.exchange_login(code=code)
        self.assertEqual(UserAccount.objects.count(),before);self.assertEqual(ExternalIdentity.objects.get(subject='local-another').user_id,user.pk)

    def test_expired_and_wrong_purpose_codes_are_not_consumed(self):
        code,_=identity.issue_local_code(subject='local-expired');LocalIdentityCode.objects.filter(digest=identity._digest(code)).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(RuleError):identity.exchange_login(code=code)
        phone,_=identity.issue_local_code(user_id=self.user.pk,phone='00000000000')
        with self.assertRaises(RuleError):identity.exchange_login(code=phone)
        self.assertIsNone(LocalIdentityCode.objects.get(digest=identity._digest(phone)).consumed_at)

    def test_client_asserted_subject_is_not_a_login_code(self):
        with self.assertRaises(RuleError):identity.exchange_login(code='local-new-1')
        with self.assertRaises(RuleError):identity.exchange_login(code='arbitrary-openid-value-from-browser')

    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_local_exchange_is_disabled_outside_synthetic_environment(self):
        with self.assertRaises(PermissionDenied):identity.issue_local_code(subject='blocked')

    @override_settings(ADC_PATIENT_IDENTITY_PROVIDER='disabled')
    def test_explicit_disabled_mode_prevents_local_credentials(self):
        with self.assertRaises(PermissionDenied):identity.issue_local_code(subject='blocked')

    def test_existing_patient_binding_requires_current_password(self):
        old=UserAccount.objects.create_user(username='existing-patient',password='test-only-existing-password')
        PatientAccess.objects.create(user=old,patient=self.p1)
        code,_=identity.issue_local_code(subject='explicit-existing')
        with self.assertRaises(PermissionDenied):identity.exchange_login(code=code,existing_user=old,existing_password='wrong')
        self.assertIsNone(LocalIdentityCode.objects.get(digest=identity._digest(code)).consumed_at)
        self.assertEqual(identity.exchange_login(code=code,existing_user=old,existing_password='test-only-existing-password').pk,old.pk)
        self.assertEqual(PatientAccess.objects.get(user=old).patient_id,self.p1.pk)

    def test_binding_cannot_move_existing_external_identity_to_another_account(self):
        other=UserAccount.objects.create_user(username='already-patient',password='test-only-existing-password');PatientAccess.objects.create(user=other,patient=self.p1)
        code,_=identity.issue_local_code(subject='local-new-1')
        with self.assertRaises(RuleError):identity.exchange_login(code=code,existing_user=other,existing_password='test-only-existing-password')
        self.assertEqual(ExternalIdentity.objects.get(subject='local-new-1').user_id,self.user.pk)

    def test_inactive_account_cannot_reenter_with_fresh_external_code(self):
        UserAccount.objects.filter(pk=self.user.pk).update(is_active=False)
        code,_=identity.issue_local_code(subject='local-new-1')
        with self.assertRaises(PermissionDenied):identity.exchange_login(code=code)

    def test_phone_purpose_is_bound_to_own_account(self):
        other=self.new_user('other-local-user');code,_=identity.issue_local_code(user_id=self.user.pk,phone='00000000000')
        with self.assertRaises(PermissionDenied):identity.verify_phone(actor=other,code=code,confirmed=True)
        self.assertFalse(AccountPhone.objects.exists())
        record=identity.verify_phone(actor=self.user,code=code,confirmed=True);self.assertEqual(record.source,'LOCAL_SIMULATION')
        with self.assertRaises(RuleError):identity.verify_phone(actor=self.user,code=code,confirmed=True)

    def test_shared_phone_and_change_do_not_merge_or_rebind_patients(self):
        other=self.new_user('other-shared-phone')
        for user in (self.user,other):
            code,_=identity.issue_local_code(user_id=user.pk,phone='00000000000');identity.verify_phone(actor=user,code=code,confirmed=True)
        self.assertEqual(AccountPhone.objects.filter(phone='00000000000').count(),2)
        code,_=identity.issue_local_code(user_id=self.user.pk,phone='00000000002');identity.verify_phone(actor=self.user,code=code,confirmed=True)
        self.assertFalse(PatientAccess.objects.exists());self.assertEqual(Patient.objects.count(),2)

    def test_real_phone_is_not_certified_by_local_issuer(self):
        with self.assertRaises(RuleError):identity.issue_local_code(user_id=self.user.pk,phone='13800000000')

    def test_phone_confirmation_and_patient_channel_are_required(self):
        code,_=identity.issue_local_code(user_id=self.user.pk,phone='00000000000')
        with self.assertRaises(RuleError):identity.verify_phone(actor=self.user,code=code,confirmed=False)
        ctx=self.user._adc_workspace;ctx.login_channel='STAFF';ctx.save(update_fields=['login_channel'])
        with self.assertRaises(PermissionDenied):identity.verify_phone(actor=self.user,code=code,confirmed=True)

    def test_new_request_does_not_create_patient_or_access(self):
        row,token=self.request();self.assertEqual(row.state,'PENDING');self.assertEqual(Patient.objects.count(),2);self.assertFalse(PatientAccess.objects.exists())
        again,replay=enrollment.confirm_submit(actor=self.user,token=token,confirmed=True);self.assertTrue(replay);self.assertEqual(row.pk,again.pk)

    def test_complete_new_patient_review_is_atomic_and_replayed_once(self):
        row,_=self.request();token=enrollment.prepare_review(actor=self.front,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-N1')
        a,_=enrollment.confirm_review(actor=self.front,token=token,confirmed=True);b,replay=enrollment.confirm_review(actor=self.front,token=token,confirmed=True)
        self.assertTrue(replay);self.assertEqual(a.patient_id,b.patient_id);self.assertEqual(Patient.objects.count(),3)
        self.assertEqual(a.patient.allergy_status,'UNKNOWN');self.assertEqual(PatientAccess.objects.get(user=self.user).patient_id,a.patient_id)
        self.assertFalse(Visit.objects.exists());self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())

    def test_existing_patient_review_keeps_original_patient_fields(self):
        before=list(Patient.objects.values());row,_=self.request('EXISTING');approved,_=self.review(row,patient=self.p1)
        self.assertEqual(approved.patient_id,self.p1.pk);self.assertEqual(list(Patient.objects.values()),before)

    def test_cross_clinic_and_missing_reviewer_duty_do_not_review(self):
        row,_=self.request()
        with self.assertRaises(PermissionDenied):self.review(row,actor=self.front2)
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_patient_relationships=False)
        with self.assertRaises(PermissionDenied):self.review(row)
        self.assertFalse(PatientAccess.objects.exists())

    def test_revoked_reviewer_after_preview_does_not_create_partial_patient(self):
        row,_=self.request();token=enrollment.prepare_review(actor=self.front,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-REVOKED')
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_patient_relationships=False)
        with self.assertRaises(PermissionDenied):enrollment.confirm_review(actor=self.front,token=token,confirmed=True)
        self.assertEqual(Patient.objects.count(),2);self.assertFalse(PatientAccess.objects.exists())

    def test_existing_patient_already_bound_cannot_be_taken_over(self):
        owner=UserAccount.objects.create_user(username='original-owner');PatientAccess.objects.create(user=owner,patient=self.p1)
        row,_=self.request('EXISTING')
        with self.assertRaises(RuleError):self.review(row,patient=self.p1)
        self.assertEqual(PatientAccess.objects.get(patient=self.p1).user_id,owner.pk)

    def test_paused_self_binding_restores_same_row_after_separate_frontdesk_review(self):
        original=PatientAccess.objects.create(user=self.user,patient=self.p1,is_active=False);before=list(Patient.objects.values())
        row,_=self.request('EXISTING');approved,_=self.review(row,patient=self.p1)
        original.refresh_from_db();self.assertTrue(original.is_active)
        self.assertEqual(PatientAccess.objects.get(user=self.user).pk,original.pk);self.assertEqual(approved.patient_id,self.p1.pk)
        self.assertEqual(list(Patient.objects.values()),before);self.assertFalse(Visit.objects.exists());self.assertFalse(CashEntry.objects.exists())
        self.assertEqual(row.events.order_by('-pk').first().snapshot['effect'],'RESTORE_EXISTING')

    def test_paused_self_binding_cannot_switch_to_another_visible_patient(self):
        original=PatientAccess.objects.create(user=self.user,patient=self.p1,is_active=False)
        self.p2.created_in_clinic=self.a;self.p2.save(update_fields=['created_in_clinic']);row,_=self.request('EXISTING')
        with self.assertRaises(RuleError):self.review(row,patient=self.p2)
        original.refresh_from_db();self.assertFalse(original.is_active);self.assertEqual(original.patient_id,self.p1.pk)

    def test_frontdesk_cannot_review_their_own_application_by_switching_roles(self):
        row,_=self.request()
        RoleAssignment.objects.create(user=self.user,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a,can_verify_patient_relationships=True)
        self.user._adc_workspace=WorkspaceContext.objects.create(user=self.user,role='FRONT_DESK',clinic=self.a,login_channel='STAFF')
        with self.assertRaises(PermissionDenied):self.review(row,actor=self.user)
        self.assertFalse(PatientAccess.objects.exists());self.assertEqual(Patient.objects.count(),2)

    def test_security_disabled_account_cannot_restore_subject_rights(self):
        access=PatientAccess.objects.create(user=self.user,patient=self.p1,is_active=False);row,_=self.request('EXISTING')
        token=enrollment.prepare_review(actor=self.front,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-BEFORE-SECURITY',patient_no=self.p1.patient_no)
        UserAccount.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(UserAccount.DoesNotExist):enrollment.confirm_review(actor=self.front,token=token,confirmed=True)
        access.refresh_from_db();self.assertFalse(access.is_active);row.refresh_from_db();self.assertEqual(row.state,'PENDING')

    def test_new_request_rejects_incomplete_profile_and_false_source_fields(self):
        self.details['billing_address']=''
        with self.assertRaises(Exception) as error:self.request()
        self.assertEqual(type(error.exception).__name__,'ValidationError')
        self.details['billing_address']='合成地址';self.details['is_verified']='true'
        with self.assertRaises(RuleError):self.request()
        self.assertFalse(PatientEnrollment.objects.exists())

    def test_patient_message_and_resubmission_keep_request_history(self):
        row,_=self.request();self.review(row,'NEED_INFO',patient_message='请确认紧急联系人。')
        row.refresh_from_db();self.assertEqual(row.patient_message,'请确认紧急联系人。')
        old=row.details.copy();self.details['emergency_name']='更正后的合成联系人'
        p=enrollment.prepare_submit(actor=self.user,clinic_id=self.a.pk,kind='NEW',details=self.details,case_id=row.pk)
        enrollment.confirm_submit(actor=self.user,token=p['proposal_token'],confirmed=True)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING');self.assertEqual(row.events.count(),3)
        self.assertEqual(row.events.order_by('pk').first().snapshot['details'],old)

    def test_withdrawn_request_cannot_be_approved_from_old_preview(self):
        row,_=self.request();t=enrollment.prepare_review(actor=self.front,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-WITHDRAW')
        enrollment.withdraw(actor=self.user,case_id=row.pk,expected_revision=0)
        with self.assertRaises(RuleError):enrollment.confirm_review(actor=self.front,token=t,confirmed=True)
        self.assertFalse(PatientAccess.objects.exists());self.assertEqual(Patient.objects.count(),2)

    def test_old_preview_does_not_overwrite_changed_patient_identity(self):
        row,_=self.request('EXISTING');t=enrollment.prepare_review(actor=self.front,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-STALE',patient_no=self.p1.patient_no)
        Patient.objects.filter(pk=self.p1.pk).update(name='已核对的新名称')
        with self.assertRaises(RuleError):enrollment.confirm_review(actor=self.front,token=t,confirmed=True)
        self.assertFalse(PatientAccess.objects.exists())

    def test_history_tables_reject_changes(self):
        self.request()
        for model in (AccountIdentityEvent,PatientEnrollmentEvent):
            with self.assertRaises(DatabaseError),transaction.atomic():model.objects.all().delete()
            with self.assertRaises(DatabaseError),transaction.atomic():model.objects.update(snapshot={})

    def test_pending_user_cannot_unlink_their_only_unrecoverable_identity(self):
        item=ExternalIdentity.objects.get(user=self.user)
        with self.assertRaises(RuleError):identity.unlink_identity(actor=self.user,identity_id=item.pk,expected_revision=item.revision,password='',confirmed=True)

    def test_unlink_retains_events_and_patient_binding(self):
        self.user.set_password('test-only-fallback-password');self.user.save(update_fields=['password']);PatientAccess.objects.create(user=self.user,patient=self.p1)
        item=ExternalIdentity.objects.get(user=self.user)
        identity.unlink_identity(actor=self.user,identity_id=item.pk,expected_revision=item.revision,password='test-only-fallback-password',confirmed=True)
        item.refresh_from_db();self.assertIsNone(item.user_id);self.assertEqual(PatientAccess.objects.get(user=self.user).patient_id,self.p1.pk)
        self.assertEqual(AccountIdentityEvent.objects.filter(user=self.user,action='UNBIND').count(),1)

    def test_concurrent_fresh_codes_for_same_subject_create_one_account(self):
        codes=[identity.issue_local_code(subject='concurrent-subject')[0] for _ in range(2)];barrier=Barrier(2)
        def run(code):
            close_old_connections()
            try:barrier.wait(timeout=10);return identity.exchange_login(code=code).pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,codes))
        self.assertEqual(results[0],results[1]);self.assertEqual(ExternalIdentity.objects.filter(subject='concurrent-subject').count(),1)
