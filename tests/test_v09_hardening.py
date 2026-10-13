"""Real PostgreSQL/HTTP regression scenarios. Must run with the Django gate."""
from unittest.mock import patch
from django.test import TransactionTestCase, Client, override_settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse
from accounts import governance as g
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from coordination.models import WaitRequest,WaitOffer
from scheduling.models import Visit
from portal.models import PatientAccess
from workspaces.context import token_for
from workspaces.models import WorkspaceContext
from tests.test_v07 import V07Fixture
OP='test-only-pass-abc'
NEW='Recovery-Example!81973-locals'

class ReadOnlyHTTPTests(V07Fixture,TransactionTestCase):
    def setUp(self):self.setup07()
    def test_query_preserves_all_business_records(self):
        e,p,o=self.offered();self.login(self.pa,'PATIENT')
        def snapshot():return (list(Visit.objects.values()),list(WaitRequest.objects.values()),list(WaitOffer.objects.values()),AuditEvent.objects.count())
        before=snapshot()
        with override_settings(ADC_READ_ONLY=True):
            self.assertContains(self.post('guide_result_wait',args=[e.pk]),'NEEDS_CONFIRMATION')
        self.assertEqual(before,snapshot())
    def test_other_patient_still_404(self):
        e=self.join();self.login(self.pb,'PATIENT')
        with override_settings(ADC_READ_ONLY=True):self.assertEqual(self.post('guide_result_wait',args=[e.pk]).status_code,404)
    def test_no_csrf_bypass_in_readonly(self):
        e=self.join();self.login(self.pa,'PATIENT');strict=Client(enforce_csrf_checks=True);strict.cookies=self.c.cookies
        with override_settings(ADC_READ_ONLY=True):
            r=strict.post(reverse('guide_result_wait',args=[e.pk]),{'workspace_token':token_for(self.ctx())});self.assertEqual(r.status_code,403)
    def test_business_write_still_denied(self):
        e,p,o=self.offered();self.login(self.pa,'PATIENT')
        with override_settings(ADC_READ_ONLY=True):
            r=self.post('wait_offer',{'confirmed':True,'action':'accept'},args=[o.pk]);self.assertEqual(r.status_code,403)
        self.assertFalse(Visit.objects.exists())
    def test_wrong_role_not_allowed(self):
        e=self.join();self.login(self.manager,'MANAGER',self.a)
        with override_settings(ADC_READ_ONLY=True):self.assertEqual(self.post('guide_result_wait',args=[e.pk]).status_code,403)
    def test_old_context_denied(self):
        e=self.join();self.login(self.front,'FRONT_DESK',self.a);old=token_for(self.ctx());self.post('activate_clinic',{'clinic':self.b.pk})
        with override_settings(ADC_READ_ONLY=True):self.assertEqual(self.c.post(reverse('guide_result_wait',args=[e.pk]),{'workspace_token':old}).status_code,409)

class SecuritySuspensionTests(V07Fixture,TransactionTestCase):
    def setUp(self):self.setup07()
    def change(self,target,action='security_suspend',**kwargs):
        opts=dict(actor=self.tech,target_id=target.pk,token=g.target_token(self.tech,target),action=action,operator_password=OP,reason='演示账号安全事件处置')
        opts.update(kwargs);r=g.change_account(**opts);target.refresh_from_db();return r
    def test_pending_visit_does_not_prevent_security_suspend(self):
        self.book();self.change(self.doctor);self.assertFalse(self.doctor.is_active);self.assertFalse(self.doctor.has_usable_password())
    def test_pending_patient_wait_does_not_prevent_suspend(self):
        self.join();self.change(self.pa);self.assertFalse(self.pa.is_active)
    def test_business_history_and_assignments_unchanged(self):
        self.book();before=(list(Visit.objects.values()),list(RoleAssignment.objects.values()),list(PatientAccess.objects.values()))
        self.change(self.doctor)
        self.assertEqual(before,(list(Visit.objects.values()),list(RoleAssignment.objects.values()),list(PatientAccess.objects.values())))
    def test_regular_retirement_still_blocks(self):
        self.book()
        with self.assertRaises(RuleError):self.change(self.doctor,'disable')
        self.doctor.refresh_from_db();self.assertTrue(self.doctor.is_active)
    def test_enable_requires_new_credentials(self):
        self.change(self.doctor)
        with self.assertRaises(RuleError):self.change(self.doctor,'enable')
    def test_reset_does_not_enable_automatically(self):
        self.change(self.doctor);self.change(self.doctor,'reset_password',new_password=NEW);self.assertFalse(self.doctor.is_active)
    def test_reset_then_enable(self):
        self.change(self.doctor);self.change(self.doctor,'reset_password',new_password=NEW);self.change(self.doctor,'enable');self.assertTrue(self.doctor.is_active);self.assertTrue(self.doctor.check_password(NEW))
    def test_old_session_does_not_revive_after_recovery(self):
        self.login(self.doctor,'DENTIST');old_ctx=self.ctx();old_revision=old_ctx.revision
        self.change(self.doctor);self.change(self.doctor,'reset_password',new_password=NEW);self.change(self.doctor,'enable')
        old_ctx.refresh_from_db();self.assertGreater(old_ctx.revision,old_revision)
        self.assertEqual(self.c.get(reverse('doctor_home')).status_code,302)
        self.assertNotIn('_auth_user_id',self.c.session)
    def test_wrong_operator_password_does_not_suspend(self):
        with self.assertRaises(ValidationError):self.change(self.doctor,operator_password='incorrect')
        self.doctor.refresh_from_db();self.assertTrue(self.doctor.is_active)
    def test_self_or_technical_target_protected(self):
        with self.assertRaises(PermissionDenied):self.change(self.tech)
    def test_readonly_mode_does_not_suspend(self):
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(PermissionDenied):self.change(self.doctor)
    def test_audit_failure_rolls_back_security_change(self):
        old=self.doctor.password
        with patch('accounts.governance.emit',side_effect=RuntimeError('injected audit failure')):
            with self.assertRaises(RuntimeError):self.change(self.doctor)
        self.doctor.refresh_from_db();self.assertTrue(self.doctor.is_active);self.assertEqual(old,self.doctor.password)
    def test_stale_target_token_rejected(self):
        token=g.target_token(self.tech,self.doctor);self.doctor.set_password(NEW);self.doctor.save(update_fields=['password'])
        with self.assertRaises(RuleError):self.change(self.doctor,token=token)
    def test_ui_requires_extra_security_confirmation(self):
        self.login(self.tech,'SYSADMIN');path=reverse('account_manage_change',args=[self.doctor.pk,'security_suspend'])
        response=self.c.get(path);self.assertContains(response,'security_confirmed')
        payload={'workspace_token':token_for(self.ctx()),'target_token':g.target_token(self.tech,self.doctor),'reason':'演示安全处置测试','operator_password':OP,'confirmed':True}
        self.assertEqual(self.c.post(path,payload).status_code,200);self.doctor.refresh_from_db();self.assertTrue(self.doctor.is_active)
    def test_direct_http_submission_with_confirmation(self):
        self.login(self.tech,'SYSADMIN');path=reverse('account_manage_change',args=[self.doctor.pk,'security_suspend'])
        payload={'workspace_token':token_for(self.ctx()),'target_token':g.target_token(self.tech,self.doctor),'reason':'演示安全处置测试','operator_password':OP,'confirmed':True,'security_confirmed':True}
        self.assertEqual(self.c.post(path,payload).status_code,302);self.doctor.refresh_from_db();self.assertFalse(self.doctor.is_active)
