
"""Authored SU-26 PostgreSQL/HTTP tests. Run through compose.verify.yaml, not SQLite."""
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
from care.models import AuditEvent, Invoice, VisitRecordVersion
from patients.contact_rules import CONTACT_FIELDS
from patients.contact_services import (contact_editor, prepare_contact_change, confirm_contact_change,
                                     STATE_SALT, PROPOSAL_SALT, EVENT_TYPE)
from patients.models import Patient
from tests.test_v04 import V04Fixture
from workspaces.models import WorkspaceContext

class ContactChangeTests(V04Fixture, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.set_up_v04()
        self.attach_context(self.front,self.a)
        self.attach_context(self.front2,self.a)
    def attach_context(self,user,clinic,role='FRONT_DESK'):
        user._adc_workspace=WorkspaceContext.objects.create(user=user,role=role,clinic=clinic,revision=1)
        return user._adc_workspace
    def values(self,patient=None):
        p=patient or self.p1;p.refresh_from_db();return {k:getattr(p,k) for k in CONTACT_FIELDS}
    def proposal(self,actor=None,patient=None,values=None):
        actor=actor or self.front;patient=patient or self.p1
        editor=contact_editor(actor=actor,patient_id=patient.pk)
        return prepare_contact_change(actor=actor,patient_id=patient.pk,state_token=editor.state_token,
            details=values or (self.values(patient)|{'phone':'000-1111'}),reason_code='PATIENT_UPDATE')
    def confirm(self,preview,actor=None,patient=None,confirmed=True):
        return confirm_contact_change(actor=actor or self.front,patient_id=(patient or self.p1).pk,
            proposal_token=preview.proposal_token,confirmed=confirmed)
    def events(self):return AuditEvent.objects.filter(event_type=EVENT_TYPE)
    def test_editor_and_preview_do_not_write(self):
        before=self.values();count=AuditEvent.objects.count();self.proposal()
        self.assertEqual(self.values(),before);self.assertEqual(AuditEvent.objects.count(),count)
    def test_confirmation_changes_only_contacts(self):
        before=Patient.objects.filter(pk=self.p1.pk).values().get();res=self.confirm(self.proposal())
        after=Patient.objects.filter(pk=self.p1.pk).values().get()
        self.assertEqual(after['phone'],'000-1111');self.assertFalse(res.repeated)
        self.assertEqual({k:v for k,v in before.items() if k not in CONTACT_FIELDS},
                         {k:v for k,v in after.items() if k not in CONTACT_FIELDS})
        self.assertEqual(self.events().count(),1)
    def test_explicit_confirmation_required_in_command(self):
        preview=self.proposal()
        with self.assertRaises(RuleError):self.confirm(preview,confirmed=False)
        self.assertEqual(self.events().count(),0)
    def test_noop_rejected_without_audit(self):
        with self.assertRaises(RuleError):self.proposal(values=self.values())
        self.assertEqual(self.events().count(),0)
    def test_replay_returns_one_event(self):
        p=self.proposal();a=self.confirm(p);b=self.confirm(p)
        self.assertEqual(a.event_id,b.event_id);self.assertTrue(b.repeated);self.assertEqual(self.events().count(),1)
    def test_replay_does_not_undo_later_change(self):
        old=self.proposal();first=self.confirm(old)
        self.confirm(self.proposal(values=self.values()|{'phone':'000-2222'}))
        repeat=self.confirm(old);self.assertTrue(repeat.repeated);self.assertEqual(repeat.event_id,first.event_id)
        self.assertEqual(self.values()['phone'],'000-2222');self.assertEqual(self.events().count(),2)
    def test_other_actor_cannot_replay_token(self):
        p=self.proposal()
        with self.assertRaises(PermissionDenied):self.confirm(p,actor=self.front2)
        self.assertEqual(self.events().count(),0)
    def test_other_target_rejected(self):
        self.p2.created_in_clinic=self.a;self.p2.save(update_fields=['created_in_clinic'])
        p=self.proposal()
        with self.assertRaises(PermissionDenied):self.confirm(p,patient=self.p2)
    def test_unassociated_clinic_cannot_read_or_write(self):
        with self.assertRaises(PermissionDenied):contact_editor(actor=self.front,patient_id=self.p2.pk)
    def test_cross_clinic_visit_creates_association_not_borrowed_role(self):
        self.book(patient_no=self.p2.patient_no)
        p=self.proposal(patient=self.p2);self.confirm(p,patient=self.p2)
        self.assertEqual(self.values(self.p2)['phone'],'000-1111')
    def test_doctor_cannot_edit_even_if_can_read(self):
        self.attach_context(self.doctor,None,'DENTIST')
        with self.assertRaises(PermissionDenied):contact_editor(actor=self.doctor,patient_id=self.p1.pk)
    def test_superuser_not_business_bypass(self):
        self.attach_context(self.tech,None,'SYSADMIN')
        with self.assertRaises(PermissionDenied):contact_editor(actor=self.tech,patient_id=self.p1.pk)
    def test_no_context_is_not_global_permission(self):
        del self.front._adc_workspace
        with self.assertRaises(PermissionDenied):contact_editor(actor=self.front,patient_id=self.p1.pk)
    def test_revoked_grant_blocks_confirm(self):
        p=self.proposal();RoleAssignment.objects.filter(user=self.front,role='FRONT_DESK',clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.confirm(p)
        self.assertEqual(self.events().count(),0)
    def test_stale_workspace_blocks_confirm(self):
        p=self.proposal();WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(clinic=self.b,revision=2)
        with self.assertRaises(PermissionDenied):self.confirm(p)
    def test_inactive_patient_blocks_confirm(self):
        p=self.proposal();Patient.objects.filter(pk=self.p1.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.confirm(p)
    def test_stale_data_between_edit_and_preview(self):
        editor=contact_editor(actor=self.front,patient_id=self.p1.pk)
        self.confirm(self.proposal(actor=self.front2))
        with self.assertRaises(RuleError):prepare_contact_change(actor=self.front,patient_id=self.p1.pk,
            state_token=editor.state_token,details=self.values()|{'phone':'000-2222'},reason_code='PATIENT_UPDATE')
    def test_stale_data_between_preview_and_confirm(self):
        p=self.proposal();self.confirm(self.proposal(actor=self.front2,values=self.values()|{'phone':'000-2222'}),actor=self.front2)
        with self.assertRaises(RuleError):self.confirm(p)
        self.assertEqual(self.values()['phone'],'000-2222')
    def test_aba_restore_does_not_revive_old_preview(self):
        values=self.values();old=self.proposal()
        self.confirm(self.proposal(actor=self.front2),actor=self.front2)
        self.confirm(self.proposal(actor=self.front2,values=values),actor=self.front2)
        with self.assertRaises(RuleError):self.confirm(old)
    def test_token_tampering(self):
        p=self.proposal()
        with self.assertRaises(RuleError):confirm_contact_change(actor=self.front,patient_id=self.p1.pk,
            proposal_token=p.proposal_token+'x',confirmed=True)
    def test_expired_preview(self):
        p=self.proposal()
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1000):
            with self.assertRaises(RuleError):self.confirm(p)
    def test_email_validation_in_command(self):
        with self.assertRaises(ValidationError):self.proposal(values=self.values()|{'email':'not-email'})
    def test_unexpected_field_rejected_in_command(self):
        with self.assertRaises(RuleError):self.proposal(values=self.values()|{'name':'偷偷改名'})
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_blocks_direct_command(self):
        with self.assertRaises(PermissionDenied):self.proposal()
    def test_audit_failure_rolls_back_contacts(self):
        before=self.values();p=self.proposal()
        with patch('patients.contact_services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.confirm(p)
        self.assertEqual(self.values(),before);self.assertEqual(self.events().count(),0)
    def test_audit_omits_contact_values(self):
        self.confirm(self.proposal());a=self.events().get()
        self.assertNotIn('000-1111',json.dumps(a.change_summary));self.assertNotIn('000-1111',a.reason)
        self.assertEqual(a.change_summary['fields'],['phone'])
    def test_published_invoice_header_unchanged(self):
        v=self.arrived();inv=self.finish(v,'NO_TREATMENT','合成数据延期就诊')
        version=inv.current_record_version;before=version.billing_header_snapshot.copy()
        self.confirm(self.proposal(values=self.values()|{'billing_address':'新的虚构账单地址'}))
        version.refresh_from_db();self.assertEqual(version.billing_header_snapshot,before)
        self.assertEqual(Invoice.objects.count(),1)
    def test_csrf_required(self):
        from tests.workspace_client import WorkspaceClient
        client=WorkspaceClient(enforce_csrf_checks=True);client.force_login(self.front)
        res=client.post(reverse('patient_contact_edit',args=[self.p1.pk]),{})
        self.assertEqual(res.status_code,403);self.assertEqual(self.events().count(),0)
    def test_http_preview_then_confirmation(self):
        self.client.force_login(self.front)
        page=self.client.get(reverse('patient_contact_edit',args=[self.p1.pk]));self.assertEqual(page.status_code,200)
        form=page.context['form'];body=self.values()|{'state_token':form['state_token'].value(),'reason_code':'ENTRY_CORRECTION','phone':'000-4444'}
        page=self.client.post(reverse('patient_contact_edit',args=[self.p1.pk]),body)
        self.assertEqual(page.status_code,200);self.assertContains(page,'尚未保存');self.assertEqual(self.values()['phone'],'000')
        result=self.client.post(reverse('patient_contact_confirm',args=[self.p1.pk]),{'proposal_token':page.context['form']['proposal_token'].value(),'confirmed':'on'})
        self.assertEqual(result.status_code,302);self.assertEqual(self.values()['phone'],'000-4444')
    def test_http_write_has_no_get_equivalent(self):
        self.client.force_login(self.front);self.assertEqual(self.client.get(reverse('patient_contact_confirm',args=[self.p1.pk])).status_code,405)
    def test_http_cache_control(self):
        self.client.force_login(self.front);res=self.client.get(reverse('patient_contact_edit',args=[self.p1.pk]))
        self.assertIn('no-store',res['Cache-Control'])
    def test_cross_role_url_rejected(self):
        self.client.force_login(self.doctor);self.assertEqual(self.client.get(reverse('patient_contact_edit',args=[self.p1.pk])).status_code,403)
    def test_race_of_two_previews_only_one_applies(self):
        a=self.proposal();b=self.proposal(actor=self.front2,values=self.values()|{'phone':'000-2222'})
        barrier=Barrier(2)
        def worker(uid,cid,token):
            close_old_connections()
            try:
                with connection.cursor() as c:c.execute("SET lock_timeout='8s'")
                actor=UserAccount.objects.get(pk=uid);actor._adc_workspace=WorkspaceContext.objects.get(pk=cid)
                barrier.wait(timeout=8)
                try:
                    confirm_contact_change(actor=actor,patient_id=self.p1.pk,proposal_token=token,confirmed=True);return 'ok'
                except RuleError:return 'conflict'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,self.front.pk,self.front._adc_workspace.pk,a.proposal_token),
                     pool.submit(worker,self.front2.pk,self.front2._adc_workspace.pk,b.proposal_token)]
            outcomes=[f.result(timeout=25) for f in futures]
        self.assertEqual(sorted(outcomes),['conflict','ok']);self.assertEqual(self.events().count(),1)
