"""SU-27/28 authored PG acceptance. Must run on PostgreSQL, never counted as pure checks.
Synthetic records only. Includes real transactions and two independent connections.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from threading import Barrier
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, close_old_connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent, Invoice
from registry.models import Clinic, Dentist, Qualification, DentistQualification
from registry.directory_services import (prepare_registration, prepare_association, confirm_directory_change,
    require_directory_actor, ALL_EVENTS, REGISTER_EVENTS, ASSOCIATION_EVENTS)
from registry.directory_forms import RegistrationForm
from scheduling.models import AvailabilitySlot, Visit
from tests.test_v04 import V04Fixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext

CLINIC = {'clinic_code':'CL_NEW','name':'合成新诊所','postal_address':'虚构新地址','supervisor_name':'合成主管',
          'phone':'0000123','email':'cnew@example.invalid','area_sqm':'123.45'}
DENTIST = {'employee_no':'DR_NEW','name':'合成新牙医','date_of_birth':'1990-01-02','home_address':'虚构新联系地址',
           'phone':'0000456','email':'dnew@example.invalid'}
QUAL = {'code':'Q_NEW','name':'合成资格类别'}

class DirectoryAcceptanceTests(V04Fixture, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.set_up_v04()
        self.tech._adc_workspace = WorkspaceContext.objects.create(user=self.tech,role='SYSADMIN',revision=1)
        self.tech2 = UserAccount.objects.create_user(username='tech_two',password='test-directory-other')
        RoleAssignment.objects.create(user=self.tech2,role='SYSADMIN',scope_kind='TECHNICAL')
        self.tech2._adc_workspace = WorkspaceContext.objects.create(user=self.tech2,role='SYSADMIN',revision=1)
        self.qual = Qualification.objects.create(code='Q_EXISTING',name='已存在的合成资格')
    def prepare(self,kind='dentist',actor=None,details=None):
        return prepare_registration(actor=actor or self.tech,kind=kind,
            details=details or {'clinic':CLINIC,'dentist':DENTIST,'qualification':QUAL}[kind],reason_code='SOURCE_RECORD')
    def commit(self,preview,actor=None,password=None,confirmed=True):
        actor=actor or self.tech
        return confirm_directory_change(actor=actor,proposal_token=preview.proposal_token,confirmed=confirmed,
            operator_password=password if password is not None else ('test-directory-other' if actor.pk==self.tech2.pk else 'test-only-pass-abc'))
    def link_preview(self,action='attach',reason=None,actor=None):
        return prepare_association(actor=actor or self.tech,dentist_id=self.d1.pk,qualification_id=self.qual.pk,
            action=action,reason_code=reason or ('CORRECT_LINK' if action=='withdraw' else 'SOURCE_RECORD'))
    def events(self):return AuditEvent.objects.filter(event_type__in=ALL_EVENTS)
    def counts(self):
        return (UserAccount.objects.count(),RoleAssignment.objects.count(),AvailabilitySlot.objects.count(),Visit.objects.count(),Invoice.objects.count())
    def test_preview_does_not_register(self):
        before=(Clinic.objects.count(),Dentist.objects.count(),Qualification.objects.count(),AuditEvent.objects.count())
        for kind in ('clinic','dentist','qualification'):self.prepare(kind)
        self.assertEqual(before,(Clinic.objects.count(),Dentist.objects.count(),Qualification.objects.count(),AuditEvent.objects.count()))
    def test_register_three_kinds(self):
        for kind,model in [('clinic',Clinic),('dentist',Dentist),('qualification',Qualification)]:
            with self.subTest(kind=kind):
                r=self.commit(self.prepare(kind));self.assertTrue(model.objects.get(pk=r.object_id).is_active);self.assertFalse(r.repeated)
                self.assertEqual(AuditEvent.objects.filter(event_type=REGISTER_EVENTS[kind]).count(),1)
    def test_new_dentist_has_no_auto_account_or_slot(self):
        before=self.counts();r=self.commit(self.prepare());self.assertEqual(self.counts(),before)
        self.assertFalse(UserAccount.objects.filter(dentist_id=r.object_id).exists())
    def test_new_clinic_has_no_auto_grant(self):
        before=self.counts();r=self.commit(self.prepare('clinic'));self.assertEqual(self.counts(),before)
        self.assertFalse(RoleAssignment.objects.filter(clinic_id=r.object_id).exists())
    def test_duplicate_registration_does_not_overwrite(self):
        r=self.commit(self.prepare())
        with self.assertRaises(RuleError):self.prepare(details=DENTIST|{'phone':'000-999'})
        self.assertEqual(Dentist.objects.get(pk=r.object_id).phone,'0000456')
    def test_inactive_duplicate_does_not_revive(self):
        r=self.commit(self.prepare());Dentist.objects.filter(pk=r.object_id).update(is_active=False)
        with self.assertRaises(RuleError):self.prepare()
        self.assertFalse(Dentist.objects.get(pk=r.object_id).is_active)
    def test_same_preview_replays_once(self):
        p=self.prepare();a=self.commit(p);b=self.commit(p)
        self.assertEqual(a.object_id,b.object_id);self.assertEqual(a.event_id,b.event_id);self.assertTrue(b.repeated)
        self.assertEqual(Dentist.objects.filter(employee_no='DR_NEW').count(),1)
    def test_two_previews_same_code_only_first_commits(self):
        a=self.prepare();b=self.prepare(actor=self.tech2);self.commit(a)
        with self.assertRaises(RuleError):self.commit(b,actor=self.tech2)
        self.assertEqual(self.events().count(),1)
    def test_explicit_confirmation_required(self):
        for confirmed in (False,1,'true'):
            with self.subTest(confirmed=confirmed),self.assertRaises(RuleError):self.commit(self.prepare(),confirmed=confirmed)
        self.assertEqual(self.events().count(),0)
    def test_wrong_operator_password(self):
        with self.assertRaises(ValidationError):self.commit(self.prepare(),password='wrong')
        self.assertFalse(Dentist.objects.filter(employee_no='DR_NEW').exists())
    def test_account_without_context_denied(self):
        del self.tech._adc_workspace
        with self.assertRaises(PermissionDenied):self.prepare()
    def test_superuser_without_technical_grant_denied(self):
        RoleAssignment.objects.filter(user=self.tech,role='SYSADMIN').update(is_active=False)
        with self.assertRaises(PermissionDenied):self.prepare()
    def test_current_frontdesk_identity_cannot_borrow_technical(self):
        RoleAssignment.objects.create(user=self.tech,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        self.tech._adc_workspace=WorkspaceContext.objects.create(user=self.tech,role='FRONT_DESK',clinic=self.a,revision=1)
        with self.assertRaises(PermissionDenied):self.prepare()
    def test_revoked_grant_blocks_confirmation(self):
        p=self.prepare();RoleAssignment.objects.filter(user=self.tech,role='SYSADMIN').update(is_active=False)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_suspended_actor_blocks_confirmation(self):
        p=self.prepare();UserAccount.objects.filter(pk=self.tech.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_context_revision_change_blocks_confirmation(self):
        p=self.prepare();WorkspaceContext.objects.filter(pk=self.tech._adc_workspace.pk).update(revision=2)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_old_token_cannot_move_to_new_context(self):
        p=self.prepare();self.tech._adc_workspace=WorkspaceContext.objects.create(user=self.tech,role='SYSADMIN',revision=1)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_other_actor_cannot_confirm(self):
        p=self.prepare()
        with self.assertRaises(PermissionDenied):self.commit(p,actor=self.tech2)
    def test_tampered_signature_denied(self):
        p=self.prepare()
        with self.assertRaises(RuleError):confirm_directory_change(actor=self.tech,proposal_token=p.proposal_token+'tamper',operator_password='test-only-pass-abc',confirmed=True)
    def test_expired_signature_denied(self):
        p=self.prepare()
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1000):
            with self.assertRaises(RuleError):self.commit(p)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_direct_write_denied(self):
        with self.assertRaises(PermissionDenied):self.commit(self.prepare())
        self.assertEqual(self.events().count(),0)
    def test_model_email_validator_is_used(self):
        with self.assertRaises(ValidationError):self.prepare(details=DENTIST|{'email':'not-email'})
    def test_future_dob_rejected(self):
        with self.assertRaises(RuleError):self.prepare(details=DENTIST|{'date_of_birth':(timezone.localdate()+timedelta(days=1)).isoformat()})
    def test_extra_unauthorized_field_rejected(self):
        with self.assertRaises(RuleError):self.prepare(details=DENTIST|{'is_active':False})
    def test_bad_area_rejected_in_form(self):
        form=RegistrationForm(CLINIC|{'area_sqm':'-1','reason_code':'SOURCE_RECORD'},kind='clinic');self.assertFalse(form.is_valid())
    def test_raw_personal_values_not_in_audit(self):
        self.commit(self.prepare());event=self.events().get();raw=json.dumps(event.change_summary,ensure_ascii=False)+event.reason
        for value in (DENTIST['phone'],DENTIST['email'],DENTIST['home_address'],DENTIST['date_of_birth']):self.assertNotIn(value,raw)
    def test_audit_failure_rolls_back_registration(self):
        p=self.prepare()
        with patch('registry.directory_services.emit',side_effect=RuntimeError('synthetic audit error')):
            with self.assertRaises(RuntimeError):self.commit(p)
        self.assertFalse(Dentist.objects.filter(employee_no='DR_NEW').exists());self.assertEqual(self.events().count(),0)
    def test_association_preview_does_not_write(self):
        self.link_preview();self.assertEqual(DentistQualification.objects.count(),0);self.assertEqual(self.events().count(),0)
    def test_association_create(self):
        r=self.commit(self.link_preview());self.assertEqual(r.object_id,self.d1.pk)
        self.assertTrue(DentistQualification.objects.get(dentist=self.d1,qualification=self.qual).is_active)
    def test_association_duplicate_denied(self):
        self.commit(self.link_preview())
        with self.assertRaises(RuleError):self.link_preview()
    def test_association_withdraw_preserves_row(self):
        before=self.counts();self.commit(self.link_preview());link=DentistQualification.objects.get()
        self.commit(self.link_preview('withdraw'));link.refresh_from_db()
        self.assertFalse(link.is_active);self.assertEqual(DentistQualification.objects.count(),1);self.assertEqual(before,self.counts())
    def test_association_restore_keeps_id_and_notes(self):
        link=DentistQualification.objects.create(dentist=self.d1,qualification=self.qual,notes='旧合成记录',is_active=False)
        self.commit(self.link_preview(reason='RESTORE_LINK'));link.refresh_from_db()
        self.assertTrue(link.is_active);self.assertEqual(link.notes,'旧合成记录');self.assertEqual(DentistQualification.objects.count(),1)
    def test_restore_requires_restore_reason(self):
        DentistQualification.objects.create(dentist=self.d1,qualification=self.qual,is_active=False)
        with self.assertRaises(RuleError):self.link_preview()
    def test_inactive_qualification_blocks_attach(self):
        self.qual.is_active=False;self.qual.save()
        with self.assertRaises(RuleError):self.link_preview()
    def test_inactive_dentist_blocks_attach(self):
        self.d1.is_active=False;self.d1.save()
        with self.assertRaises(RuleError):self.link_preview()
    def test_withdraw_possible_for_inactive_qualification(self):
        self.commit(self.link_preview());self.qual.is_active=False;self.qual.save()
        self.commit(self.link_preview('withdraw'));self.assertFalse(DentistQualification.objects.get().is_active)
    def test_association_state_changed_after_preview(self):
        p=self.link_preview();self.qual.name='后来变更';self.qual.save()
        with self.assertRaises(RuleError):self.commit(p)
        self.assertEqual(DentistQualification.objects.count(),0)
    def test_association_aba_invalidates_old_preview(self):
        self.commit(self.link_preview());old=self.link_preview('withdraw')
        self.commit(self.link_preview('withdraw',actor=self.tech2),actor=self.tech2)
        self.commit(self.link_preview(actor=self.tech2,reason='RESTORE_LINK'),actor=self.tech2)
        with self.assertRaises(RuleError):self.commit(old)
        self.assertTrue(DentistQualification.objects.get().is_active)
    def test_association_replay_does_not_undo_later_withdrawal(self):
        p=self.link_preview();a=self.commit(p);self.commit(self.link_preview('withdraw'))
        b=self.commit(p);self.assertTrue(b.repeated);self.assertEqual(a.event_id,b.event_id)
        self.assertFalse(DentistQualification.objects.get().is_active)
    def test_association_audit_failure_rolls_back(self):
        p=self.link_preview()
        with patch('registry.directory_services.emit',side_effect=RuntimeError('synthetic audit fault')):
            with self.assertRaises(RuntimeError):self.commit(p)
        self.assertEqual(DentistQualification.objects.count(),0)
    def test_existing_bill_header_unchanged(self):
        visit=self.arrived();invoice=self.finish(visit,'NO_TREATMENT','合成无治疗说明')
        version=invoice.current_record_version;before=version.billing_header_snapshot.copy()
        self.commit(self.prepare('clinic'));self.commit(self.prepare());self.commit(self.link_preview())
        version.refresh_from_db();self.assertEqual(version.billing_header_snapshot,before)
    def test_http_csrf_required(self):
        client=WorkspaceClient(enforce_csrf_checks=True);client.force_login(self.tech)
        self.assertEqual(client.post(reverse('directory_create',args=['dentist']),{}).status_code,403)
    def test_http_create_preview_confirm(self):
        self.client.force_login(self.tech)
        response=self.client.post(reverse('directory_create',args=['dentist']),DENTIST|{'reason_code':'SOURCE_RECORD'})
        self.assertEqual(response.status_code,200);self.assertContains(response,'尚未保存');self.assertFalse(Dentist.objects.filter(employee_no='DR_NEW').exists())
        token=response.context['form']['proposal_token'].value()
        result=self.client.post(reverse('directory_confirm'),{'proposal_token':token,'operator_password':'test-only-pass-abc','confirmed':'on'})
        self.assertEqual(result.status_code,302);self.assertTrue(Dentist.objects.filter(employee_no='DR_NEW').exists())
    def test_http_confirm_has_no_get_equivalent(self):
        self.client.force_login(self.tech);self.assertEqual(self.client.get(reverse('directory_confirm')).status_code,405)
    def test_http_private_page_not_cached(self):
        self.client.force_login(self.tech);response=self.client.get(reverse('directory_detail',args=['dentist',self.d1.pk]))
        self.assertEqual(response.status_code,200);self.assertIn('no-store',response['Cache-Control'])
    def test_http_patient_and_manager_cannot_read_directory(self):
        for actor in (self.pa,self.manager):
            self.client.force_login(actor);self.assertEqual(self.client.get(reverse('directory_home')).status_code,403)
    def test_http_list_omits_home_address_and_birth_date(self):
        self.d1.home_address='必须隐藏的联系地址';self.d1.save()
        self.client.force_login(self.tech);r=self.client.get(reverse('directory_list',args=['dentist']))
        self.assertNotContains(r,'必须隐藏的联系地址');self.assertNotContains(r,'1990-01-01')
    @override_settings(ADC_READ_ONLY=True)
    def test_http_readonly_hides_creation_and_rejects_post(self):
        self.client.force_login(self.tech);r=self.client.get(reverse('directory_list',args=['dentist']))
        self.assertEqual(r.status_code,200);self.assertNotContains(r,reverse('directory_create',args=['dentist']))
        self.assertEqual(self.client.post(reverse('directory_create',args=['dentist']),DENTIST).status_code,403)
    def test_http_qualification_link_flow(self):
        self.client.force_login(self.tech)
        r=self.client.post(reverse('directory_attach',args=[self.d1.pk]),{'qualification':self.qual.pk,'reason_code':'SOURCE_RECORD'})
        self.assertEqual(r.status_code,200);self.assertContains(r,'尚未保存')
        r=self.client.post(reverse('directory_confirm'),{'proposal_token':r.context['form']['proposal_token'].value(),'operator_password':'test-only-pass-abc','confirmed':'on'})
        self.assertEqual(r.status_code,302);self.assertEqual(DentistQualification.objects.count(),1)
    def test_http_unknown_type_does_not_expose_other_models(self):
        self.client.force_login(self.tech);self.assertEqual(self.client.get(reverse('directory_list',args=['patient'])).status_code,404)
    def test_http_escape_untrusted_name(self):
        self.qual.name='<script>BAD</script>';self.qual.save()
        self.client.force_login(self.tech);r=self.client.get(reverse('directory_detail',args=['qualification',self.qual.pk]))
        self.assertNotContains(r,'<script>BAD</script>');self.assertContains(r,'&lt;script&gt;BAD&lt;/script&gt;')
    def test_http_database_error_uses_uncertain_result_message(self):
        from django.db import OperationalError
        self.client.force_login(self.tech)
        with patch('registry.directory_views.confirm_directory_change',side_effect=OperationalError('synthetic')):
            r=self.client.post(reverse('directory_confirm'),{'proposal_token':'dummy','operator_password':'pass','confirmed':'on'})
        self.assertEqual(r.status_code,503);self.assertContains(r,'不代表此前一定没有保存',status_code=503)
    def _race(self,items):
        barrier=Barrier(2)
        def worker(actor_id,ctx_id,preview,password):
            close_old_connections()
            try:
                with connection.cursor() as c:c.execute("SET lock_timeout='8s'")
                actor=UserAccount.objects.get(pk=actor_id);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctx_id)
                barrier.wait(timeout=8)
                try:
                    result=confirm_directory_change(actor=actor,proposal_token=preview.proposal_token,operator_password=password,confirmed=True)
                    return 'repeat' if result.repeated else 'ok'
                except RuleError:return 'conflict'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,*row) for row in items]
            return sorted(f.result(timeout=25) for f in futures)
    def test_concurrent_same_code_one_record(self):
        a=self.prepare();b=self.prepare(actor=self.tech2)
        result=self._race([(self.tech.pk,self.tech._adc_workspace.pk,a,'test-only-pass-abc'),
                           (self.tech2.pk,self.tech2._adc_workspace.pk,b,'test-directory-other')])
        self.assertEqual(result,['conflict','ok']);self.assertEqual(Dentist.objects.filter(employee_no='DR_NEW').count(),1)
    def test_concurrent_same_operation_one_event(self):
        p=self.prepare();row=(self.tech.pk,self.tech._adc_workspace.pk,p,'test-only-pass-abc')
        self.assertEqual(self._race([row,row]),['ok','repeat']);self.assertEqual(self.events().count(),1)
    def test_concurrent_same_association_one_link(self):
        a=self.link_preview();b=self.link_preview(actor=self.tech2)
        self.assertEqual(self._race([(self.tech.pk,self.tech._adc_workspace.pk,a,'test-only-pass-abc'),
            (self.tech2.pk,self.tech2._adc_workspace.pk,b,'test-directory-other')]),['conflict','ok'])
        self.assertEqual(DentistQualification.objects.count(),1)
