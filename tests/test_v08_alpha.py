"""Actual Django/PostgreSQL integration tests. Not executed by pure-check suite."""
from datetime import timedelta
from unittest.mock import patch
from django.test import TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts import governance as g
from adc_core.rules import RuleError
from care.models import AuditEvent
from coordination.forms import JoinForm
from coordination.models import WaitRequest
from coordination import services as co
from portal.models import PatientAccess
from workspaces.context import SESSION_KEY,token_for
from workspaces.models import WorkspaceContext
from tests.test_v07 import V07Fixture

PASSWORD='Account-Test!7392-Forest'
OP_PASSWORD='test-only-pass-abc'

class LoginShortcutTests(V07Fixture,TransactionTestCase):
    def setUp(self):self.setup07()
    def real_login(self,user,route='login',extra=None):
        user.set_password(PASSWORD);user.save(update_fields=['password'])
        return self.c.post(reverse(route),dict(username=user.username,password=PASSWORD,**(extra or {})))
    def test_patient_single_redirect(self):
        r=self.real_login(self.pa,'portal_login');self.assertEqual(r.url,reverse('portal_home'));self.assertEqual(self.ctx().role,'PATIENT')
    def test_single_role_context_has_no_clinic(self):
        self.real_login(self.manager);self.assertEqual(self.ctx().role,'MANAGER');self.assertIsNone(self.ctx().clinic_id)
    def test_multiple_clinics_do_not_become_multiple_roles(self):
        r=self.real_login(self.front);self.assertEqual(r.url,reverse('frontdesk_home'));self.assertIsNone(self.ctx().clinic_id)
    def test_multi_role_still_selects(self):
        RoleAssignment.objects.create(user=self.manager,role='HQ',scope_kind='CHAIN')
        r=self.real_login(self.manager);self.assertEqual(r.url,reverse('select_role'));self.assertEqual(self.ctx().role,'')
    def test_no_roles_remain_unselected(self):
        u=UserAccount.objects.create_user(username='norole');r=self.real_login(u)
        self.assertEqual(r.url,reverse('select_role'));self.assertContains(self.c.get(r.url),'尚未')
    def test_disabled_patient_access_not_activated(self):
        self.access.is_active=False;self.access.save();self.real_login(self.pa)
        self.assertEqual(self.ctx().role,'')
    def test_only_inactive_clinic_role_not_activated(self):
        self.a.is_active=False;self.a.save();self.real_login(self.manager);self.assertEqual(self.ctx().role,'')
    def test_switch_link_hidden_for_single_patient(self):
        r=self.real_login(self.pa);self.assertNotContains(self.c.get(reverse('portal_home')),'data-switch>切换身份')
    def test_switch_link_visible_for_multi_role(self):
        RoleAssignment.objects.create(user=self.manager,role='HQ',scope_kind='CHAIN')
        self.login(self.manager,'MANAGER',self.a)
        self.assertContains(self.c.get(reverse('manager_home')),'data-switch>切换身份')
    def test_login_does_not_honor_external_next(self):
        r=self.real_login(self.pa,extra={'next':'https://malicious.invalid/'})
        self.assertEqual(r.url,reverse('portal_home'))
    def test_login_replaces_previous_context_and_guide(self):
        self.login(self.front,'FRONT_DESK',self.a);old=self.ctx();s=self.c.session;s['adc_guide']={'x':1};s.save()
        self.real_login(self.front);self.assertNotEqual(self.ctx().pk,old.pk);self.assertIsNone(self.ctx().clinic_id);self.assertNotIn('adc_guide',self.c.session)
    def test_auto_role_cannot_read_other_workspace(self):
        self.real_login(self.pa);self.assertEqual(self.c.get(reverse('manager_home')).status_code,403)
    def test_readonly_login_can_activate(self):
        with override_settings(ADC_READ_ONLY=True):
            r=self.real_login(self.pa);self.assertEqual(r.url,reverse('portal_home'))
    def test_get_selection_does_not_activate_uninitialized_context(self):
        self.login(self.pa);self.assertEqual(self.ctx().role,'')

