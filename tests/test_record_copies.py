"""Patient-copy scope, independent review, immutable files and PostgreSQL races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
import hashlib,uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from accounts.governance import change_account,target_token
from adc_core.rules import RuleError
from clinical import record_copies as cmd,copy_generation as gen
from clinical.copy_models import RecordCopyRequest,RecordCopyItem,RecordCopyFile,RecordCopyEvent
from clinical.copy_projection import data,packet
from clinical.archive_models import ArchivePackage
from portal.models import PatientAccess
from tests.test_medical_archives import ArchiveFixture
from tests.workspace_client import WorkspaceClient


class CopyFixture(ArchiveFixture):
    def ctx(self,user,role,clinic=None):
        super().ctx(user,role,clinic)
        if role=='PATIENT':
            user._adc_workspace.login_channel='PATIENT';user._adc_workspace.save(update_fields=['login_channel'])
        return user
    def setup_copy(self):
        self.setup_archive();self.pkg=self.fixed()
        self.duty(self.front,'copy_verifier',grant_id=RoleAssignment.objects.get(user=self.front,role='FRONT_DESK',clinic=self.a).pk)
        self.duty(self.reviewer,'copy_reviewer',clinic_id=self.a.pk)
        self.ctx(self.front,'FRONT_DESK',self.a);self.ctx(self.reviewer,'DENTIST');self.ctx(self.patient_user,'PATIENT')
    def duty(self,target,action,enabled=True,**kw):
        return change_account(actor=self.tech,target_id=target.pk,token=target_token(self.tech,target),action=action,
            operator_password='test-only-pass-abc',reason='课程合成：明确本用途病历副本核验及独立审核职责。',reviewer_enabled=enabled,**kw)
    def do(self,actor,action,row=None,**fields):
        p=cmd.prepare(actor=actor,action=action,request_id=row.pk if row else None,fields=fields)
        return cmd.confirm(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]
    def request(self,**kw):
        return self.do(self.patient_user,'SUBMIT',clinic=self.a.pk,visits=[self.v.pk],sections=list(cmd.SECTIONS),purpose='复诊就医与个人留存',**kw)
    def verified(self,row=None):
        row=row or self.request()
        return self.do(self.front,'VERIFY',row,decision='VERIFY',basis='IN_PERSON',identity_reference='SYNTHETIC-COPY-ID',authority_reference='SYNTHETIC-COPY-AUTH',purpose_checked=True,
            pickup_until=timezone.now()+timedelta(days=7),reviewer=self.reviewer.clinicalreviewerappointment_set.get(clinic=self.a).pk)
    def approved(self,row=None):return self.do(self.reviewer,'REVIEW',self.verified(row),decision='APPROVE',message='独立核对本用途、本人或代理依据及准确资料范围。')
    def ready_copy(self):
        row=self.approved();self.assertTrue(gen.generate(row.pk)['published']);row.refresh_from_db();return row
    def claim(self,row,actor=None):
        actor=actor or self.patient_user;p=cmd.prepare(actor=actor,action='CLAIM',request_id=row.pk)
        cmd.confirm(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
        return cmd.pickup_token(actor,row,p['proposal_token'])
    def proxy(self,kind='WRITTEN'):
        user=UserAccount.objects.create_user(username='copy_proxy',password='synthetic-copy-only')
        PatientAccess.objects.create(user=user,patient=self.p2);self.ctx(user,'PATIENT')
        row=self.do(self.front,'REGISTER',patient_no=self.v.patient.patient_no,recipient_account=user.username,
            recipient_name='合成受托人',kind=kind,clinic=self.a.pk,visits=[self.v.pk],sections=['DOCUMENT','CONSENT'],purpose='经患者书面委托办理本次病历复制')
        return user,row


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class RecordCopyTests(CopyFixture,TransactionTestCase):
    def setUp(self):self.setup_copy()

    def test_complete_self_application_verification_review_and_authenticated_pickup(self):
        before=self.money();original=bytes(self.pkg.pdf);row=self.ready_copy()
        token=self.claim(row);out,pdf=cmd.pickup(actor=self.patient_user,token=token)
        self.assertTrue(pdf.startswith(b'%PDF-'));self.assertEqual(row.file.sha256,hashlib.sha256(pdf).hexdigest())
        out.refresh_from_db();self.assertEqual(out.state,'DELIVERED')
        self.assertEqual(RecordCopyEvent.objects.filter(action='FILE_RESPONSE').count(),1)
        self.assertEqual(bytes(self.pkg.pdf),original);self.assertEqual(before,self.money())

    def test_identity_return_and_explicit_resubmission_preserve_history(self):
        row=self.request();self.do(self.front,'VERIFY',row,decision='RETURN',message='请补充原件核对编号与用途说明。')
        row.refresh_from_db();self.assertEqual(row.state,'NEED_INFO')
        self.do(self.patient_user,'RESUBMIT',row,message='已到店补充核对原件，按原范围继续申请。')
        row.refresh_from_db();self.assertEqual(row.state,'PENDING');self.verified(row)
        self.assertEqual(list(row.events.values_list('action',flat=True)),['SUBMIT','VERIFY','RESUBMIT','VERIFY'])

    def test_independent_return_requires_new_material_verification(self):
        row=self.verified();self.do(self.reviewer,'REVIEW',row,decision='RETURN',message='请重新明确领取有效期与材料范围。')
        row.refresh_from_db();self.assertEqual(row.state,'NEED_INFO')
        self.assertFalse(RecordCopyFile.objects.exists())

    def test_missing_fixed_file_keeps_application_without_fake_approval(self):
        # A second finished visit is unnecessary: preserve a case with an unresolved source.
        with patch('clinical.record_copies.ArchivePackage.objects.filter') as lookup:
            lookup.return_value.order_by.return_value.first.return_value=None
            row=self.request()
        self.assertIsNone(row.items.get().package_id)
        self.assertEqual(row.state,'PENDING')
        self.verified(row);self.assertEqual(row.items.get().package_id,self.pkg.pk)

    def test_wrong_clinic_and_other_patient_visit_are_rejected(self):
        with self.assertRaises((PermissionDenied,RuleError)):
            self.do(self.patient_user,'SUBMIT',clinic=self.b.pk,visits=[self.v.pk],sections=['DOCUMENT'],purpose='申请其他门店资料')
        self.assertFalse(RecordCopyRequest.objects.exists())

    def test_empty_and_unknown_sections_do_not_expand_to_all_records(self):
        for groups in ([],['SECRET']):
            with self.assertRaises(RuleError):self.do(self.patient_user,'SUBMIT',clinic=self.a.pk,visits=[self.v.pk],sections=groups,purpose='复诊就医资料')

    def test_repeat_confirmation_creates_one_application(self):
        p=cmd.prepare(actor=self.patient_user,action='SUBMIT',fields=dict(clinic=self.a.pk,visits=[self.v.pk],sections=['DOCUMENT'],purpose='复诊就医资料'))
        a=cmd.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        b=cmd.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(a[0].pk,b[0].pk);self.assertTrue(b[1]);self.assertEqual(RecordCopyRequest.objects.count(),1)

    def test_material_duty_and_copy_review_duty_are_default_off(self):
        self.duty(self.front,'copy_verifier',False,grant_id=RoleAssignment.objects.get(user=self.front,role='FRONT_DESK',clinic=self.a).pk)
        self.ctx(self.front,'FRONT_DESK',self.a)
        with self.assertRaises(PermissionDenied):cmd.front(self.front)
        self.duty(self.reviewer,'copy_reviewer',False,clinic_id=self.a.pk)
        self.ctx(self.reviewer,'DENTIST')
        self.assertTrue(self.reviewer.clinicalreviewerappointment_set.get(clinic=self.a).can_review_archives)
        with self.assertRaises((PermissionDenied,RuleError)):
            cmd.review_authority(self.reviewer,self.request())

    def test_nonmedical_roles_and_original_author_cannot_approve(self):
        row=self.verified()
        for actor in (self.front,self.doc,self.manager,self.tech,self.patient_user):
            with self.subTest(actor=actor.pk),self.assertRaises((PermissionDenied,RuleError)):
                cmd.prepare(actor=actor,action='REVIEW',request_id=row.pk,fields=dict(decision='APPROVE',message='不具备独立医务审核职责'))
        self.assertEqual(RecordCopyRequest.objects.get().state,'REVIEW')

    def test_wrong_recipient_cannot_read_or_consume_ticket(self):
        row=self.ready_copy();token=self.claim(row)
        other=UserAccount.objects.create_user(username='copy_other',password='synthetic-only');PatientAccess.objects.create(user=other,patient=self.p2);self.ctx(other,'PATIENT')
        with self.assertRaises(PermissionDenied):cmd.pickup(actor=other,token=token)
        self.assertFalse(RecordCopyEvent.objects.filter(action='FILE_RESPONSE').exists())

    def test_revocation_blocks_old_preview_and_download_ticket(self):
        row=self.ready_copy();token=self.claim(row)
        p=cmd.prepare(actor=self.patient_user,action='CLAIM',request_id=row.pk)
        self.do(self.front,'REVOKE',row,message='领取人提出材料争议，停止后续领取。')
        for call in (lambda:cmd.pickup(actor=self.patient_user,token=token),lambda:cmd.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)):
            with self.assertRaises(RuleError):call()
        self.assertEqual(RecordCopyFile.objects.count(),1)

    def test_inactive_self_access_and_account_stop_pickup(self):
        row=self.ready_copy();token=self.claim(row)
        PatientAccess.objects.filter(user=self.patient_user).update(is_active=False)
        with self.assertRaises(PermissionDenied):cmd.pickup(actor=self.patient_user,token=token)
        self.assertFalse(RecordCopyEvent.objects.filter(action='FILE_RESPONSE').exists())

    def test_expired_pickup_is_visible_but_history_and_file_remain(self):
        row=self.ready_copy();token=self.claim(row)
        future=timezone.now()+timedelta(days=8)
        with patch('django.utils.timezone.now',return_value=future):
            self.assertFalse(data(row)['can_pickup'])
            with self.assertRaises(RuleError):cmd.pickup(actor=self.patient_user,token=token)
        self.assertEqual(RecordCopyFile.objects.count(),1)

    def test_changed_identity_or_review_duty_blocks_pickup(self):
        row=self.ready_copy();token=self.claim(row)
        self.duty(self.reviewer,'copy_reviewer',False,clinic_id=self.a.pk)
        with self.assertRaises(RuleError):cmd.pickup(actor=self.patient_user,token=token)

    def test_repeated_transport_records_one_response_without_changing_money(self):
        row=self.ready_copy();token=self.claim(row);before=self.money()
        a=cmd.pickup(actor=self.patient_user,token=token)[1];b=cmd.pickup(actor=self.patient_user,token=token)[1]
        self.assertEqual(a,b);self.assertEqual(RecordCopyEvent.objects.filter(action='FILE_RESPONSE').count(),1);self.assertEqual(before,self.money())

    def test_render_failure_can_retry_original_approved_scope(self):
        row=self.approved()
        with patch('clinical.copy_generation.render',side_effect=RuntimeError('PRIVATE_COPY_CONTENT')):result=gen.generate(row.pk)
        self.assertEqual(result['state'],'FAILED');self.assertFalse(RecordCopyFile.objects.exists())
        row.refresh_from_db();self.do(self.front,'RETRY',row);self.assertTrue(gen.generate(row.pk)['published']);self.assertEqual(RecordCopyFile.objects.count(),1)

    def test_scope_projection_omits_other_categories_and_material_references(self):
        row=self.do(self.patient_user,'SUBMIT',clinic=self.a.pk,visits=[self.v.pk],sections=['DOCUMENT'],purpose='本人病历文书留存')
        projected=packet(row);titles=[s['title'] for r in projected['records'] for s in r['sections']]
        self.assertNotIn('选定的已发布收费版本',titles)
        self.assertNotIn('proxy_versions',str(projected));self.assertNotIn('identity_reference',str(projected))

    def test_sql_file_event_scope_and_request_identity_are_retained(self):
        row=self.ready_copy();event=row.events.first();item=row.items.get()
        for action in (lambda:RecordCopyFile.objects.filter(request=row).update(pdf=b'changed'),
            lambda:RecordCopyEvent.objects.filter(pk=event.pk).delete(),lambda:RecordCopyItem.objects.filter(pk=item.pk).update(sections=['FEES']),
            lambda:RecordCopyRequest.objects.filter(pk=row.pk).update(purpose='silently replaced')):
            with self.assertRaises(DatabaseError),transaction.atomic():action()

    def test_concurrent_generation_publishes_one_file(self):
        row=self.approved();barrier=Barrier(2)
        original=gen.render
        def render(content):
            barrier.wait();return original(content)
        def worker():
            close_old_connections()
            try:return gen.generate(row.pk)
            finally:close_old_connections()
        with patch('clinical.copy_generation.render',side_effect=render):
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:worker(),range(2)))
        self.assertEqual(RecordCopyFile.objects.count(),1);self.assertEqual(sum(x['published'] for x in results),1)

    def test_http_account_token_is_required_and_front_has_no_pdf_access(self):
        row=self.ready_copy();client=WorkspaceClient();client.force_login(self.patient_user)
        response=client.get('/api/mini/v1/record-copies/');self.assertEqual(response.status_code,200)
        response=client.post('/api/mini/v1/record-copies/'+str(row.pk)+'/preview/',{'action':'CLAIM'})
        self.assertEqual(response.status_code,403)
        client.force_login(self.front)
        self.assertEqual(client.get('/clinical/record-copies/'+str(row.pk)+'/').status_code,200)
        response=client.get('/portal/record-copies/download/?ticket=invalid')
        self.assertEqual(response.status_code,403)

    def test_http_self_application_options_and_human_preview(self):
        client=WorkspaceClient();client.force_login(self.patient_user)
        self.assertEqual(client.get('/portal/record-copies/new/').status_code,200)
        self.assertEqual(client.get('/api/mini/v1/record-copies/options/').status_code,200)
        response=client.post('/portal/record-copies/new/',{'clinic':self.a.pk,'visits':[self.v.pk],'sections':['DOCUMENT'],'purpose':'本人病历复诊使用','account_token':client.current_token()})
        self.assertEqual(response.status_code,200);self.assertContains(response,'实际领取人');self.assertNotContains(response,'identity_reference')

    def test_written_proxy_gets_only_the_separately_verified_copy(self):
        from portal.policies import patient_access
        proxy,row=self.proxy();row=self.approved(row);gen.generate(row.pk);row.refresh_from_db()
        token=self.claim(row,proxy);self.assertTrue(cmd.pickup(actor=proxy,token=token)[1].startswith(b'%PDF-'))
        self.assertEqual(patient_access(proxy,self_only=True).patient_id,self.p2.pk)
        self.assertFalse(PatientAccess.objects.filter(user=proxy,patient=self.v.patient).exists())
        client=WorkspaceClient();client.force_login(proxy)
        self.assertEqual(client.get('/api/mini/v1/record-copies/'+str(row.pk)+'/').status_code,200)
        self.assertEqual(client.get('/clinical/archives/').status_code,403)

    def test_proxy_original_reference_required_and_not_shown_in_patient_projection(self):
        proxy,row=self.proxy()
        with self.assertRaises(RuleError):
            self.do(self.front,'VERIFY',row,decision='VERIFY',basis='IN_PERSON',identity_reference='COPY-ID',authority_reference='',purpose_checked=True,pickup_until=timezone.now()+timedelta(days=1),reviewer=self.reviewer.clinicalreviewerappointment_set.get(clinic=self.a).pk)
        self.verified(row)
        public=data(RecordCopyRequest.objects.get(pk=row.pk))
        self.assertNotIn('SYNTHETIC-COPY-AUTH',str(public));self.assertNotIn('SYNTHETIC-COPY-ID',str(public))

    def test_minor_guardian_copy_is_separately_verified(self):
        from datetime import date
        self.v.patient.date_of_birth=date(timezone.localdate().year-8,1,1);self.v.patient.save(update_fields=['date_of_birth'])
        proxy,row=self.proxy('GUARDIAN');row=self.approved(row);gen.generate(row.pk);row.refresh_from_db()
        self.assertTrue(cmd.pickup(actor=proxy,token=self.claim(row,proxy))[1].startswith(b'%PDF-'))

    def test_adult_cannot_be_passed_under_minor_guardian_basis(self):
        proxy,row=self.proxy('GUARDIAN')
        with self.assertRaises(RuleError):self.verified(row)
        row.refresh_from_db();self.assertEqual(row.state,'PENDING')

    def test_appointment_authority_does_not_allow_self_copy_of_delegated_patient(self):
        from portal.models import PatientRelationship,PatientAppointmentGrant
        proxy=UserAccount.objects.create_user(username='copy_appointment_only',password='synthetic-copy-only')
        relation=PatientRelationship.objects.create(clinic=self.a,patient=self.v.patient,related_name='合成联系人',kind='DELEGATE',delegate_user=proxy,state='VERIFIED',created_by=self.front)
        grant=PatientAppointmentGrant.objects.create(relationship=relation,valid_from=timezone.now()-timedelta(days=1),valid_until=timezone.now()+timedelta(days=1),created_by=self.front)
        self.ctx(proxy,'PATIENT');proxy._adc_workspace.patient_grant=grant;proxy._adc_workspace.save(update_fields=['patient_grant'])
        with self.assertRaises(PermissionDenied):
            self.do(proxy,'SUBMIT',clinic=self.a.pk,visits=[self.v.pk],sections=['DOCUMENT'],purpose='代约权限不能代替病历复制')
        self.assertFalse(RecordCopyRequest.objects.exists())

    def test_revoked_material_duty_invalidates_old_verification(self):
        row=self.request();fields=dict(decision='VERIFY',basis='IN_PERSON',identity_reference='COPY-ID',authority_reference='',purpose_checked=True,pickup_until=timezone.now()+timedelta(days=1),reviewer=self.reviewer.clinicalreviewerappointment_set.get(clinic=self.a).pk)
        p=cmd.prepare(actor=self.front,action='VERIFY',request_id=row.pk,fields=fields)
        self.duty(self.front,'copy_verifier',False,grant_id=RoleAssignment.objects.get(user=self.front,role='FRONT_DESK',clinic=self.a).pk)
        self.ctx(self.front,'FRONT_DESK',self.a)
        with self.assertRaises((PermissionDenied,RuleError)):cmd.confirm(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)

    def test_copied_file_stays_fixed_after_new_clinical_directory_values(self):
        row=self.ready_copy();before=bytes(row.file.pdf)
        from registry.models import TreatmentType
        TreatmentType.objects.filter(pk=self.item.pk).update(name='目录更新后名称')
        row.refresh_from_db();self.assertEqual(bytes(row.file.pdf),before)

    def test_concurrent_revocation_and_pickup_preserve_ordered_result(self):
        row=self.ready_copy();ticket=self.claim(row);barrier=Barrier(2)
        p=cmd.prepare(actor=self.front,action='REVOKE',request_id=row.pk,fields=dict(message='领取人材料争议停止新领取'))
        def worker(action):
            close_old_connections()
            try:
                barrier.wait()
                if action=='revoke':return cmd.confirm(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
                try:return cmd.pickup(actor=self.patient_user,token=ticket)
                except RuleError:return 'REJECTED_AFTER_REVOCATION'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,['revoke','pickup']))
        row.refresh_from_db();self.assertEqual(row.state,'REVOKED');self.assertLessEqual(row.events.filter(action='FILE_RESPONSE').count(),1)
        with self.assertRaises(RuleError):cmd.pickup(actor=self.patient_user,token=ticket)

    def test_native_authenticated_pdf_delivery_and_bearer_link_rejection(self):
        row=self.ready_copy();client=WorkspaceClient();client.force_login(self.patient_user)
        session=client.get('/api/mini/v1/session/').json()['data'];account=session['account_token']
        p=client.post('/api/mini/v1/record-copies/'+str(row.pk)+'/preview/',{'action':'CLAIM','account_token':account})
        self.assertEqual(p.status_code,200,p.content)
        response=client.post('/api/mini/v1/record-copies/confirm/',{'proposal_token':p.json()['data']['proposal_token'],'confirmed':'on','account_token':account})
        self.assertEqual(response.status_code,200,response.content)
        ticket=response.json()['data']['ticket'];url='/api/mini/v1/record-copies/download/?ticket='+ticket
        pdf=client.get(url);self.assertEqual(pdf.status_code,200);raw=b''.join(pdf.streaming_content)
        self.assertEqual(hashlib.sha256(raw).hexdigest(),row.file.sha256)
        self.assertIn('no-store',pdf['Cache-Control'])
        client.logout();response=client.get(url);self.assertEqual(response.status_code,401)
        self.assertNotIn(b'%PDF-',response.content)

    def test_identity_change_blocks_approval_but_allows_return_to_material_queue(self):
        row=self.verified();self.v.patient.name='合成身份补充更正';self.v.patient.save(update_fields=['name'])
        with self.assertRaises(RuleError):self.do(self.reviewer,'REVIEW',row,decision='APPROVE',message='不能沿用旧身份核对结果')
        self.do(self.reviewer,'REVIEW',row,decision='RETURN',message='身份资料发生变化，请前台重新核对原件和账号。')
        row.refresh_from_db();self.assertEqual(row.state,'NEED_INFO');self.assertFalse(RecordCopyFile.objects.exists())

    def test_copy_only_registered_account_can_pickup_without_patient_chart_access(self):
        from accounts.external_models import AccountIdentityEvent
        from portal.policies import patient_access
        user=UserAccount.objects.create_user(username='copy_account_only',password='synthetic-copy-only')
        AccountIdentityEvent.objects.create(user=user,operation_id=uuid.uuid4(),action='BIND',snapshot={'fixture':'registered-account-history-only-not-platform-proof'})
        self.ctx(user,'');user._adc_workspace.login_channel='PATIENT';user._adc_workspace.save(update_fields=['login_channel'])
        row=self.do(self.front,'REGISTER',patient_no=self.v.patient.patient_no,recipient_account=user.username,recipient_name='合成受托人',kind='WRITTEN',clinic=self.a.pk,visits=[self.v.pk],sections=['DOCUMENT'],purpose='本用途受托病历复制领取')
        row=self.approved(row);gen.generate(row.pk);row.refresh_from_db()
        self.assertTrue(cmd.pickup(actor=user,token=self.claim(row,user))[1].startswith(b'%PDF-'))
        self.assertFalse(PatientAccess.objects.filter(user=user).exists())
        with self.assertRaises(PermissionDenied):patient_access(user,self_only=True)
