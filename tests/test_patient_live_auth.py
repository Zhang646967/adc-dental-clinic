"""PostgreSQL authentication, account ownership and real HTTP boundaries.

Provider responses are mocked; these tests never claim platform acceptance or
send a real SMS. The public teacher rehearsal uses separate synthetic data.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections,transaction,IntegrityError
from django.test import Client,SimpleTestCase,TransactionTestCase,override_settings
from django.utils import timezone
from django.urls import reverse
from accounts import patient_auth as auth,auth_providers as providers
from accounts.external_models import AccountIdentityEvent,AccountPhone,ExternalIdentity,SmsChallenge
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice
from finance.cash_models import CashEntry
from patients.models import Patient
from portal.models import PatientAccess
from scheduling.models import Visit
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext

DEMO=dict(ADC_PATIENT_AUTH_MODE='demo',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='demo',ADC_CLINICAL_SYNTHETIC=True,ADC_TEACHER_TEST_MODE=True,ADC_SMS_GLOBAL_DAILY_LIMIT=200,ADC_READ_ONLY=False)
LIVE=dict(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='tencent',ADC_SMS_SECRET_ID='isolated-test-id',ADC_SMS_SECRET_KEY='isolated-test-key',ADC_SMS_APP_ID='1400000000',ADC_SMS_SIGN_NAME='合成测试',ADC_SMS_TEMPLATE_ID='100000')


@override_settings(**DEMO)
class PatientLiveAuthTests(FixtureMixin,TransactionTestCase):
    def setUp(self):self.make_fixture();self.counter=0
    def request(self,user=None,session=None):
        return SimpleNamespace(user=user or AnonymousUser(),session=session if session is not None else {},META={'REMOTE_ADDR':'127.0.0.1'})
    def issue(self,phone='00000000110',request=None,purpose='LOGIN'):
        request=request or self.request();sent=auth.request_sms(request=request,phone=phone,purpose=purpose,confirmed=True)
        return request,sent
    def confirm(self,request,sent,phone='00000000110',purpose='LOGIN',**kwargs):
        return auth.confirm_sms(request=request,challenge=sent['challenge'],phone=phone,code=kwargs.get('code',sent['test_code']),purpose=purpose,confirmed=True)
    def account(self,username,patient):
        user=UserAccount.objects.create_user(username=username,password='test-only-patient-password')
        PatientAccess.objects.create(user=user,patient=patient)
        user._adc_workspace=WorkspaceContext.objects.create(user=user,role='PATIENT',login_channel='PATIENT')
        return user

    def test_registration_creates_account_without_patient_employee_or_money_grants(self):
        request,sent=self.issue();user=self.confirm(request,sent)
        self.assertFalse(user.has_usable_password());self.assertFalse(RoleAssignment.objects.filter(user=user).exists());self.assertFalse(PatientAccess.objects.filter(user=user).exists())
        self.assertEqual(Patient.objects.count(),2);self.assertFalse(Visit.objects.exists());self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())
        self.assertEqual(AccountPhone.objects.get(user=user).source,'DEMO_SMS')

    def test_existing_verified_phone_returns_same_account(self):
        request,sent=self.issue();user=self.confirm(request,sent)
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2))
        request2,sent2=self.issue();self.assertEqual(self.confirm(request2,sent2).pk,user.pk)

    def test_patient_entry_registers_on_same_page_without_employee_or_display_links(self):
        client=Client(enforce_csrf_checks=True)
        page=client.get('/portal/login/')
        self.assertContains(page,'id="sms-auth-form"')
        self.assertContains(page,'未注册的手机号验证后自动注册')
        self.assertContains(page,'微信快捷登录')
        self.assertNotContains(page,'mode-toggle');self.assertNotContains(page,'员工登录')
        self.assertNotContains(page,'href="/accounts/login/"')
        token=client.cookies['csrftoken'].value
        response=client.post('/portal/login/',{'action':'send','phone':'00000000501','confirmed':'on','csrfmiddlewaretoken':token})
        self.assertContains(response,'data-test-code')
        sent=response.context['sent']
        wrong='999999' if sent['test_code']!='999999' else '888888'
        response=client.post('/portal/login/',{'action':'confirm','phone':'00000000501','challenge':sent['challenge'],'code':wrong,'confirmed':'on','csrfmiddlewaretoken':token})
        self.assertEqual(response.status_code,200);self.assertFalse(ExternalIdentity.objects.filter(subject='00000000501').exists())
        response=client.post('/portal/login/',{'action':'confirm','phone':'00000000501','challenge':sent['challenge'],'code':sent['test_code'],'confirmed':'on','csrfmiddlewaretoken':token})
        self.assertRedirects(response,'/portal/account/')
        user=ExternalIdentity.objects.get(subject='00000000501').user
        self.assertFalse(user.has_usable_password());self.assertFalse(PatientAccess.objects.filter(user=user).exists())
        self.assertFalse(RoleAssignment.objects.filter(user=user).exists())
        self.assertFalse(Visit.objects.exists());self.assertFalse(CashEntry.objects.exists())

    def test_inline_send_requires_consent_and_failed_password_opens_only_its_panel(self):
        client=Client()
        response=client.post('/portal/login/',{'action':'send','phone':'00000000502'})
        self.assertEqual(response.status_code,200);self.assertFalse(SmsChallenge.objects.exists())
        response=client.post('/portal/login/',{'username':'missing','password':'invalid','login_method':'password'})
        self.assertContains(response,'class="auth-password" open')
        self.assertContains(response,'id="sms-auth-form"')

    def test_code_is_hashed_and_purpose_session_bound(self):
        request,sent=self.issue();row=SmsChallenge.objects.get()
        self.assertEqual(len(row.code_digest),64)
        with self.assertRaises(RuleError):self.confirm(self.request(),sent)
        with self.assertRaises(RuleError):self.confirm(request,sent,purpose='BIND')
        self.assertIsNone(SmsChallenge.objects.get().consumed_at)

    def test_used_code_never_replays_an_account_effect(self):
        request,sent=self.issue();self.confirm(request,sent);count=UserAccount.objects.count()
        with self.assertRaises(RuleError):self.confirm(request,sent)
        self.assertEqual(UserAccount.objects.count(),count)

    def test_wrong_attempts_commit_and_lock_after_five(self):
        request,sent=self.issue();bad='000000' if sent['test_code']!='000000' else '999999'
        for n in range(1,6):
            with self.assertRaises(RuleError):self.confirm(request,sent,code=bad)
            self.assertEqual(SmsChallenge.objects.get().attempts,n)
        with self.assertRaises(RuleError):self.confirm(request,sent)
        self.assertFalse(ExternalIdentity.objects.filter(provider='SMS').exists())

    def test_expired_code_cannot_register(self):
        request,sent=self.issue();SmsChallenge.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(RuleError):self.confirm(request,sent)

    def test_send_cooldown_and_phone_daily_limit(self):
        self.issue()
        with self.assertRaises(RuleError):self.issue()
        for n in range(4):
            SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2));self.issue()
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2))
        with self.assertRaises(RuleError):self.issue()
        self.assertEqual(SmsChallenge.objects.count(),5)

    @override_settings(ADC_SMS_GLOBAL_DAILY_LIMIT=1)
    def test_global_budget_limits_different_phones(self):
        self.issue()
        with self.assertRaises(RuleError):self.issue('00000000111')

    def test_ip_hour_limit_covers_different_phones(self):
        for n in range(10):self.issue('00000000'+str(200+n))
        with self.assertRaises(RuleError):self.issue('00000000300')

    def test_provider_failure_reserves_limit_and_creates_no_account(self):
        with patch('accounts.auth_providers.send_sms',side_effect=RuleError('服务暂不可用')):
            with self.assertRaises(RuleError):self.issue()
        self.assertEqual(SmsChallenge.objects.get().state,'FAILED')
        with self.assertRaises(RuleError):self.issue()
        self.assertFalse(ExternalIdentity.objects.filter(provider='SMS').exists())

    @override_settings(ADC_TEACHER_TEST_MODE=False)
    def test_demo_needs_explicit_teacher_flag(self):
        with self.assertRaises(RuleError):self.issue()

    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_demo_never_certifies_real_environment(self):
        with self.assertRaises(RuleError):self.issue()

    def test_demo_rejects_real_mobile_number(self):
        with self.assertRaises(RuleError):self.issue('13800000000')

    @override_settings(**LIVE)
    def test_live_sms_returns_no_plain_code(self):
        with patch('accounts.auth_providers.send_sms') as send:
            request,sent=self.issue('13800000000')
        self.assertNotIn('test_code',sent);self.assertFalse(sent['demo']);self.assertEqual(send.call_count,1)
        code=send.call_args.args[1]
        user=auth.confirm_sms(request=request,challenge=sent['challenge'],phone='13800000000',code=code,purpose='LOGIN',confirmed=True)
        self.assertEqual(AccountPhone.objects.get(user=user).source,'SMS_VERIFIED')

    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_never_sends_or_registers(self):
        with self.assertRaises(PermissionDenied):self.issue()
        self.assertFalse(SmsChallenge.objects.exists())

    def test_contact_phone_alone_never_merges_old_patient_or_account(self):
        user=self.account('old-patient',self.p1);AccountPhone.objects.create(user=user,phone='00000000110',source='LOCAL_SIMULATION',verified_at=timezone.now())
        request,sent=self.issue();new=self.confirm(request,sent)
        self.assertNotEqual(new.pk,user.pk);self.assertEqual(PatientAccess.objects.get(user=user).patient_id,self.p1.pk);self.assertFalse(PatientAccess.objects.filter(user=new).exists())

    def test_binding_is_own_patient_channel_only(self):
        user=self.account('bind-patient',self.p1);request,sent=self.issue(request=self.request(user),purpose='BIND')
        other=self.account('other-patient',self.p2)
        with self.assertRaises(RuleError):self.confirm(self.request(other,request.session.copy()),sent,purpose='BIND')
        self.assertEqual(self.confirm(request,sent,purpose='BIND').pk,user.pk)

    def test_phone_change_revokes_old_login_credential_and_preserves_chart(self):
        user=self.account('change-phone',self.p1);request,sent=self.issue(request=self.request(user),purpose='BIND');self.confirm(request,sent,purpose='BIND')
        newrequest,newsent=self.issue('00000000111',self.request(user),purpose='BIND');self.confirm(newrequest,newsent,'00000000111',purpose='BIND')
        self.assertIsNone(ExternalIdentity.objects.get(provider='SMS',subject='00000000110').user_id)
        self.assertEqual(ExternalIdentity.objects.get(provider='SMS',subject='00000000111').user_id,user.pk)
        self.assertEqual(PatientAccess.objects.get(user=user).patient_id,self.p1.pk)
        self.assertEqual(AccountIdentityEvent.objects.filter(user=user,action='PHONE_REPLACED').count(),1)

    def test_phone_bound_elsewhere_is_not_taken_over(self):
        request,sent=self.issue();owner=self.confirm(request,sent)
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2))
        other=self.account('claim-existing-phone',self.p1);request2,sent2=self.issue(request=self.request(other),purpose='BIND')
        with self.assertRaises(RuleError):self.confirm(request2,sent2,purpose='BIND')
        self.assertEqual(ExternalIdentity.objects.get(provider='SMS').user_id,owner.pk)
        self.assertFalse(AccountPhone.objects.filter(user=other).exists())

    def test_disabled_account_cannot_return_using_new_code(self):
        request,sent=self.issue();user=self.confirm(request,sent);UserAccount.objects.filter(pk=user.pk).update(is_active=False)
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2));request2,sent2=self.issue()
        with self.assertRaises(PermissionDenied):self.confirm(request2,sent2)

    def test_concurrent_confirmation_has_one_account_and_one_effect(self):
        request,sent=self.issue();barrier=Barrier(2)
        def run(_):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:return self.confirm(self.request(session=request.session.copy()),sent).pk
                except RuleError:return 'REJECTED'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(results.count('REJECTED'),1);self.assertEqual(ExternalIdentity.objects.filter(provider='SMS',user__isnull=False).count(),1)
        self.assertEqual(AccountIdentityEvent.objects.filter(action='BIND').count(),1)

    def test_same_wechat_subject_concurrently_creates_one_account(self):
        barrier=Barrier(2)
        def run(_):
            close_old_connections()
            try:barrier.wait(timeout=10);return auth.exchange_identity(provider='WECHAT_MINI',app_id='wx-test',subject='server_verified_subject').pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
        self.assertEqual(results[0],results[1]);self.assertEqual(ExternalIdentity.objects.filter(provider='WECHAT_MINI').count(),1)

    def test_database_rejects_two_sms_logins_for_one_account(self):
        user=self.account('unique-phone',self.p1)
        ExternalIdentity.objects.create(provider='SMS',app_id=auth.SMS_APP,subject='00000000110',user=user)
        with self.assertRaises(IntegrityError),transaction.atomic():ExternalIdentity.objects.create(provider='SMS',app_id=auth.SMS_APP,subject='00000000111',user=user)

    def test_web_registration_requires_csrf(self):
        client=Client(enforce_csrf_checks=True);client.get('/portal/auth/sms/')
        self.assertEqual(client.post('/portal/auth/sms/',{'phone':'00000000110','confirmed':'on','action':'send'}).status_code,403)
        self.assertFalse(SmsChallenge.objects.exists())

    def test_web_registration_and_account_open_without_patient_rights(self):
        client=Client();response=client.get('/portal/auth/sms/');self.assertContains(response,'课程测试验证码')
        sent=client.post('/portal/auth/sms/',{'phone':'00000000110','confirmed':'on','action':'send'})
        data=sent.context['sent'];self.assertIsNotNone(data)
        response=client.post('/portal/auth/sms/',{'phone':'00000000110','confirmed':'on','action':'confirm','code':data['test_code'],'challenge':data['challenge']})
        self.assertRedirects(response,'/portal/account/');self.assertFalse(PatientAccess.objects.exists())
        self.assertRedirects(client.get('/patients/'),reverse('select_role'),fetch_redirect_response=False)

    def test_mini_registration_and_sms_binding_require_account_token(self):
        client=Client();client.get('/api/mini/v1/session/')
        sent=client.post('/api/mini/v1/auth/sms/send/',{'phone':'00000000110','confirmed':'on'}).json()['data']
        response=client.post('/api/mini/v1/auth/sms/confirm/',{'phone':'00000000110','confirmed':'on','challenge':sent['challenge'],'code':sent['test_code']})
        self.assertTrue(response.json()['data']['account_authenticated']);self.assertFalse(response.json()['data']['authenticated'])
        denied=client.post('/api/mini/v1/account/phone/sms/send/',{'phone':'00000000111','confirmed':'on'})
        self.assertEqual(denied.status_code,403)
        token=response.json()['data']['account_token']
        allowed=client.post('/api/mini/v1/account/phone/sms/send/',{'phone':'00000000111','confirmed':'on'},HTTP_X_ADC_ACCOUNT=token)
        self.assertEqual(allowed.status_code,200)

    @override_settings(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_WECHAT_MINI_APP_ID='wx-isolated-test',ADC_WECHAT_MINI_APP_SECRET='not-a-live-secret')
    def test_mini_wechat_uses_server_identity_and_does_not_return_provider_tokens(self):
        with patch('accounts.auth_providers._request',return_value={'openid':'server_subject_001','session_key':'NEVER_RETURN_THIS'}):
            response=Client().post('/api/mini/v1/auth/wechat/',{'code':'valid-provider-code','confirmed':'on','openid':'attacker_subject'})
        self.assertEqual(response.status_code,200);self.assertNotContains(response,'NEVER_RETURN_THIS');self.assertTrue(response.json()['data']['account_authenticated'])
        self.assertEqual(ExternalIdentity.objects.get().subject,'server_subject_001');self.assertFalse(PatientAccess.objects.exists())

    @override_settings(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_WECHAT_WEB_APP_ID='wx-web-test',ADC_WECHAT_WEB_APP_SECRET='not-a-live-secret')
    def test_web_oauth_state_is_required_and_one_use(self):
        client=Client();started=client.post('/portal/auth/wechat/start/',{'confirmed':'on','kind':'WEB'})
        self.assertIn('open.weixin.qq.com/connect/qrconnect',started.url);state=client.session['adc_wechat_oauth']['state']
        with patch('accounts.auth_providers._request') as provider:
            response=client.get('/portal/auth/wechat/callback/',{'state':'wrong','code':'provider-code-001'})
        self.assertEqual(provider.call_count,0);self.assertRedirects(response,'/portal/login/')
        self.assertFalse(ExternalIdentity.objects.exists())
        client.post('/portal/auth/wechat/start/',{'confirmed':'on','kind':'WEB'});state=client.session['adc_wechat_oauth']['state']
        with patch('accounts.auth_providers._request',return_value={'openid':'oauth_server_subject','access_token':'NEVER_RETURN_THIS'}) as provider:
            response=client.get('/portal/auth/wechat/callback/',{'state':state,'code':'provider-code-001'})
            self.assertRedirects(response,'/portal/account/')
            client.get('/portal/auth/wechat/callback/',{'state':state,'code':'provider-code-001'})
        self.assertEqual(provider.call_count,1);self.assertEqual(ExternalIdentity.objects.count(),1)

    @override_settings(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_WECHAT_MINI_APP_ID='wx-isolated-test',ADC_WECHAT_MINI_APP_SECRET='not-a-live-secret',ADC_WECHAT_PHONE_ENABLED=True)
    def test_wechat_phone_needs_own_bound_mini_identity(self):
        user=self.account('wechat-phone',self.p1)
        with patch('accounts.auth_providers.wechat_phone',return_value='13800000000') as provider:
            with self.assertRaises(RuleError):auth.bind_wechat_phone(actor=user,code='provider-phone-code',confirmed=True)
            self.assertEqual(provider.call_count,0)
            ExternalIdentity.objects.create(provider='WECHAT_MINI',app_id='wx-isolated-test',subject='server_subject_001',user=user)
            phone=auth.bind_wechat_phone(actor=user,code='provider-phone-code',confirmed=True)
        self.assertEqual(phone.source,'WECHAT_PHONE');self.assertEqual(ExternalIdentity.objects.get(provider='SMS').user_id,user.pk)
        self.assertEqual(PatientAccess.objects.get(user=user).patient_id,self.p1.pk)

    @override_settings(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_WECHAT_MINI_APP_ID='wx-isolated-test',ADC_WECHAT_MINI_APP_SECRET='not-a-live-secret')
    def test_mini_can_bind_wechat_to_current_sms_account_without_merging(self):
        client=Client()
        with self.settings(**DEMO):
            sent=client.post('/api/mini/v1/auth/sms/send/',{'phone':'00000000110','confirmed':'on'}).json()['data']
            profile=client.post('/api/mini/v1/auth/sms/confirm/',{'phone':'00000000110','confirmed':'on','challenge':sent['challenge'],'code':sent['test_code']}).json()['data']
        with patch('accounts.auth_providers._request',return_value={'openid':'bound_mini_subject','session_key':'NEVER_RETURN_THIS'}) as provider:
            denied=client.post('/api/mini/v1/account/wechat/bind/',{'code':'provider-code-001','confirmed':'on'})
            self.assertEqual(denied.status_code,403);self.assertEqual(provider.call_count,0)
            allowed=client.post('/api/mini/v1/account/wechat/bind/',{'code':'provider-code-001','confirmed':'on'},HTTP_X_ADC_ACCOUNT=profile['account_token'])
        self.assertEqual(allowed.status_code,200)
        self.assertEqual(ExternalIdentity.objects.get(provider='SMS').user_id,ExternalIdentity.objects.get(provider='WECHAT_MINI').user_id)
        self.assertEqual(allowed.json()['data']['workspace_id'],profile['workspace_id'])

    @override_settings(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_WECHAT_WEB_APP_ID='wx-web-test',ADC_WECHAT_WEB_APP_SECRET='not-a-live-secret')
    def test_web_oauth_can_bind_existing_patient_without_changing_chart(self):
        user=self.account('web-bind-patient',self.p1);client=Client()
        client.post('/portal/login/',{'username':user.username,'password':'test-only-patient-password'})
        profile=client.get('/api/mini/v1/session/').json()['data']
        started=client.post('/portal/auth/wechat/start/',{'confirmed':'on','kind':'WEB','bind':'on','account_token':profile['account_token']})
        self.assertEqual(started.status_code,302);state=client.session['adc_wechat_oauth']['state']
        with patch('accounts.auth_providers._request',return_value={'openid':'bound_web_subject','access_token':'NEVER_RETURN_THIS'}):
            response=client.get('/portal/auth/wechat/callback/',{'state':state,'code':'provider-code-001'})
        self.assertRedirects(response,'/portal/account/')
        self.assertEqual(ExternalIdentity.objects.get(provider='WECHAT_WEB').user_id,user.pk)
        self.assertEqual(PatientAccess.objects.get(user=user).patient_id,self.p1.pk)


class ProviderAdapterTests(SimpleTestCase):
    @override_settings(ADC_SMS_PROVIDER='disabled',ADC_WECHAT_MINI_APP_ID='',ADC_WECHAT_MINI_APP_SECRET='')
    def test_unconfigured_providers_make_no_network_request(self):
        with patch('accounts.auth_providers._request') as network:
            with self.assertRaises(RuleError):providers.wechat_subject('provider-code','MINI')
            with self.assertRaises(RuleError):providers.send_sms('13800000000','123456')
        self.assertEqual(network.call_count,0)

    @override_settings(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_WECHAT_MINI_APP_ID='wx-test',ADC_WECHAT_MINI_APP_SECRET='not-a-live-secret')
    def test_wechat_error_is_generic_and_has_no_provider_payload(self):
        with patch('accounts.auth_providers._request',return_value={'errcode':40029,'errmsg':'SECRET_PROVIDER_DETAIL'}):
            with self.assertRaises(RuleError) as error:providers.wechat_subject('provider-code','MINI')
        self.assertNotIn('SECRET_PROVIDER_DETAIL',str(error.exception))

    @override_settings(**LIVE)
    def test_tencent_request_uses_signed_fixed_endpoint_and_expected_template(self):
        with patch('accounts.auth_providers._request',return_value={'Response':{'SendStatusSet':[{'Code':'Ok'}]}}) as network:
            providers.send_sms('13800000000','123456')
        self.assertEqual(network.call_args.args[0],'https://sms.tencentcloudapi.com/')
        self.assertEqual(network.call_args.kwargs['data']['TemplateParamSet'],['123456','5'])
        headers=network.call_args.kwargs['headers'];self.assertEqual(headers['X-TC-Version'],'2021-01-11');self.assertTrue(headers['Authorization'].startswith('TC3-HMAC-SHA256 Credential='))

    @override_settings(**LIVE)
    def test_sms_rejected_by_provider_is_not_marked_as_delivered(self):
        with patch('accounts.auth_providers._request',return_value={'Response':{'SendStatusSet':[{'Code':'FailedOperation.TemplateParamSetNotMatchApprovedTemplate'}]}}):
            with self.assertRaises(RuleError):providers.send_sms('13800000000','123456')