class WindowFormTests(V07Fixture,TransactionTestCase):
    def setUp(self):self.setup07()
    def form(self,start,end):
        return JoinForm({'clinic':self.a.pk,'earliest':start,'latest':end,'confirmed':True},user=self.pa)
    def test_reverse_has_specific_field_error(self):
        f=self.form(self.t+timedelta(hours=1),self.t);self.assertFalse(f.is_valid());self.assertIn('最晚结束时间必须晚于',str(f.errors['latest']))
    def test_past_has_specific_field_error(self):
        f=self.form(timezone.now()-timedelta(hours=1),self.t);self.assertFalse(f.is_valid());self.assertIn('earliest',f.errors)
    def test_short_interval_specific_error(self):
        f=self.form(self.t,self.t+timedelta(minutes=15));self.assertFalse(f.is_valid());self.assertIn('30分钟',str(f.errors['latest']))
    def test_beyond_horizon_specific_error(self):
        f=self.form(self.t,timezone.now()+timedelta(days=15));self.assertFalse(f.is_valid());self.assertIn('不能晚于',str(f.errors['latest']))
    def test_valid_precise_minutes_preserved(self):
        f=self.form(self.t,self.t+timedelta(minutes=31));self.assertTrue(f.is_valid(),f.errors);self.assertEqual(f.cleaned_data['earliest'],self.t)
    def test_server_render_min_max_and_script(self):
        self.login(self.pa,'PATIENT');r=self.c.get(reverse('waitlist_join'))
        self.assertContains(r,'wait-window-limits');self.assertContains(r,'min=');self.assertContains(r,'wait-window.js')
    def test_bypassed_picker_still_rejected(self):
        self.login(self.pa,'PATIENT');r=self.post('waitlist_join',{'clinic':self.a.pk,'earliest':self.t,'latest':self.t-timedelta(hours=1),'confirmed':True})
        self.assertEqual(r.status_code,200);self.assertFalse(WaitRequest.objects.exists())
    def test_scope_switch_still_rejects_old_time_form(self):
        self.login(self.front,'FRONT_DESK',self.a);old=token_for(self.ctx());self.post('activate_clinic',{'clinic':self.b.pk})
        r=self.c.post(reverse('waitlist_join'),{'workspace_token':old,'clinic':self.a.pk,'patient_no':self.p1.patient_no,'earliest':self.t,'latest':self.t+timedelta(hours=1),'confirmed':True})
        self.assertEqual(r.status_code,409);self.assertFalse(WaitRequest.objects.exists())

class WaitlistUXTests(V07Fixture,TransactionTestCase):
    def setUp(self):self.setup07()
    def test_frontdesk_has_navigation_cta(self):
        self.join();self.login(self.front,'FRONT_DESK',self.a);r=self.c.get(reverse('waitlist'))
        self.assertContains(r,'前往排程建议');self.assertContains(r,reverse('schedule_plans'))
    def test_patient_has_no_manager_cta(self):
        self.join();self.login(self.pa,'PATIENT');self.assertNotContains(self.c.get(reverse('waitlist')),reverse('schedule_plans'))
    def test_manager_no_scheduling_cta(self):
        self.join();self.login(self.manager,'MANAGER',self.a);self.assertNotContains(self.c.get(reverse('waitlist')),reverse('schedule_plans'))
    def test_no_expired_offers_hide_recycle_form(self):
        self.login(self.manager,'MANAGER',self.a);r=self.c.get(reverse('waitlist'))
        self.assertNotContains(r,'action="'+reverse('expire_offers')+'"');self.assertContains(r,'没有待回收')
    def test_plan_expiry_visible(self):
        e,p,o=self.offered();self.login(self.front,'FRONT_DESK',self.a)
        self.assertContains(self.c.get(reverse('schedule_plan',args=[p.pk])),'截止：')
    def test_accepted_offer_links_to_booking(self):
        e,p,o=self.offered();o=co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True)
        self.login(self.pa,'PATIENT');r=self.c.get(reverse('waitlist'))
        self.assertContains(r,'原邀约截止（历史信息）');self.assertContains(r,reverse('portal_visit',args=[o.visit_id]))

