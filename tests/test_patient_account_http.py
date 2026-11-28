"""Actual CSRF/session/channel HTTP paths before and after identity review."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch
import hashlib
import json
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import Client,TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts import external_identity as identity
from accounts.external_models import AccountPhone,AccountIdentityEvent
from portal.models import PatientAccess
from portal import enrollment
from portal.enrollment_models import PatientEnrollment
from portal.account_access import can_account_login
from patients.models import Patient
from scheduling.models import Visit
from workspaces.models import WorkspaceContext
from workspaces.context import SESSION_KEY
from registry.directory_models import ClinicDirectory
from tests.fixtures import FixtureMixin


@override_settings(ADC_PATIENT_AUTH_MODE='demo',ADC_CLINICAL_SYNTHETIC=True,ADC_PATIENT_IDENTITY_PROVIDER='local',ADC_READ_ONLY=False)
class PatientAccountHttpTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.make_fixture()
        self.front._adc_workspace=WorkspaceContext.objects.create(user=self.front,role='FRONT_DESK',clinic=self.a,login_channel='STAFF')
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_patient_relationships=True)
        ClinicDirectory.objects.create(clinic=self.a,display_name='ADC口腔·合成长沙门店',city='长沙',province='湖南',district='岳麓',address='虚构门址',entrance='合成入口',public_phone='00000000000',is_published=True)
        self.browser=Client(enforce_csrf_checks=True);self.state=self.browser.get(reverse('mini_session')).json()['data']
        self.details=dict(clinic=str(self.a.pk),kind='NEW',name='合成新患者',date_of_birth='2001-01-01',billing_address='合成地址',phone='00000000000',email='',emergency_name='合成联络人',emergency_phone='00000000001',patient_reference='')

    def post(self,name,fields=None,args=None):
        return self.browser.post(reverse(name,args=args),fields or {},HTTP_X_CSRFTOKEN=self.state['csrf_token'],HTTP_X_ADC_ACCOUNT=self.state.get('account_token',''),HTTP_X_ADC_WORKSPACE=self.state.get('workspace_token',''))

    def login_local(self,subject='http-new',**fields):
        code,_=identity.issue_local_code(subject=subject)
        response=self.post('mini_account_local_login',dict(code=code,confirmed='on',**fields))
        self.assertEqual(response.status_code,200,response.content);self.state=response.json()['data']
        user=UserAccount.objects.get(pk=self.browser.session['_auth_user_id'])
        user._adc_workspace=WorkspaceContext.objects.get(pk=self.browser.session[SESSION_KEY]);return user

    def submitted(self):
        response=self.post('mini_enrollment_preview',self.details);self.assertEqual(response.status_code,200,response.content)
        token=response.json()['data']['proposal_token']
        response=self.post('mini_enrollment_confirm',dict(proposal_token=token,confirmed='on'));self.assertEqual(response.status_code,200,response.content)
        return PatientEnrollment.objects.get(pk=response.json()['data']['case']['id'])

    def test_guest_session_exposes_only_local_provider_availability(self):
        self.assertEqual(self.state['identity_provider'],'local');self.assertFalse(self.state['authenticated']);self.assertFalse(self.state['account_authenticated'])
        self.assertNotIn('account_token',self.state)

    def test_course_prefill_only_discloses_selected_synthetic_role_before_normal_login(self):
        invite = 'C' * 43
        password = 'fixture-only-course-login'
        owner = UserAccount.objects.create_user(username='course-owner', password=password)
        PatientAccess.objects.create(user=owner, patient=self.p1)
        self.front.set_password(password)
        self.front.save(update_fields=['password'])
        self.manager.set_password(password)
        self.manager.save(update_fields=['password'])
        roles = {
            'owner': {'username': owner.username, 'password': password},
            'front': {'username': self.front.username, 'password': password},
            'manager': {'username': self.manager.username, 'password': password},
            'finance': {'username': self.front.username, 'password': password},
        }
        config = {'invite_sha256': hashlib.sha256(invite.encode()).hexdigest(),
                  'expires_at': (timezone.now() + timedelta(hours=1)).isoformat(), 'roles': roles}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'private-course-roles.json'
            path.write_text(json.dumps(config))
            with override_settings(ADC_COURSE_ROLE_FILE=str(path)):
                self.assertEqual(self.browser.post(reverse('mini_course_role'), {'invite': invite}).status_code, 403)
                self.assertEqual(self.post('mini_course_role', {'invite': 'D' * 43}).status_code, 404)
                listing = self.post('mini_course_role', {'invite': invite})
                self.assertEqual(listing.json()['data']['roles'], [{'id': 'owner', 'label': '患者本人'}])
                self.assertNotIn(password, listing.content.decode())
                self.assertEqual(self.post('mini_course_role', {'invite': invite, 'role': 'front'}).status_code, 404)
                self.assertEqual(self.post('staff_course_role', {'invite': invite, 'role': 'owner'}).status_code, 404)
                self.assertEqual(self.post('staff_course_role', {'invite': invite, 'role': 'front'}).json()['data'], roles['front'])
                staff_choices = self.post('staff_course_role', {'invite': invite}).json()['data']['roles']
                self.assertEqual([item['id'] for item in staff_choices], ['front', 'manager'])
                self.assertEqual(self.post('staff_course_role', {'invite': invite, 'role': 'manager'}).json()['data'], roles['manager'])
                self.assertEqual(self.post('staff_course_role', {'invite': invite, 'role': 'finance'}).status_code, 404)
                self.assertEqual(self.post('mini_course_role', {'invite': invite, 'role': 'manager'}).status_code, 404)
                with override_settings(ADC_CLINICAL_SYNTHETIC=False):
                    self.assertEqual(self.post('mini_course_role', {'invite': invite}).status_code, 404)
                payload = self.post('mini_course_role', {'invite': invite, 'role': 'owner'})
                self.assertEqual(payload['Cache-Control'], 'no-store')
                self.assertEqual(payload.json()['data'], roles['owner'])
                self.assertFalse(self.browser.get(reverse('mini_session')).json()['data']['authenticated'])
                config['expires_at'] = (timezone.now() - timedelta(seconds=1)).isoformat()
                path.write_text(json.dumps(config))
                self.assertEqual(self.post('mini_course_role', {'invite': invite, 'role': 'owner'}).status_code, 404)
                logged_in = self.post('mini_login', roles['owner'])
                self.assertTrue(logged_in.json()['data']['authenticated'])
                self.assertFalse(Visit.objects.exists())

    def test_public_trial_role_picker_reuses_normal_staff_and_patient_login(self):
        password = 'isolated-trial-fixture-only'
        owner = UserAccount.objects.create_user(username='trial_owner', password=password)
        PatientAccess.objects.create(user=owner, patient=self.p1)
        self.front.username = 'trial_front_branch'
        self.front.set_password(password)
        self.front.save(update_fields=['username', 'password'])
        roles = {'owner': {'username': owner.username, 'password': password},
                 'front': {'username': self.front.username, 'password': password},
                 'manager': {'username': self.manager.username, 'password': 'private-never-listed'}}
        database = 'adc_public_trial_role_test'
        roster = {'purpose': 'public-role-trial-v1', 'database': database,
                  'expires_at': (timezone.now() + timedelta(days=1)).isoformat(), 'roles': roles}
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'trial.json'
            path.write_text(json.dumps(roster))
            # Only the deployment name is varied. Logins, grants, CSRF and contexts use PostgreSQL.
            identity = SimpleNamespace(settings_dict={'NAME': database})
            with override_settings(ADC_PUBLIC_TRIAL_ROLE_FILE=str(path)), patch('portal.course_roles.connection', identity):
                for endpoint, login_page, role, expected_context in (
                    ('staff_course_role','login','front','FRONT_DESK'),
                    ('mini_course_role','portal_login','owner','PATIENT'),
                ):
                    self.browser = Client(enforce_csrf_checks=True)
                    self.state = self.browser.get(reverse('mini_session')).json()['data']
                    form = self.browser.get(reverse(login_page))
                    self.assertContains(form, 'data-public-trial')
                    self.assertNotContains(form, password)
                    self.assertEqual(self.browser.post(reverse(endpoint), {'trial':'public'}).status_code, 403)
                    choices = self.post(endpoint, {'trial':'public'})
                    self.assertEqual([i['id'] for i in choices.json()['data']['roles']], [role])
                    self.assertNotContains(choices, password)
                    self.assertEqual(self.post(endpoint, {'trial':'public','invite':'invalid'}).status_code, 404)
                    self.assertEqual(self.post(endpoint, {'trial':'public','role':'manager'}).status_code, 404)
                    fields = self.post(endpoint, {'trial':'public','role':role})
                    self.assertEqual(fields.json()['data'], roles[role])
                    self.assertEqual(fields['Cache-Control'], 'no-store')
                    self.assertNotIn('_auth_user_id', self.browser.session)
                    csrf = self.browser.cookies['csrftoken'].value
                    logged_in = self.browser.post(reverse(login_page), fields.json()['data'], HTTP_X_CSRFTOKEN=csrf)
                    self.assertEqual(logged_in.status_code, 302)
                    context = WorkspaceContext.objects.get(pk=self.browser.session[SESSION_KEY])
                    self.assertEqual(context.role, expected_context)
                    from portal.course_roles import require_personal_password
                    with self.assertRaises(PermissionDenied):
                        require_personal_password(context.user)
                    require_personal_password(self.manager)
                    from workspaces.context import token_for
                    before = context.user.password
                    self.browser.post(reverse('own_password_change'), {
                        'old_password': password, 'new_password1': 'long-changed-visitor-password',
                        'new_password2': 'long-changed-visitor-password', 'workspace_token': token_for(context),
                    }, HTTP_X_CSRFTOKEN=self.browser.cookies['csrftoken'].value)
                    context.user.refresh_from_db()
                    self.assertEqual(context.user.password, before)
                self.browser = Client(enforce_csrf_checks=True)
                self.state = self.browser.get(reverse('mini_session')).json()['data']
                for bad in [{'database':'adc_public_trial_elsewhere'}, {'purpose':'private'},
                            {'invite_sha256':'a'*64}, {'expires_at':timezone.now().isoformat()}]:
                    path.write_text(json.dumps(roster | bad))
                    self.assertEqual(self.post('mini_course_role', {'trial':'public'}).status_code, 404)
                    self.assertNotContains(self.browser.get(reverse('login')), 'data-public-trial')
                path.write_text(json.dumps(roster | {'database':'adc_clinic'}))
                identity.settings_dict['NAME'] = 'adc_clinic'
                self.assertEqual(self.post('mini_course_role', {'trial':'public'}).status_code, 404)
                path.write_text(json.dumps(roster))
                identity.settings_dict['NAME'] = database
                with override_settings(ADC_CLINICAL_SYNTHETIC=False):
                    self.assertEqual(self.post('mini_course_role', {'trial':'public'}).status_code, 404)
                    for view in ('login','portal_login'):
                        self.assertNotContains(self.browser.get(reverse(view)), 'data-public-trial')
                with override_settings(ADC_PUBLIC_TRIAL_ROLE_FILE=''):
                    for view in ('login','portal_login'):
                        self.assertNotContains(self.browser.get(reverse(view)), 'data-public-trial')
                owner.set_password('replacement-for-operator-rotation')
                owner.save(update_fields=['password'])
                self.assertEqual(self.post('mini_course_role', {'trial':'public','role':'owner'}).status_code, 404)
                self.front.is_superuser = True
                self.front.save(update_fields=['is_superuser'])
                self.assertEqual(self.post('staff_course_role', {'trial':'public','role':'front'}).status_code, 404)
                self.assertFalse(Visit.objects.exists())

    def test_local_login_creates_pending_channel_without_business_authority(self):
        user=self.login_local();self.assertTrue(self.state['account_authenticated']);self.assertFalse(self.state['authenticated'])
        self.assertTrue(self.state['enrollment_required']);self.assertEqual(user._adc_workspace.role,'')
        self.assertEqual(self.browser.get(reverse('mini_visits')).status_code,409)
        self.assertFalse(PatientAccess.objects.filter(user=user).exists())

    def test_login_code_without_csrf_is_rejected_without_consumption(self):
        code,_=identity.issue_local_code(subject='csrf-probe')
        response=self.browser.post(reverse('mini_account_local_login'),dict(code=code,confirmed='on'))
        self.assertEqual(response.status_code,403);self.assertFalse(AccountIdentityEvent.objects.filter(identity__subject='csrf-probe').exists())

    def test_own_account_command_without_current_account_token_is_rejected(self):
        user=self.login_local();code,_=identity.issue_local_code(user_id=user.pk,phone='00000000000')
        response=self.browser.post(reverse('mini_account_phone'),dict(code=code,confirmed='on'),HTTP_X_CSRFTOKEN=self.state['csrf_token'])
        self.assertEqual(response.status_code,403);self.assertFalse(AccountPhone.objects.exists())

    def test_own_profile_never_exposes_external_subject_or_another_user_case(self):
        self.login_local();self.submitted()
        other=self.login_local('http-another')
        response=self.browser.get(reverse('mini_account_profile'));self.assertEqual(response.status_code,200)
        data=response.json()['data'];self.assertEqual(data['cases'],[])
        self.assertNotIn('subject',str(data['identities']));self.assertNotIn('session_key',str(data))

    def test_local_phone_and_password_setup_retain_session(self):
        user=self.login_local();phone,_=identity.issue_local_code(user_id=user.pk,phone='00000000000')
        response=self.post('mini_account_phone',dict(code=phone,confirmed='on'));self.assertEqual(response.status_code,200,response.content)
        fresh,_=identity.issue_local_code(subject='http-new')
        response=self.post('mini_account_password',dict(code=fresh,new_password='test-only-fallback-secret',repeat_password='test-only-fallback-secret',confirmed='on'))
        self.assertEqual(response.status_code,200,response.content);self.state=response.json()['data'];self.assertTrue(self.state['password_ready'])
        self.assertTrue(self.state['account_authenticated']);self.assertFalse(self.state['authenticated'])
        self.assertEqual(self.browser.get(reverse('patient_account')).status_code,200)

    def test_wrong_identity_cannot_reset_account_password(self):
        self.login_local();code,_=identity.issue_local_code(subject='wrong-reset-subject')
        response=self.post('mini_account_password',dict(code=code,new_password='test-only-fallback-secret',repeat_password='test-only-fallback-secret',confirmed='on'))
        self.assertEqual(response.status_code,403)

    def test_weak_password_returns_actionable_error_without_spending_identity_code(self):
        user=self.login_local();code,_=identity.issue_local_code(subject='http-new')
        response=self.post('mini_account_password',dict(code=code,new_password='123',repeat_password='123',confirmed='on'))
        self.assertEqual(response.status_code,409,response.content)
        from accounts.external_models import LocalIdentityCode
        self.assertIsNone(LocalIdentityCode.objects.get(digest=identity._digest(code)).consumed_at)
        user.refresh_from_db();self.assertFalse(user.has_usable_password())

    def test_old_account_token_cannot_submit_after_context_revision_changes(self):
        user=self.login_local();WorkspaceContext.objects.filter(pk=user._adc_workspace.pk).update(revision=1)
        response=self.post('mini_enrollment_preview',self.details);self.assertEqual(response.status_code,403)
        self.assertFalse(PatientEnrollment.objects.exists())

    def test_read_only_allows_reviewed_context_activation_but_not_phone_writes(self):
        user=self.login_local();PatientAccess.objects.create(user=user,patient=self.p1)
        code,_=identity.issue_local_code(user_id=user.pk,phone='00000000000')
        with override_settings(ADC_READ_ONLY=True):
            response=self.post('mini_account_activate',{'confirmed':'on'});self.assertEqual(response.status_code,200,response.content)
            self.state=response.json()['data'];self.assertTrue(self.state['authenticated'])
            response=self.post('mini_account_phone',{'code':code,'confirmed':'on'});self.assertEqual(response.status_code,403)
            self.assertFalse(AccountPhone.objects.exists());self.assertFalse(Visit.objects.exists())

    def test_disabled_original_self_binding_guides_restore_instead_of_duplicate_enrollment(self):
        user=self.login_local();PatientAccess.objects.create(user=user,patient=self.p1,is_active=False)
        response=self.browser.get(reverse('mini_account_profile'));self.assertEqual(response.status_code,200)
        data=response.json()['data'];self.assertTrue(data['self_binding_needs_review']);self.assertTrue(data['can_request_enrollment'])
        response=self.browser.get(reverse('patient_account'));self.assertContains(response,'原本人关联需要复核')
        response=self.post('mini_enrollment_preview',self.details);self.assertEqual(response.status_code,409)
        self.assertFalse(PatientEnrollment.objects.exists())

    def test_new_patient_api_to_staff_review_to_explicit_activation(self):
        user=self.login_local();row=self.submitted();self.assertEqual(Patient.objects.count(),2)
        token=enrollment.prepare_review(actor=self.front,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-HTTP-APPROVE')
        enrollment.confirm_review(actor=self.front,token=token,confirmed=True)
        refreshed=self.browser.get(reverse('mini_session')).json()['data'];self.assertFalse(refreshed['authenticated']);self.assertFalse(refreshed['enrollment_required'])
        self.assertEqual(self.post('mini_account_activate',{}).status_code,403)
        response=self.post('mini_account_activate',{'confirmed':'on'});self.assertEqual(response.status_code,200,response.content)
        self.state=response.json()['data'];self.assertTrue(self.state['authenticated']);self.assertEqual(self.state['patient_name'],self.details['name'])
        self.assertEqual(self.browser.get(reverse('mini_visits')).status_code,200);self.assertFalse(Visit.objects.exists())

    def test_new_request_replay_and_foreign_withdraw_preserve_one_case(self):
        self.login_local();row=self.submitted();self.login_local('other-withdrawer')
        response=self.post('mini_enrollment_withdraw',{'revision':row.revision,'confirmed':'on'},args=[row.pk])
        self.assertEqual(response.status_code,404);row.refresh_from_db();self.assertEqual(row.state,'PENDING')

    def test_pending_account_website_routes_are_usable(self):
        self.login_local()
        response=self.browser.get(reverse('patient_account'));self.assertContains(response,'核验本人档案');self.assertNotContains(response,'就诊人：')
        response=self.browser.get(reverse('patient_enrollment_new'));self.assertEqual(response.status_code,200)
        response=self.browser.post(reverse('patient_enrollment_new'),dict(self.details,account_token=self.state['account_token']),HTTP_X_CSRFTOKEN=self.state['csrf_token'])
        self.assertEqual(response.status_code,200,response.content);self.assertContains(response,'确认送交前台核验');self.assertContains(response,'出生日期')
        self.assertNotContains(response,'date_of_birth</dt>')

    def test_staff_channel_cannot_enter_own_patient_account_routes(self):
        self.browser.force_login(self.front);session=self.browser.session;session[SESSION_KEY]=str(self.front._adc_workspace.pk);session.save()
        self.assertEqual(self.browser.get(reverse('patient_account')).status_code,403)
        self.assertEqual(self.browser.get(reverse('mini_account_profile')).status_code,403)

    def test_staff_review_http_shows_selected_original_patient_before_confirmation(self):
        self.login_local();self.details['kind']='EXISTING';row=self.submitted()
        client=Client();client.force_login(self.front);session=client.session;session[SESSION_KEY]=str(self.front._adc_workspace.pk);session.save()
        from workspaces.context import token_for
        response=client.post(reverse('patient_enrollment_detail',args=[row.pk]),dict(action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-WEB-EVIDENCE',patient_no=self.p1.patient_no,workspace_token=token_for(self.front._adc_workspace)))
        self.assertEqual(response.status_code,200,response.content);self.assertContains(response,self.p1.patient_no);self.assertContains(response,self.p1.name)
        self.assertContains(response,'核验通过并关联');self.assertFalse(PatientAccess.objects.exists())

    def test_unlink_retains_pending_password_login_and_request_history(self):
        user=self.login_local();self.submitted();fresh,_=identity.issue_local_code(subject='http-new')
        identity.set_login_password(actor=user,code=fresh,new_password='test-only-fallback-secret',confirmed=True)
        # Reauthenticate with the new password to establish a current auth hash.
        self.state=self.browser.get(reverse('mini_session')).json()['data']
        user=self.login_local();item=user.external_identities.get()
        response=self.post('mini_account_unlink',dict(identity=item.pk,revision=item.revision,password='test-only-fallback-secret',confirmed='on'))
        self.assertEqual(response.status_code,200,response.content);self.assertTrue(can_account_login(user))
        self.post('mini_logout');self.state=self.browser.get(reverse('mini_session')).json()['data']
        response=self.post('mini_login',dict(username=user.username,password='test-only-fallback-secret'));self.assertEqual(response.status_code,200,response.content)
        self.state=response.json()['data'];self.assertTrue(self.state['account_authenticated']);self.assertFalse(self.state['authenticated'])
        self.assertEqual(len(self.browser.get(reverse('mini_account_profile')).json()['data']['cases']),1)

    def test_concurrent_different_accounts_cannot_claim_same_existing_patient(self):
        first=self.login_local('parallel-first');self.details['kind']='EXISTING';a=self.submitted()
        self.login_local('parallel-second');b=self.submitted()
        front2=UserAccount.objects.create_user(username='same-clinic-reviewer');RoleAssignment.objects.create(user=front2,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a,can_verify_patient_relationships=True)
        front2._adc_workspace=WorkspaceContext.objects.create(user=front2,role='FRONT_DESK',clinic=self.a,login_channel='STAFF')
        pairs=[]
        for actor,row in [(self.front,a),(front2,b)]:
            t=enrollment.prepare_review(actor=actor,case_id=row.pk,action='APPROVE',basis='IN_PERSON',reference='SYNTHETIC-PARALLEL',patient_no=self.p1.patient_no);pairs.append((actor.pk,actor._adc_workspace.pk,t))
        barrier=Barrier(2)
        def run(data):
            close_old_connections()
            try:
                user,ctx,t=data;actor=UserAccount.objects.get(pk=user);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctx)
                barrier.wait(timeout=10)
                try:enrollment.confirm_review(actor=actor,token=t,confirmed=True);return 'approved'
                except Exception as exc:
                    from adc_core.rules import RuleError
                    if isinstance(exc,RuleError):return 'conflict'
                    raise
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,pairs))
        self.assertEqual(sorted(results),['approved','conflict']);self.assertEqual(PatientAccess.objects.filter(patient=self.p1).count(),1);self.assertEqual(Patient.objects.count(),2)
