"""Real PostgreSQL contracts; mocked provider responses do not prove platform access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import Client,TransactionTestCase,override_settings
from django.utils import timezone
from accounts import auth_providers as providers,patient_auth as auth,web_login as qr
from accounts.auth_config import authentication_settings
from accounts.external_models import ExternalIdentity,WebLoginTicket,SmsChallenge,AccountPhone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from patients.models import Patient
from portal.models import PatientAccess
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext

LIVE=dict(ADC_PATIENT_AUTH_MODE='live',ADC_PATIENT_IDENTITY_PROVIDER='disabled',ADC_SMS_PROVIDER='disabled',ADC_READ_ONLY=False,
    ADC_WECHAT_MINI_APP_ID='wx0000000000000001',ADC_WECHAT_MINI_APP_SECRET='isolated-secret',ADC_CLINICAL_SYNTHETIC=True)
CLOUD=dict(**{**LIVE,'ADC_SMS_PROVIDER':'cloudbase'},ADC_CLOUDBASE_ENV_ID='isolated-env-001',ADC_CLOUDBASE_REGION='ap-shanghai',ADC_CLOUDBASE_PUBLISHABLE_KEY='isolated-publishable',
    ADC_SMS_FREE_QUOTA_CONFIRMED=True,ADC_SMS_ALLOWED_TEST_PHONES=('13800000001','13800000002'),ADC_SMS_LIVE_TEST_LIMIT=10)


@override_settings(**LIVE)
class WebLoginTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.make_fixture()
        self.user=auth.exchange_identity(provider='WECHAT_MINI',app_id=LIVE['ADC_WECHAT_MINI_APP_ID'],subject='wx-first-subject')
        self.ctx=WorkspaceContext.objects.create(user=self.user,role='',login_channel='PATIENT');self.user._adc_workspace=self.ctx
        self.identity=ExternalIdentity.objects.get(user=self.user)
        self.proof=('WECHAT_MINI',LIVE['ADC_WECHAT_MINI_APP_ID'],'wx-first-subject')
    def request(self):return SimpleNamespace(user=AnonymousUser(),session={},META={'REMOTE_ADDR':'127.0.0.1'},build_absolute_uri=lambda path:'https://adc.example.test'+path)
    def start(self,request=None):
        request=request or self.request()
        with patch.object(providers,'mini_login_image',return_value=b'\x89PNG\r\n\x1a\nfixture') as mock:row=qr.start(request)
        mock.assert_called_once_with(row.pk.hex)
        return request,row
    def approve(self,row,actor=None):
        with patch.object(providers,'wechat_subject',return_value=self.proof):return qr.decide(actor=actor or self.user,value=row.pk,decision='approve',code='new-wx-login-code',confirmed=True)
    def test_ticket_has_three_minute_expiry_and_scan_contains_only_public_id(self):
        request,row=self.start();self.assertEqual(len(row.pk.hex),32);self.assertLessEqual((row.expires_at-row.created_at).total_seconds(),180)
        self.assertNotIn(request.session['adc_web_qr']['secret'],str(qr.describe(row)));self.assertEqual(row.origin,'https://adc.example.test')
    def test_scan_then_status_never_authenticates_browser(self):
        request,row=self.start();self.approve(row)
        self.assertEqual(qr.describe(qr.browser_ticket(request,row.pk))['state'],'APPROVED')
        self.assertFalse(request.user.is_authenticated);self.assertIsNone(WebLoginTicket.objects.get().consumed_at)
        self.assertEqual(qr.consume(request,row.pk).pk,self.user.pk);self.assertEqual(WebLoginTicket.objects.get().state,'CONSUMED')
        self.assertFalse(PatientAccess.objects.filter(user=self.user).exists());self.assertFalse(RoleAssignment.objects.filter(user=self.user).exists());self.assertEqual(Patient.objects.count(),2)
    def test_wrong_browser_cannot_view_or_consume(self):
        _,row=self.start();self.approve(row)
        with self.assertRaises(PermissionDenied):qr.browser_ticket(self.request(),row.pk)
        with self.assertRaises(PermissionDenied):qr.consume(self.request(),row.pk)
    def test_password_or_sms_account_without_matching_fresh_wechat_cannot_approve(self):
        _,row=self.start()
        with patch.object(providers,'wechat_subject',return_value=('WECHAT_MINI',LIVE['ADC_WECHAT_MINI_APP_ID'],'different-subject')):
            with self.assertRaises(PermissionDenied):qr.decide(actor=self.user,value=row.pk,decision='approve',code='fresh-code',confirmed=True)
        self.assertEqual(ExternalIdentity.objects.count(),1);self.assertEqual(WebLoginTicket.objects.get().state,'PENDING')
    def test_approval_requires_explicit_consent_and_new_provider_exchange(self):
        _,row=self.start()
        with patch.object(providers,'wechat_subject') as provider:
            with self.assertRaises(RuleError):qr.decide(actor=self.user,value=row.pk,decision='approve',confirmed=False)
            provider.assert_not_called()
        with patch.object(providers,'wechat_subject',side_effect=RuleError('微信码过期')):
            with self.assertRaises(RuleError):self.approve_with_expired_code(row)
    def approve_with_expired_code(self,row):return qr.decide(actor=self.user,value=row.pk,decision='approve',code='expired-code',confirmed=True)
    def test_reject_and_expiry_leave_no_login(self):
        request,row=self.start();qr.decide(actor=self.user,value=row.pk,decision='reject')
        with self.assertRaises(RuleError):qr.consume(request,row.pk)
        request,row=self.start(request);WebLoginTicket.objects.filter(pk=row.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(RuleError):self.approve(row)
        self.assertEqual(WebLoginTicket.objects.get(pk=row.pk).state,'EXPIRED')
    def test_refresh_invalidates_even_approved_ticket(self):
        request,row=self.start();self.approve(row);_,next_row=self.start(request)
        with self.assertRaises(PermissionDenied):qr.consume(request,row.pk)
        self.assertEqual(WebLoginTicket.objects.get(pk=row.pk).state,'REJECTED');self.assertNotEqual(next_row.pk,row.pk)
    def test_unlink_or_rebinding_invalidates_approval(self):
        request,row=self.start();self.approve(row)
        ExternalIdentity.objects.filter(pk=self.identity.pk).update(user=None,revision=self.identity.revision+1)
        with self.assertRaises(RuleError):qr.consume(request,row.pk)
        self.assertEqual(WebLoginTicket.objects.get().state,'REJECTED')
    def test_disabled_account_cannot_consume(self):
        request,row=self.start();self.approve(row);UserAccount.objects.filter(pk=self.user.pk).update(is_active=False)
        with self.assertRaises(RuleError):qr.consume(request,row.pk)
    def test_changed_password_invalidates_approved_ticket(self):
        request,row=self.start();self.approve(row);self.user.set_password('new-valid-test-password');self.user.save()
        with self.assertRaises(RuleError):qr.consume(request,row.pk)
    def test_changed_mobile_workspace_invalidates_approved_ticket(self):
        request,row=self.start();self.approve(row);WorkspaceContext.objects.filter(pk=self.ctx.pk).update(revision=2)
        with self.assertRaises(RuleError):qr.consume(request,row.pk)
    def test_changed_browser_account_cannot_claim_ticket(self):
        request,row=self.start();self.approve(row);request.user=self.user
        with self.assertRaises(PermissionDenied):qr.consume(request,row.pk)
    def test_two_concurrent_consumptions_have_one_effect(self):
        request,row=self.start();self.approve(row);barrier=Barrier(2);session=dict(request.session)
        def run():
            close_old_connections();r=self.request();r.session=dict(session);barrier.wait()
            try:qr.consume(r,row.pk);return 'ok'
            except RuleError:return 'refused'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sorted(results),['ok','refused']);self.assertEqual(self.user.identity_events.filter(action='WEB_LOGIN_CONSUME').count(),1)
    def test_two_simultaneous_phone_confirmations_produce_one_approval(self):
        _,row=self.start();barrier=Barrier(2)
        def run():
            close_old_connections();user=UserAccount.objects.get(pk=self.user.pk);user._adc_workspace=WorkspaceContext.objects.get(pk=self.ctx.pk);barrier.wait()
            try:self.approve(row,user);return 'ok'
            except RuleError:return 'refused'
            finally:close_old_connections()
        with patch.object(providers,'wechat_subject',return_value=self.proof),ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sorted(results),['ok','refused']);self.assertEqual(self.user.identity_events.filter(action='WEB_LOGIN_APPROVE').count(),1)
    def test_http_csrf_status_and_browser_completion(self):
        client=Client(enforce_csrf_checks=True);page=client.get('/portal/login/')
        self.assertContains(page,'id="wechat-qr-login"');self.assertNotContains(page,'员工登录')
        self.assertEqual(client.post('/portal/auth/wechat/qr/start/').status_code,403)
        token=client.cookies['csrftoken'].value
        with patch.object(providers,'mini_login_image',return_value=b'\x89PNG\r\n\x1a\nfixture'):
            response=client.post('/portal/auth/wechat/qr/start/',HTTP_X_CSRFTOKEN=token)
        data=response.json()['data'];row=WebLoginTicket.objects.get(pk=data['ticket']);self.approve(row)
        status=client.get('/portal/auth/wechat/qr/status/',{'ticket':row.pk.hex})
        self.assertEqual(status.json()['data']['state'],'APPROVED');self.assertNotIn('_auth_user_id',client.session)
        self.assertEqual(client.post('/portal/auth/wechat/qr/complete/',{'ticket':row.pk.hex}).status_code,403)
        done=client.post('/portal/auth/wechat/qr/complete/',{'ticket':row.pk.hex},HTTP_X_CSRFTOKEN=token)
        self.assertEqual(done.json()['data']['redirect'],'/portal/account/');self.assertEqual(int(client.session['_auth_user_id']),self.user.pk)
    def test_mini_without_account_login_cannot_see_destination(self):
        _,row=self.start();client=Client();response=client.get('/api/mini/v1/account/web-login/',{'ticket':row.pk.hex})
        self.assertEqual(response.status_code,401);self.assertNotIn(row.origin,response.content.decode())
    def test_official_jpeg_and_existing_png_codes_survive_storage_and_http_delivery(self):
        for raw,mime in ((b'\xff\xd8\xfffixture-jpeg','image/jpeg'),(b'\x89PNG\r\n\x1a\nfixture-png','image/png')):
            with self.subTest(mime=mime):
                client=Client();client.get('/portal/login/')
                opener=SimpleNamespace(open=lambda request,**kwargs:BytesIO(raw))
                with patch.object(providers,'mini_access_token',return_value='fixture-token'),patch.object(providers,'build_opener',return_value=opener):
                    response=client.post('/portal/auth/wechat/qr/start/')
                self.assertEqual(response.status_code,200)
                data=response.json()['data'];row=WebLoginTicket.objects.get(pk=data['ticket'])
                self.assertEqual(bytes(row.image),raw)
                image=client.get(data['image']);self.assertEqual(image.status_code,200)
                self.assertEqual(image['Content-Type'],mime);self.assertEqual(image['Cache-Control'],'no-store');self.assertEqual(image.content,raw)
                self.assertEqual(Client().get(data['image']).status_code,403)
    def test_qr_provider_errors_and_oversized_images_are_not_accepted_as_codes(self):
        for raw in (b'{"errcode":40001,"errmsg":"fixture"}',b'\xff\xd8\xff'+b'x'*1048576):
            with self.subTest(bytes=len(raw)),patch.object(providers,'mini_access_token',return_value='fixture-token'),patch.object(providers,'build_opener',return_value=SimpleNamespace(open=lambda request,**kwargs:BytesIO(raw))):
                with self.assertRaises(RuleError):providers.mini_login_image('a'*32)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_refuses_ticket_writes(self):
        with self.assertRaises(PermissionDenied):self.start()
    def test_bad_ticket_id_is_business_error(self):
        with self.assertRaises(RuleError):qr.inspect(self.user,'invalid')
    def test_restore_expires_pending_auth_but_preserves_accounts_and_passwords(self):
        from django.core.management import call_command
        from io import StringIO
        request,row=self.start();self.approve(row);password=self.user.password
        call_command('invalidate_auth_challenges',stdout=StringIO())
        with self.assertRaises(RuleError):qr.consume(request,row.pk)
        self.user.refresh_from_db();self.assertEqual(self.user.password,password);self.assertEqual(self.identity.user_id,self.user.pk)
    def test_mini_http_requires_own_account_token_and_fresh_wechat_proof(self):
        _,row=self.start();client=Client()
        with patch.object(providers,'wechat_subject',return_value=self.proof):session=client.post('/api/mini/v1/auth/wechat/',{'code':'new-code','confirmed':'on'}).json()['data']
        with patch.object(providers,'wechat_subject',return_value=self.proof) as proof:
            denied=client.post('/api/mini/v1/account/web-login/',{'ticket':row.pk.hex,'decision':'approve','code':'fresh-code','confirmed':'on'})
            self.assertEqual(denied.status_code,403);proof.assert_not_called()
            approved=client.post('/api/mini/v1/account/web-login/',{'ticket':row.pk.hex,'decision':'approve','code':'fresh-code','confirmed':'on'},HTTP_X_ADC_ACCOUNT=session['account_token'])
        self.assertEqual(approved.json()['data']['state'],'APPROVED');self.assertFalse(PatientAccess.objects.filter(user=self.user).exists())
    def test_native_wechat_repeat_login_preserves_account_without_phone(self):
        client=Client()
        with patch.object(providers,'wechat_subject',return_value=self.proof):
            for _ in range(2):self.assertEqual(client.post('/api/mini/v1/auth/wechat/',{'code':'fresh-code','confirmed':'on'}).status_code,200)
        self.assertEqual(ExternalIdentity.objects.count(),1);self.assertFalse(AccountPhone.objects.filter(user=self.user).exists());self.assertFalse(PatientAccess.objects.filter(user=self.user).exists())


@override_settings(**CLOUD)
class CloudBaseTests(FixtureMixin,TransactionTestCase):
    def setUp(self):self.make_fixture();self.request=SimpleNamespace(user=AnonymousUser(),session={},META={'REMOTE_ADDR':'127.0.0.1'})
    def issue(self,phone='13800000001',purpose='LOGIN'):
        with patch.object(providers,'cloudbase_send',return_value=('provider-held-challenge',600)):
            return auth.request_sms(request=self.request,phone=phone,purpose=purpose,confirmed=True)
    def confirm(self,sent,phone='13800000001',purpose='LOGIN',code='123456'):
        return auth.confirm_sms(request=self.request,challenge=sent['challenge'],phone=phone,code=code,purpose=purpose,confirmed=True)
    def test_provider_challenge_retained_without_client_otp_or_token(self):
        sent=self.issue();row=SmsChallenge.objects.get();self.assertEqual(row.provider_reference,'provider-held-challenge');self.assertEqual(row.code_digest,'')
        self.assertNotIn('test_code',sent);self.assertNotIn('provider-held-challenge',str(sent));self.assertEqual(sent['expires_seconds'],600)
        with patch.object(providers,'cloudbase_verify') as verify:user=self.confirm(sent)
        verify.assert_called_once_with('provider-held-challenge','123456')
        self.assertFalse(user.has_usable_password());self.assertFalse(PatientAccess.objects.filter(user=user).exists());self.assertFalse(RoleAssignment.objects.filter(user=user).exists())
        self.assertEqual(AccountPhone.objects.get(user=user).source,'SMS_VERIFIED')
    def test_provider_rejection_commits_attempt_and_no_user(self):
        sent=self.issue()
        with patch.object(providers,'cloudbase_verify',side_effect=RuleError('验证码错误')):
            with self.assertRaises(RuleError):self.confirm(sent)
        self.assertEqual(SmsChallenge.objects.get().attempts,1);self.assertFalse(ExternalIdentity.objects.filter(provider='SMS').exists())
    def test_wrong_session_never_calls_remote_verifier(self):
        sent=self.issue();self.request.session={}
        with patch.object(providers,'cloudbase_verify') as verify:
            with self.assertRaises(RuleError):self.confirm(sent)
            verify.assert_not_called()
    def test_used_challenge_does_not_recontact_provider(self):
        sent=self.issue()
        with patch.object(providers,'cloudbase_verify') as verify:
            self.confirm(sent)
            with self.assertRaises(RuleError):self.confirm(sent)
            self.assertEqual(verify.call_count,1)
    def test_unapproved_number_never_reserves_or_sends(self):
        with patch.object(providers,'cloudbase_send') as sender:
            with self.assertRaises(RuleError):auth.request_sms(request=self.request,phone='13800000009',purpose='LOGIN',confirmed=True)
            sender.assert_not_called();self.assertFalse(SmsChallenge.objects.exists())
    @override_settings(ADC_SMS_FREE_QUOTA_CONFIRMED=False)
    def test_unconfirmed_free_quota_disables_platform_calls(self):
        with patch.object(providers,'_request') as provider:
            with self.assertRaises(RuleError):auth.request_sms(request=self.request,phone='13800000001',purpose='LOGIN',confirmed=True)
            provider.assert_not_called()
    @override_settings(ADC_SMS_LIVE_TEST_LIMIT=1)
    def test_live_budget_is_entire_round_including_failure_not_daily(self):
        with patch.object(providers,'cloudbase_send',side_effect=RuleError('额度不足')):
            with self.assertRaises(RuleError):self.issue_failure()
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(days=2))
        with patch.object(providers,'cloudbase_send') as sender:
            with self.assertRaises(RuleError):auth.request_sms(request=self.request,phone='13800000002',purpose='LOGIN',confirmed=True)
            sender.assert_not_called()
    def issue_failure(self):return auth.request_sms(request=self.request,phone='13800000001',purpose='LOGIN',confirmed=True)
    def test_binding_cannot_take_other_account_phone(self):
        sent=self.issue()
        with patch.object(providers,'cloudbase_verify'):original=self.confirm(sent)
        actor=auth.exchange_identity(provider='WECHAT_MINI',app_id=LIVE['ADC_WECHAT_MINI_APP_ID'],subject='wx-other-subject')
        actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role='',login_channel='PATIENT');self.request.user=actor
        SmsChallenge.objects.update(created_at=timezone.now()-timedelta(minutes=2));sent=self.issue(purpose='BIND')
        with patch.object(providers,'cloudbase_verify'):
            with self.assertRaises(RuleError):self.confirm(sent,purpose='BIND')
        self.assertEqual(ExternalIdentity.objects.get(provider='SMS').user_id,original.pk);self.assertFalse(AccountPhone.objects.filter(user=actor).exists())
    def test_rebinding_preserves_original_account_and_releases_old_login(self):
        sent=self.issue()
        with patch.object(providers,'cloudbase_verify'):actor=self.confirm(sent)
        actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role='',login_channel='PATIENT');self.request.user=actor
        sent=self.issue('13800000002',purpose='BIND')
        with patch.object(providers,'cloudbase_verify'):self.assertEqual(self.confirm(sent,'13800000002',purpose='BIND').pk,actor.pk)
        self.assertIsNone(ExternalIdentity.objects.get(subject='13800000001').user_id);self.assertEqual(AccountPhone.objects.get(user=actor).phone,'13800000002')
    def test_provider_http_contract_keeps_credentials_on_backend(self):
        with patch.object(providers,'_request',return_value={'verification_id':'server-id','expires_in':600}) as call:
            self.assertEqual(providers.cloudbase_send('13800000001'),('server-id',600))
        args,kwargs=call.call_args;self.assertEqual(args[0],'https://isolated-env-001.api.tcloudbasegateway.com/auth/v1/verification')
        self.assertEqual(kwargs['data'],{'phone_number':'+86 13800000001','target':'ANY'});self.assertEqual(kwargs['headers']['Authorization'],'Bearer isolated-publishable')
        with patch.object(providers,'_request',return_value={'verification_token':'must-not-escape'}) as call:
            self.assertIsNone(providers.cloudbase_verify('server-id','123456'))
        self.assertEqual(call.call_args.kwargs['data'],{'verification_id':'server-id','verification_code':'123456'})
    def test_captcha_is_server_bound_and_used_on_sms_send(self):
        self.request.session['adc_sms_captcha']=dict(token='server-captcha',session=auth.session_key(self.request,create=True),expires=timezone.now().timestamp()+300)
        with patch.object(providers,'cloudbase_verify_captcha',return_value='validated-captcha') as captcha,patch.object(providers,'cloudbase_send',return_value=('server-id',600)) as sender:
            auth.request_sms(request=self.request,phone='13800000001',purpose='LOGIN',confirmed=True,captcha_key='AB12')
        captcha.assert_called_once_with('server-captcha','AB12');sender.assert_called_once_with('13800000001',captcha_token='validated-captcha')
    @override_settings(ADC_SMS_PROVIDER='demo',ADC_PATIENT_IDENTITY_PROVIDER='local')
    def test_live_mode_cannot_fallback_to_synthetic_auth(self):
        self.assertFalse(providers.capabilities()['sms_demo']);self.assertFalse(providers.capabilities()['sms_enabled'])
        self.assertIn('accounts.E021',[e.id for e in authentication_settings(None)])