class GovernanceTests(V07Fixture,TransactionTestCase):
    def setUp(self):
        self.setup07();self.target=UserAccount.objects.create_user(username='new_target',password=PASSWORD)
    def change(self,action,**kw):
        opts=dict(actor=self.tech,target_id=self.target.pk,token=g.target_token(self.tech,self.target),action=action,operator_password=OP_PASSWORD,reason='合成账号管理验收')
        opts.update(kw);r=g.change_account(**opts);self.target.refresh_from_db();return r
    def test_create_has_no_implicit_roles(self):
        u=g.create_account(actor=self.tech,username='newperson',password=PASSWORD,operator_password=OP_PASSWORD,reason='合成账号创建测试')
        self.assertTrue(u.check_password(PASSWORD));self.assertFalse(u.is_staff);self.assertFalse(u.is_superuser);self.assertFalse(RoleAssignment.objects.filter(user=u).exists())
    def test_wrong_operator_password(self):
        with self.assertRaises(ValidationError):self.change('enable',operator_password='wrong')
    def test_doctor_cannot_govern(self):
        with self.assertRaises(PermissionDenied):g.target_token(self.doctor,self.target)
    def test_superuser_without_role_cannot_govern(self):
        RoleAssignment.objects.filter(user=self.tech).delete()
        with self.assertRaises(PermissionDenied):g.target_token(self.tech,self.target)
    def test_self_admin_change_blocked(self):
        with self.assertRaises(PermissionDenied):self.change('grant',target_id=self.tech.pk,token=g.target_token(self.tech,self.tech),role='HQ')
    def test_sysadmin_grant_not_exposed(self):
        with self.assertRaises(PermissionDenied):self.change('grant',role='SYSADMIN')
    def test_clinic_grant_is_exact_scope(self):
        self.change('grant',role='MANAGER',clinic_id=self.a.pk)
        self.assertEqual(RoleAssignment.objects.get(user=self.target).clinic_id,self.a.pk)
    def test_chain_role_cannot_include_clinic(self):
        with self.assertRaises(RuleError):self.change('grant',role='HQ',clinic_id=self.a.pk)
    def test_dentist_grant_needs_link(self):
        with self.assertRaises(RuleError):self.change('grant',role='DENTIST')
    def test_revoke_preserves_binding_history(self):
        self.change('grant',role='MANAGER',clinic_id=self.a.pk);a=RoleAssignment.objects.get(user=self.target)
        self.change('revoke',grant_id=a.pk);a.refresh_from_db();self.assertFalse(a.is_active)
    def test_other_accounts_grant_cannot_be_revoked(self):
        a=RoleAssignment.objects.filter(user=self.manager).first()
        with self.assertRaises(RoleAssignment.DoesNotExist):self.change('revoke',grant_id=a.pk)
    def test_patient_number_cannot_replace_binding(self):
        self.target=self.pa
        with self.assertRaises(RuleError):self.change('bind_patient',patient_no=self.p2.patient_no)
    def test_duplicate_patient_claim_rejected(self):
        with self.assertRaises(RuleError):self.change('bind_patient',patient_no=self.p1.patient_no)
    def test_bind_unclaimed_synthetic_patient(self):
        from patients.models import Patient
        p=Patient.objects.create(name='演示新患者',date_of_birth='2000-01-01',billing_address='虚构址',phone='000',emergency_name='合成联系人',emergency_phone='000',created_in_clinic=self.a)
        self.change('bind_patient',patient_no=p.patient_no);self.assertEqual(PatientAccess.objects.get(user=self.target).patient_id,p.pk)
    def test_disable_with_pending_visit_blocked(self):
        self.target=self.pa;self.book()
        with self.assertRaises(RuleError):self.change('disable')
        self.target.refresh_from_db();self.assertTrue(self.target.is_active)
    def test_disable_with_waitlist_blocked(self):
        self.target=self.pa;self.join()
        with self.assertRaises(RuleError):self.change('disable')
    def test_disable_is_not_delete(self):
        self.change('disable');self.assertFalse(UserAccount.objects.get(pk=self.target.pk).is_active)
        self.change('enable');self.assertTrue(UserAccount.objects.get(pk=self.target.pk).is_active)
    def test_stale_target_token_rejected(self):
        old=g.target_token(self.tech,self.target);self.change('grant',role='HQ')
        with self.assertRaises(RuleError):self.change('disable',token=old)
    def test_target_token_cannot_be_replayed_for_another(self):
        with self.assertRaises(RuleError):self.change('enable',token=g.target_token(self.tech,self.front))
    def test_audit_failure_rolls_back_grant(self):
        with patch('accounts.governance.emit',side_effect=RuntimeError('audit unavailable')):
            with self.assertRaises(RuntimeError):self.change('grant',role='HQ')
        self.assertFalse(RoleAssignment.objects.filter(user=self.target).exists())
    def test_authority_change_invalidates_context(self):
        ctx=WorkspaceContext.objects.create(user=self.target,role='HQ')
        self.change('grant',role='HQ');ctx.refresh_from_db();self.assertEqual(ctx.role,'');self.assertEqual(ctx.revision,1)
    def test_password_reset_not_logged(self):
        new='Changed!73928-NotReal';self.change('reset_password',new_password=new)
        self.assertTrue(self.target.check_password(new));self.assertNotIn(new,str(list(AuditEvent.objects.values('change_summary','reason'))))
    def test_readonly_blocks_management_service(self):
        with override_settings(ADC_READ_ONLY=True):
            with self.assertRaises(PermissionDenied):self.change('grant',role='HQ')
    def test_get_cannot_mutate_account(self):
        self.login(self.tech,'SYSADMIN');r=self.c.get(reverse('account_manage_change',args=[self.target.pk,'disable']))
        self.assertEqual(r.status_code,200);self.target.refresh_from_db();self.assertTrue(self.target.is_active)
    def test_form_has_no_password_echo(self):
        self.login(self.tech,'SYSADMIN');r=self.c.get(reverse('account_manage_change',args=[self.target.pk,'reset_password']))
        self.assertContains(r,'type="password"');self.assertNotContains(r,self.target.password)
    def test_technical_role_with_doctor_context_cannot_govern(self):
        self.tech.dentist=self.d2;self.tech.save();RoleAssignment.objects.create(user=self.tech,role='DENTIST',scope_kind='SELF_DENTIST')
        self.login(self.tech,'DENTIST');self.assertEqual(self.c.get(reverse('account_manage_list')).status_code,403)
    def test_post_with_stale_operator_context_rejected(self):
        RoleAssignment.objects.create(user=self.tech,role='HQ',scope_kind='CHAIN')
        self.login(self.tech,'SYSADMIN');old=token_for(self.ctx());self.post('activate_role',{'role':'HQ'})
        r=self.c.post(reverse('account_manage_change',args=[self.target.pk,'disable']),{'workspace_token':old,'confirmed':'on'})
        self.assertEqual(r.status_code,403);self.target.refresh_from_db();self.assertTrue(self.target.is_active)
    def test_own_password_change_logs_out_without_grant_change(self):
        self.pa.set_password(PASSWORD);self.pa.save();self.login(self.pa,'PATIENT');new='Another!Password3917'
        r=self.post('own_password_change',{'old_password':PASSWORD,'new_password1':new,'new_password2':new})
        self.assertEqual(r.status_code,302);self.pa.refresh_from_db();self.assertTrue(self.pa.check_password(new));self.assertNotIn('_auth_user_id',self.c.session)
        self.assertEqual(PatientAccess.objects.get(user=self.pa).patient_id,self.p1.pk)
