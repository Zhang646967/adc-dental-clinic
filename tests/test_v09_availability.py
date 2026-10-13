"""SU-29/30 integration tests for PostgreSQL. AUTHORED, not pure-check evidence.
No mock ORM, middleware bypass or SQLite replacement. Failure injection is scoped
only to the audit call. Race tests use independent DB connections.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import connection, close_old_connections, DatabaseError
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent, Invoice
from coordination.models import WaitRequest, WaitOffer, SchedulePlan
from coordination.services import publish_plan
from registry.models import Dentist
from scheduling.models import AvailabilitySlot, Visit
from scheduling.services import create_appointment, change_appointment, create_slot
from scheduling.availability_services import (EVENTS, inspect_availability,
    prepare_availability_change, confirm_availability_change)
from scheduling.availability_forms import SlotChangeForm
from tests.fixtures import FixtureMixin
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext

class AvailabilityAcceptanceTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.make_fixture()
        self.manager._adc_workspace=WorkspaceContext.objects.create(user=self.manager,role='MANAGER',clinic=self.a,revision=1)
        self.manager2=UserAccount.objects.create_user(username='manager_other',password='test-manager-other')
        RoleAssignment.objects.create(user=self.manager2,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        self.manager2._adc_workspace=WorkspaceContext.objects.create(user=self.manager2,role='MANAGER',clinic=self.a,revision=1)
    def prepare(self,action='deactivate',actor=None,slot=None,start=None,end=None):
        actor=actor or self.manager;slot=slot or self.slot1
        _,token=inspect_availability(actor=actor,slot_id=slot.pk)
        return prepare_availability_change(actor=actor,slot_id=slot.pk,state_token=token,action=action,reason_code='PLAN_CHANGED',
            start=start if start is not None else self.t+timedelta(hours=5) if action=='replace' else None,
            end=end if end is not None else self.t+timedelta(hours=7) if action=='replace' else None)
    def commit(self,preview,actor=None,confirmed=True):
        return confirm_availability_change(actor=actor or self.manager,slot_id=preview.slot_id,
            proposal_token=preview.proposal_token,confirmed=confirmed)
    def maintenance_events(self):return AuditEvent.objects.filter(event_type__in=EVENTS)
    def new_plan(self):
        e=WaitRequest.objects.create(patient=self.p1,clinic=self.a,earliest=self.t,latest=self.t+timedelta(hours=4),created_by=self.front,state='WAITING')
        return SchedulePlan.objects.create(clinic=self.a,created_by=self.manager2,suggestions=[{
            'request_id':e.pk,'request_revision':e.revision,'slot_id':self.slot1.pk,
            'start':self.t.isoformat(),'end':(self.t+timedelta(minutes=30)).isoformat()}])
    def new_offer(self,expired=False):
        plan=self.new_plan();e=WaitRequest.objects.get(pk=plan.suggestions[0]['request_id']);e.state='OFFERED';e.save(update_fields=['state'])
        return WaitOffer.objects.create(request=e,plan=plan,slot=self.slot1,starts_at=self.t,ends_at=self.t+timedelta(minutes=30),
            expires_at=timezone.now()+timedelta(minutes=-1 if expired else 10))
    def client_manager(self,csrf=False):
        client=WorkspaceClient(enforce_csrf_checks=csrf);client.force_login(self.manager);return client
    def test_inspect_and_preview_make_no_business_writes(self):
        before=(AvailabilitySlot.objects.count(),AuditEvent.objects.count(),Visit.objects.count(),WaitOffer.objects.count())
        self.prepare();self.prepare('replace')
        self.assertEqual(before,(AvailabilitySlot.objects.count(),AuditEvent.objects.count(),Visit.objects.count(),WaitOffer.objects.count()))
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active)
    def test_stop_preserves_original_times_and_row(self):
        old=(self.slot1.starts_at,self.slot1.ends_at,self.slot1.dentist_id,self.slot1.clinic_id)
        r=self.commit(self.prepare());self.slot1.refresh_from_db()
        self.assertFalse(self.slot1.is_active);self.assertIsNone(r.replacement_id)
        self.assertEqual(old,(self.slot1.starts_at,self.slot1.ends_at,self.slot1.dentist_id,self.slot1.clinic_id))
        self.assertEqual(self.maintenance_events().count(),1)
    def test_replacement_has_new_id_same_clinic_and_dentist(self):
        r=self.commit(self.prepare('replace'));s=AvailabilitySlot.objects.get(pk=r.replacement_id)
        self.assertNotEqual(s.pk,self.slot1.pk);self.assertEqual((s.clinic_id,s.dentist_id),(self.a.pk,self.d1.pk))
        self.assertEqual(s.starts_at,self.t+timedelta(hours=5));self.assertTrue(s.is_active)
        self.slot1.refresh_from_db();self.assertFalse(self.slot1.is_active);self.assertEqual(self.slot1.starts_at,self.t)
    def test_replacement_can_overlap_its_old_interval(self):
        r=self.commit(self.prepare('replace',start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=3)))
        self.assertTrue(AvailabilitySlot.objects.get(pk=r.replacement_id).is_active)
    def test_unchanged_interval_not_replaced(self):
        with self.assertRaises(RuleError):self.prepare('replace',start=self.slot1.starts_at,end=self.slot1.ends_at)
    def test_schedule_booked_blocks_maintenance(self):
        self.book();snap,_=inspect_availability(actor=self.manager,slot_id=self.slot1.pk)
        self.assertEqual(snap.impact.blocking_visits,1)
        with self.assertRaises(RuleError):self.prepare()
    def test_checked_in_visit_blocks(self):
        v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=v.lock_version,action='check_in')
        with self.assertRaises(RuleError):self.prepare('replace')
    def test_cancelled_history_stays_on_old_slot(self):
        v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=v.lock_version,action='cancel',reason='合成取消',party='PATIENT')
        r=self.commit(self.prepare('replace'));v.refresh_from_db()
        self.assertEqual(v.availability_slot_id,self.slot1.pk);self.assertEqual(v.scheduled_start,self.t);self.assertEqual(v.status,'CANCELLED')
        self.assertEqual(Visit.objects.filter(availability_slot_id=r.replacement_id).count(),0)
    def test_valid_hold_blocks_even_without_visit(self):
        self.new_offer()
        with self.assertRaises(RuleError):self.prepare()
        self.assertEqual(Visit.objects.count(),0)
    def test_expired_hold_does_not_block_or_get_rewritten(self):
        o=self.new_offer(expired=True);r=self.commit(self.prepare());o.refresh_from_db();o.request.refresh_from_db()
        self.assertEqual(o.state,'PENDING');self.assertEqual(o.request.state,'OFFERED');self.assertIsNone(o.visit_id)
        self.assertIsNone(r.replacement_id)
    def test_draft_does_not_reserve_but_publish_after_stop_rejected(self):
        plan=self.new_plan();self.commit(self.prepare())
        with self.assertRaises(RuleError):publish_plan(actor=self.manager2,plan_id=plan.pk)
        self.assertEqual(WaitOffer.objects.count(),0);plan.refresh_from_db();self.assertEqual(plan.state,'DRAFT')
    def test_booking_after_preview_invalidates_confirmation(self):
        p=self.prepare();self.book()
        with self.assertRaises(RuleError):self.commit(p)
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active)
    def test_new_offer_after_preview_invalidates_confirmation(self):
        p=self.prepare();self.new_offer()
        with self.assertRaises(RuleError):self.commit(p)
        self.assertEqual(self.maintenance_events().count(),0)
    def test_booking_created_then_cancelled_still_invalidates_old_preview(self):
        p=self.prepare();v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',reason='合成取消',party='PATIENT')
        with self.assertRaises(RuleError):self.commit(p)
    def test_slot_audit_cursor_prevents_aba_old_preview(self):
        p=self.prepare()
        AuditEvent.objects.create(actor=self.manager2,event_type='SLOT_DEACTIVATED',subject_type='availabilityslot',
            subject_key=str(self.slot1.pk),occurred_at=timezone.now(),change_summary={'synthetic':'audit-cursor-changed'})
        with self.assertRaises(RuleError):self.commit(p)
    def test_time_passage_rechecks_original_start(self):
        p=self.prepare()
        with patch('scheduling.availability_services.timezone.now',return_value=self.t):
            with self.assertRaises(RuleError):self.commit(p)
    def test_new_begin_expired_after_preview_is_rejected(self):
        p=self.prepare('replace',start=timezone.now().replace(second=0,microsecond=0)+timedelta(minutes=3),
                       end=timezone.now().replace(second=0,microsecond=0)+timedelta(minutes=30))
        with patch('scheduling.availability_services.timezone.now',return_value=timezone.now()+timedelta(minutes=5)):
            with self.assertRaises(RuleError):self.commit(p)
    def test_other_clinic_target_denied(self):
        with self.assertRaises(PermissionDenied):inspect_availability(actor=self.manager,slot_id=self.slot2.pk)
    def test_zero_or_oversized_slot_id_returns_permission_failure(self):
        for slot_id in (0, 2**63):
            with self.subTest(slot_id=slot_id),self.assertRaises(PermissionDenied):
                inspect_availability(actor=self.manager,slot_id=slot_id)
    def test_missing_context_denied(self):
        del self.manager._adc_workspace
        with self.assertRaises(PermissionDenied):self.prepare()
    def test_assigned_manager_role_not_enough_while_active_frontdesk(self):
        RoleAssignment.objects.create(user=self.manager,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        self.manager._adc_workspace=WorkspaceContext.objects.create(user=self.manager,role='FRONT_DESK',clinic=self.a,revision=1)
        with self.assertRaises(PermissionDenied):self.prepare()
    def test_superuser_has_no_business_bypass(self):
        self.tech._adc_workspace=WorkspaceContext.objects.create(user=self.tech,role='SYSADMIN',revision=1)
        with self.assertRaises(PermissionDenied):self.prepare(actor=self.tech)
    def test_revoked_role_rejected_at_confirm(self):
        p=self.prepare();RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_suspended_account_rejected_at_confirm(self):
        p=self.prepare();UserAccount.objects.filter(pk=self.manager.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_changed_workspace_revision_rejected(self):
        p=self.prepare();WorkspaceContext.objects.filter(pk=self.manager._adc_workspace.pk).update(revision=2)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_other_manager_cannot_replay_someones_token(self):
        with self.assertRaises(PermissionDenied):self.commit(self.prepare(),actor=self.manager2)
    def test_token_from_other_slot_rejected(self):
        p=self.prepare()
        with self.assertRaises(PermissionDenied):confirm_availability_change(actor=self.manager,slot_id=self.slot2.pk,proposal_token=p.proposal_token,confirmed=True)
    def test_explicit_true_confirmation_required(self):
        p=self.prepare()
        for x in (False,'true',1,None):
            with self.subTest(x=x),self.assertRaises(RuleError):self.commit(p,confirmed=x)
    def test_token_tampering_rejected(self):
        p=self.prepare()
        with self.assertRaises(RuleError):confirm_availability_change(actor=self.manager,slot_id=p.slot_id,proposal_token=p.proposal_token+'x',confirmed=True)
    def test_token_expiry_rejected_even_for_repeat(self):
        p=self.prepare();self.commit(p)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1000):
            with self.assertRaises(RuleError):self.commit(p)
    def test_repeat_stop_creates_no_second_event(self):
        p=self.prepare();a=self.commit(p);b=self.commit(p)
        self.assertEqual(a.event_id,b.event_id);self.assertTrue(b.repeated);self.assertEqual(self.maintenance_events().count(),1)
    def test_repeat_replacement_creates_no_second_new_slot(self):
        p=self.prepare('replace');a=self.commit(p);b=self.commit(p)
        self.assertEqual(a.replacement_id,b.replacement_id);self.assertEqual(AvailabilitySlot.objects.count(),3)
    def test_replay_does_not_restore_later_stopped_successor(self):
        p=self.prepare('replace');a=self.commit(p);new=AvailabilitySlot.objects.get(pk=a.replacement_id)
        self.commit(self.prepare(slot=new));b=self.commit(p);new.refresh_from_db()
        self.assertTrue(b.repeated);self.assertFalse(new.is_active)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_service_write_denied(self):
        p=self.prepare()
        with self.assertRaises(PermissionDenied):self.commit(p)
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active)
    def test_inactive_dentist_cannot_replace(self):
        Dentist.objects.filter(pk=self.d1.pk).update(is_active=False)
        with self.assertRaises(RuleError):self.prepare('replace')
        self.commit(self.prepare())
    def test_audit_failure_rolls_back_both_slots(self):
        p=self.prepare('replace')
        with patch('scheduling.availability_services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.commit(p)
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active);self.assertEqual(AvailabilitySlot.objects.count(),2)
    def test_late_cross_clinic_overlap_rolls_back_source_stop(self):
        p=self.prepare('replace')
        AvailabilitySlot.objects.create(clinic=self.b,dentist=self.d1,starts_at=self.t+timedelta(hours=5),ends_at=self.t+timedelta(hours=8))
        with self.assertRaises(RuleError):self.commit(p)
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active);self.assertEqual(self.maintenance_events().count(),0)
    def test_other_clinic_conflict_is_reported_before_preview(self):
        AvailabilitySlot.objects.create(clinic=self.b,dentist=self.d1,starts_at=self.t+timedelta(hours=5),ends_at=self.t+timedelta(hours=8))
        with self.assertRaises(RuleError):self.prepare('replace')
    def test_snapshot_changed_between_edit_and_preview(self):
        _,token=inspect_availability(actor=self.manager,slot_id=self.slot1.pk);self.book()
        with self.assertRaises(RuleError):prepare_availability_change(actor=self.manager,slot_id=self.slot1.pk,state_token=token,action='deactivate',reason_code='PLAN_CHANGED')
    def test_new_slot_creation_still_allowed_by_original_service(self):
        s=create_slot(actor=self.manager,clinic_id=self.a.pk,dentist_id=self.d1.pk,start=self.t+timedelta(days=2),end=self.t+timedelta(days=2,hours=3))
        self.assertTrue(s.is_active)
    def test_maintenance_does_not_change_accounts_or_invoices(self):
        before=(list(RoleAssignment.objects.values()),list(UserAccount.objects.values()),list(Invoice.objects.values()))
        self.commit(self.prepare('replace'))
        self.assertEqual(before,(list(RoleAssignment.objects.values()),list(UserAccount.objects.values()),list(Invoice.objects.values())))
    def test_actual_form_interprets_beijing_without_browser_zone(self):
        form=SlotChangeForm({'state_token':'x','start':'2030-01-01T09:00','end':'2030-01-01T10:00','reason_code':'PLAN_CHANGED'},action='replace')
        self.assertTrue(form.is_valid(),form.errors);self.assertEqual(form.cleaned_data['start'].utcoffset(),timedelta(hours=8))
    def test_actual_form_end_error_is_field_specific(self):
        form=SlotChangeForm({'state_token':'x','start':'2030-01-01T10:00','end':'2030-01-01T09:00','reason_code':'PLAN_CHANGED'},action='replace')
        self.assertFalse(form.is_valid());self.assertIn('end',form.errors)
    def test_list_and_detail_real_templates_render(self):
        c=self.client_manager()
        self.assertEqual(c.get(reverse('availability_list')).status_code,200)
        r=c.get(reverse('availability_detail',args=[self.slot1.pk]));self.assertContains(r,'关联业务影响')
    def test_list_scope_excludes_other_clinic_slot(self):
        c=self.client_manager();r=c.get(reverse('availability_list'))
        self.assertNotContains(r,reverse('availability_detail',args=[self.slot2.pk]))
    def test_manager_http_target_scope_is_enforced(self):
        self.assertEqual(self.client_manager().get(reverse('availability_detail',args=[self.slot2.pk])).status_code,403)
    def test_blocked_page_does_not_offer_confirm_form(self):
        self.book();c=self.client_manager();r=c.get(reverse('availability_change',args=[self.slot1.pk,'replace']))
        self.assertEqual(r.status_code,409);self.assertNotContains(r,'name="proposal_token"',status_code=409)
        self.assertNotContains(r,self.p1.patient_no,status_code=409)
    def test_http_preview_then_confirm_follows_real_middleware(self):
        c=self.client_manager();url=reverse('availability_change',args=[self.slot1.pk,'deactivate']);r=c.get(url)
        form=r.context['form'];token=form.initial['state_token']
        p=c.post(url,{'state_token':token,'reason_code':'PLAN_CHANGED'})
        self.assertContains(p,'尚未保存');proposal=p.context['preview'].proposal_token
        r=c.post(reverse('availability_confirm',args=[self.slot1.pk]),{'proposal_token':proposal,'confirmed':'on'})
        self.assertEqual(r.status_code,302);self.slot1.refresh_from_db();self.assertFalse(self.slot1.is_active)
    def test_http_confirm_without_csrf_rejected(self):
        c=self.client_manager(csrf=True)
        r=c.post(reverse('availability_confirm',args=[self.slot1.pk]),{'proposal_token':'x','confirmed':'on'})
        self.assertEqual(r.status_code,403)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_get_allows_scope_but_post_rejected(self):
        c=self.client_manager();r=c.get(reverse('availability_detail',args=[self.slot1.pk]));self.assertEqual(r.status_code,200)
        r=c.post(reverse('availability_confirm',args=[self.slot1.pk]),{'proposal_token':'x','confirmed':'on'})
        self.assertEqual(r.status_code,403)
    def test_confirm_get_cannot_mutate(self):
        c=self.client_manager();self.assertEqual(c.get(reverse('availability_confirm',args=[self.slot1.pk])).status_code,405)
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active)
    def test_database_error_uses_unknown_result_recovery(self):
        c=self.client_manager()
        with patch('scheduling.availability_views.confirm_availability_change',side_effect=DatabaseError('synthetic')):
            r=c.post(reverse('availability_confirm',args=[self.slot1.pk]),{'proposal_token':'x','confirmed':'on'})
        self.assertContains(r,'不代表此前一定失败',status_code=503)
    def race(self,left,right):
        barrier=Barrier(2)
        def run(fn):
            close_old_connections()
            try:
                with connection.cursor() as cursor:cursor.execute('SET statement_timeout TO 15000')
                barrier.wait(timeout=10)
                try:fn();return 'success'
                except RuleError:return 'rejected'
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(run,left);b=pool.submit(run,right)
            return [a.result(timeout=25),b.result(timeout=25)]
    def test_two_connection_booking_and_stop_preserve_invariant(self):
        p=self.prepare();out=self.race(lambda:self.commit(p),lambda:self.book())
        self.assertEqual(sorted(out),['rejected','success']);self.slot1.refresh_from_db()
        if Visit.objects.exists():self.assertTrue(self.slot1.is_active)
        else:self.assertFalse(self.slot1.is_active)
    def test_two_connection_publication_and_stop_preserve_invariant(self):
        p=self.prepare();plan=self.new_plan();out=self.race(lambda:self.commit(p),lambda:publish_plan(actor=self.manager2,plan_id=plan.pk))
        self.assertEqual(sorted(out),['rejected','success']);self.slot1.refresh_from_db()
        if WaitOffer.objects.exists():self.assertTrue(self.slot1.is_active)
        else:self.assertFalse(self.slot1.is_active)
    def test_two_connection_duplicate_replacement_one_commit(self):
        a=self.prepare('replace');b=self.prepare('replace',actor=self.manager2)
        out=self.race(lambda:self.commit(a),lambda:self.commit(b,actor=self.manager2))
        self.assertEqual(sorted(out),['rejected','success']);self.assertEqual(AvailabilitySlot.objects.count(),3)
    def test_two_connection_new_slot_and_replacement_conflict(self):
        p=self.prepare('replace')
        out=self.race(lambda:self.commit(p),lambda:create_slot(actor=self.manager2,clinic_id=self.a.pk,dentist_id=self.d1.pk,
            start=self.t+timedelta(hours=5),end=self.t+timedelta(hours=7)))
        self.assertEqual(sorted(out),['rejected','success'])
        self.assertEqual(AvailabilitySlot.objects.filter(dentist=self.d1,is_active=True,starts_at=self.t+timedelta(hours=5)).count(),1)
