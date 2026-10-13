"""SU-32/33: genuine Django/PostgreSQL tests. Authored, not yet executed here.
No mocked ORM, SQLite fallback, middleware removal or fabricated success.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from importlib import import_module
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import connection, close_old_connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent, Invoice
from coordination.models import WaitRequest, WaitOffer, SchedulePlan
from coordination.services import (publish_plan, create_plan, answer_offer, join_waitlist)
from portal.models import PatientAccess
from portal.services import preview_booking, confirm_booking, public_options, cancel_booking
from scheduling.models import AvailabilitySlot, Visit
from scheduling.services import create_appointment, change_appointment, reschedule, create_slot
from scheduling.selectors import booking_slots
from scheduling.availability_services import (inspect_availability, prepare_availability_change, confirm_availability_change)
from scheduling.front_coordination_selectors import read_coordination_slot
from scheduling.intake_services import (EVENTS, inspect_intake, prepare_intake, confirm_intake)
from tests.fixtures import FixtureMixin
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext

class IntakeAcceptanceTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.make_fixture()
        self.manager._adc_workspace=WorkspaceContext.objects.create(user=self.manager,role='MANAGER',clinic=self.a,revision=1)
        self.other=UserAccount.objects.create_user(username='intake_manager2',password='test-only-pass-123')
        RoleAssignment.objects.create(user=self.other,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        self.other._adc_workspace=WorkspaceContext.objects.create(user=self.other,role='MANAGER',clinic=self.a,revision=1)
        self.pa=UserAccount.objects.create_user(username='intake_patient',password='test-only-pass-123')
        self.access=PatientAccess.objects.create(user=self.pa,patient=self.p1)
    def preview(self,action='pause',actor=None,slot=None):
        actor=actor or self.manager;slot=slot or self.slot1
        _,token=inspect_intake(actor=actor,slot_id=slot.pk)
        return prepare_intake(actor=actor,slot_id=slot.pk,state_token=token,action=action,
            reason='COORDINATION' if action=='pause' else 'READY_TO_REOPEN')
    def commit(self,p,actor=None,confirmed=True):
        return confirm_intake(actor=actor or self.manager,slot_id=p['slot_id'],proposal_token=p['proposal_token'],confirmed=confirmed)
    def pause(self):return self.commit(self.preview())
    def plan(self,patient=None,slot=None):
        slot=slot or self.slot1;patient=patient or self.p1
        e=WaitRequest.objects.create(patient=patient,clinic=self.a,earliest=self.t,latest=self.t+timedelta(hours=4),created_by=self.front)
        return SchedulePlan.objects.create(clinic=self.a,created_by=self.manager,suggestions=[dict(request_id=e.pk,request_revision=e.revision,
            slot_id=slot.pk,start=self.t.isoformat(),end=(self.t+timedelta(minutes=30)).isoformat(),intake_revision=0)])
    def offer(self):
        p=self.plan();publish_plan(actor=self.manager,plan_id=p.pk)
        return WaitOffer.objects.get(plan=p)
    def counts(self):
        return tuple(m.objects.count() for m in (AvailabilitySlot,Visit,WaitOffer,WaitRequest,Invoice,AuditEvent))
    def test_defaults_preserve_existing_intake(self):
        self.assertFalse(self.slot1.booking_paused);self.assertEqual(self.slot1.intake_revision,0)
    def test_preview_has_no_business_changes(self):
        before=self.counts();p=self.preview();self.assertEqual(before,self.counts())
        self.assertEqual(p['before'],'接收新预约');self.assertEqual(p['after'],'已暂停新增')
    def test_pause_keeps_slot_effective_and_interval(self):
        self.pause();self.slot1.refresh_from_db()
        self.assertTrue(self.slot1.is_active);self.assertTrue(self.slot1.booking_paused)
        self.assertEqual(self.slot1.intake_revision,1);self.assertEqual(self.slot1.starts_at,self.t)
    def test_pause_preserves_existing_booking(self):
        v=self.book();original=(v.status,v.scheduled_start,v.scheduled_end,v.lock_version)
        self.pause();v.refresh_from_db()
        self.assertEqual(original,(v.status,v.scheduled_start,v.scheduled_end,v.lock_version))
    def test_pause_preserves_offer_state_and_expiry(self):
        o=self.offer();expiry=o.expires_at;self.pause();o.refresh_from_db()
        self.assertEqual((o.state,o.expires_at,o.visit_id),('PENDING',expiry,None))
    def test_front_new_booking_rejected(self):
        self.pause()
        with self.assertRaises(RuleError):self.book()
        self.assertFalse(Visit.objects.exists())
    def test_public_options_excludes_paused(self):
        self.pause();self.assertFalse(any(row['slot'].pk==self.slot1.pk for row in public_options(self.pa)))
    def test_staff_options_excludes_paused(self):
        self.pause();self.assertFalse(booking_slots(self.front).filter(pk=self.slot1.pk).exists())
    def test_direct_portal_preview_paused_rejected(self):
        self.pause()
        with self.assertRaises(ObjectDoesNotExist):preview_booking(user=self.pa,slot_id=self.slot1.pk,start=self.t)
    def test_old_portal_preview_after_pause_rejected(self):
        _,_,token=preview_booking(user=self.pa,slot_id=self.slot1.pk,start=self.t);self.pause()
        with self.assertRaises(RuleError):confirm_booking(actor=self.pa,token=token)
    def test_old_portal_preview_after_pause_resume_rejected(self):
        _,_,token=preview_booking(user=self.pa,slot_id=self.slot1.pk,start=self.t);self.pause();self.commit(self.preview('resume'))
        with self.assertRaises(RuleError):confirm_booking(actor=self.pa,token=token)
    def test_successful_portal_receipt_survives_pause(self):
        _,_,token=preview_booking(user=self.pa,slot_id=self.slot1.pk,start=self.t)
        v=confirm_booking(actor=self.pa,token=token);self.pause()
        self.assertEqual(confirm_booking(actor=self.pa,token=token).pk,v.pk)
    def test_existing_offer_accepted_during_pause(self):
        o=self.offer();self.pause();answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        o.refresh_from_db();self.assertEqual(o.state,'ACCEPTED');self.assertIsNotNone(o.visit_id)
        self.assertEqual(o.visit.availability_slot_id,self.slot1.pk)
    def test_patient_accepts_existing_offer_during_pause(self):
        o=self.offer();self.pause();answer_offer(actor=self.pa,offer_id=o.pk,accept=True)
        o.refresh_from_db();self.assertEqual(o.visit.patient_id,self.p1.pk)
    def test_offer_rejection_during_pause_preserved(self):
        o=self.offer();self.pause();answer_offer(actor=self.front,offer_id=o.pk,accept=False)
        o.refresh_from_db();self.assertEqual(o.state,'DECLINED');self.assertFalse(Visit.objects.exists())
    def test_expired_offer_not_revived_by_pause(self):
        o=self.offer();self.pause()
        with patch('coordination.services.timezone.now',return_value=o.expires_at):
            with self.assertRaises(RuleError):answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        self.assertFalse(Visit.objects.exists())
    def test_expired_offer_not_revived_by_resume(self):
        o=self.offer();self.pause();self.commit(self.preview('resume'))
        with patch('coordination.services.timezone.now',return_value=o.expires_at):
            with self.assertRaises(RuleError):answer_offer(actor=self.front,offer_id=o.pk,accept=True)
    def test_accept_failure_keeps_offer_and_request(self):
        o=self.offer();self.pause()
        with patch('scheduling.services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        o.refresh_from_db();o.request.refresh_from_db()
        self.assertEqual(o.state,'PENDING');self.assertEqual(o.request.state,'OFFERED');self.assertFalse(Visit.objects.exists())
    def test_offer_retry_after_pause_is_one_visit(self):
        o=self.offer();self.pause();first=answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        second=answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        self.assertEqual(first.visit_id,second.visit_id);self.assertEqual(Visit.objects.count(),1)
    def test_new_plan_excludes_paused(self):
        self.plan();self.pause();plan=create_plan(actor=self.manager,clinic_id=self.a.pk)
        self.assertFalse(any(r['slot_id']==self.slot1.pk for r in plan.suggestions))
    def test_unpublished_draft_rejected_after_pause(self):
        p=self.plan();self.pause()
        with self.assertRaises(RuleError):publish_plan(actor=self.manager,plan_id=p.pk)
        p.refresh_from_db();self.assertEqual(p.state,'DRAFT');self.assertFalse(WaitOffer.objects.exists())
    def test_unpublished_draft_rejected_after_pause_resume(self):
        p=self.plan();self.pause();self.commit(self.preview('resume'))
        with self.assertRaises(RuleError):publish_plan(actor=self.manager,plan_id=p.pk)
    def test_published_plan_retry_returns_original(self):
        p=self.plan();publish_plan(actor=self.manager,plan_id=p.pk);self.pause()
        self.assertEqual(publish_plan(actor=self.manager,plan_id=p.pk).pk,p.pk)
        self.assertEqual(WaitOffer.objects.filter(plan=p).count(),1)
    def test_batch_publish_with_paused_slot_rolls_back_all(self):
        p=self.plan();e=WaitRequest.objects.create(patient=self.p2,clinic=self.a,earliest=self.t,latest=self.t+timedelta(hours=4),created_by=self.front)
        other=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d2,starts_at=self.t+timedelta(days=2),ends_at=self.t+timedelta(days=2,hours=2))
        # Second row still within its own request window. First row must not survive rejection.
        e.earliest=other.starts_at;e.latest=other.ends_at;e.save()
        p.suggestions.append(dict(request_id=e.pk,request_revision=0,slot_id=other.pk,start=other.starts_at.isoformat(),
            end=(other.starts_at+timedelta(minutes=30)).isoformat(),intake_revision=0));p.save()
        self.commit(self.preview(slot=other))
        with self.assertRaises(RuleError):publish_plan(actor=self.manager,plan_id=p.pk)
        self.assertFalse(WaitOffer.objects.exists());self.assertFalse(WaitRequest.objects.filter(state='OFFERED').exists())
    def test_waitlist_registration_is_still_allowed(self):
        self.pause();e=join_waitlist(actor=self.front,clinic_id=self.a.pk,patient_no=self.p1.patient_no,earliest=self.t,latest=self.t+timedelta(hours=4))
        self.assertEqual(e.state,'WAITING')
    def test_reschedule_out_allowed(self):
        v=self.book();self.pause()
        dest=create_slot(actor=self.manager,clinic_id=self.a.pk,dentist_id=self.d1.pk,start=self.t+timedelta(days=1),end=self.t+timedelta(days=1,hours=2))
        new=reschedule(actor=self.front,visit_id=v.pk,expected_version=0,new_slot_id=dest.pk,start=dest.starts_at,end=dest.starts_at+timedelta(minutes=30),reason='合成同意改期')
        self.assertEqual(new.availability_slot_id,dest.pk)
    def test_reschedule_into_paused_rolls_back_source(self):
        v=self.book(slot_id=self.slot2.pk);self.pause()
        with self.assertRaises(RuleError):reschedule(actor=self.front,visit_id=v.pk,expected_version=0,new_slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),reason='合成改期')
        v.refresh_from_db();self.assertEqual(v.status,'SCHEDULED');self.assertEqual(Visit.objects.count(),1)
    def test_existing_checkin_not_blocked(self):
        v=self.book();self.pause();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        v.refresh_from_db();self.assertEqual(v.status,'CHECKED_IN')
    def test_existing_cancellation_not_blocked(self):
        v=self.book();self.pause();cancel_booking(actor=self.pa,visit_id=v.pk,expected_version=0,reason='合成主动取消')
        v.refresh_from_db();self.assertEqual(v.status,'CANCELLED')
    def test_resume_allows_fresh_booking(self):
        self.pause();self.commit(self.preview('resume'));self.book();self.assertEqual(Visit.objects.count(),1)
    def test_pause_keeps_original_resource_constraint(self):
        self.pause()
        with self.assertRaises(RuleError):create_slot(actor=self.manager,clinic_id=self.a.pk,dentist_id=self.d1.pk,start=self.t,end=self.t+timedelta(hours=1))
    def test_empty_paused_replacement_preserves_pause(self):
        self.pause();_,token=inspect_availability(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_availability_change(actor=self.manager,slot_id=self.slot1.pk,state_token=token,action='replace',reason_code='PLAN_CHANGED',start=self.t+timedelta(days=1),end=self.t+timedelta(days=1,hours=2))
        r=confirm_availability_change(actor=self.manager,slot_id=self.slot1.pk,proposal_token=p.proposal_token,confirmed=True)
        self.assertTrue(AvailabilitySlot.objects.get(pk=r.replacement_id).booking_paused)
    def test_old_maintenance_preview_rejected_after_intake_changes(self):
        _,token=inspect_availability(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_availability_change(actor=self.manager,slot_id=self.slot1.pk,state_token=token,action='deactivate',reason_code='PLAN_CHANGED')
        self.pause()
        with self.assertRaises(RuleError):confirm_availability_change(actor=self.manager,slot_id=self.slot1.pk,proposal_token=p.proposal_token,confirmed=True)
    def test_intake_aba_invalidates_another_managers_preview(self):
        old=self.preview(actor=self.other);self.pause();self.commit(self.preview('resume'))
        with self.assertRaises(RuleError):self.commit(old,actor=self.other)
    def test_successful_pause_replay_cannot_undo_resume(self):
        p=self.preview();self.commit(p);self.commit(self.preview('resume'));r=self.commit(p)
        self.assertTrue(r.repeated);self.assertFalse(r.paused)
    def test_commit_requires_confirmation(self):
        with self.assertRaises(RuleError):self.commit(self.preview(),confirmed=False)
    def test_audit_failure_rolls_back_pause_and_revision(self):
        p=self.preview()
        with patch('scheduling.intake_services.emit',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):self.commit(p)
        self.slot1.refresh_from_db();self.assertFalse(self.slot1.booking_paused);self.assertEqual(self.slot1.intake_revision,0)
    def test_clinic_scope_rejected(self):
        with self.assertRaises(PermissionDenied):self.preview(slot=self.slot2)
    def test_front_cannot_change_intake(self):
        with self.assertRaises(PermissionDenied):self.preview(actor=self.front)
    def test_readonly_blocks_service_commit(self):
        p=self.preview()
        with override_settings(ADC_READ_ONLY=True),self.assertRaises(PermissionDenied):self.commit(p)
    def test_expired_confirm_rejected(self):
        p=self.preview()
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1000),self.assertRaises(RuleError):self.commit(p)
    def test_tampered_confirm_rejected(self):
        p=self.preview();p['proposal_token']+='changed'
        with self.assertRaises(RuleError):self.commit(p)
    def test_new_booking_invalidates_pause_preview(self):
        p=self.preview();self.book()
        with self.assertRaises(RuleError):self.commit(p)
    def test_role_revocation_rejects_commit(self):
        p=self.preview();RoleAssignment.objects.filter(user=self.manager).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_manager_pages_render_real_templates(self):
        c=WorkspaceClient();c.force_login(self.manager)
        self.assertContains(c.get(reverse('intake_change',args=[self.slot1.pk,'pause'])),'暂停接收新预约')
        self.assertContains(c.get(reverse('availability_detail',args=[self.slot1.pk])),'控制是否接收新预约')
    def test_get_confirm_never_writes(self):
        c=WorkspaceClient();c.force_login(self.manager);before=self.counts()
        self.assertEqual(c.get(reverse('intake_confirm',args=[self.slot1.pk])).status_code,405)
        self.assertEqual(before,self.counts())
    def test_http_csrf_still_enforced(self):
        c=WorkspaceClient(enforce_csrf_checks=True);c.force_login(self.manager)
        self.assertEqual(c.post(reverse('intake_confirm',args=[self.slot1.pk]),{'confirmed':'on','proposal_token':'x'}).status_code,403)
    def test_actual_http_preview_confirm_and_resume(self):
        c=WorkspaceClient();c.force_login(self.manager)
        for action,reason,paused in [('pause','COORDINATION',True),('resume','READY_TO_REOPEN',False)]:
            page=c.get(reverse('intake_change',args=[self.slot1.pk,action]))
            token=page.context['form'].initial['state_token']
            preview=c.post(reverse('intake_change',args=[self.slot1.pk,action]),dict(state_token=token,reason=reason))
            self.assertContains(preview,'尚未保存')
            result=c.post(reverse('intake_confirm',args=[self.slot1.pk]),dict(proposal_token=preview.context['preview']['proposal_token'],confirmed='on'))
            self.assertEqual(result.status_code,302);self.slot1.refresh_from_db();self.assertEqual(self.slot1.booking_paused,paused)
    def test_front_http_direct_intake_is_denied(self):
        c=WorkspaceClient();c.force_login(self.front)
        self.assertEqual(c.get(reverse('intake_change',args=[self.slot1.pk,'pause'])).status_code,403)
    def test_readonly_http_post_remains_denied(self):
        c=WorkspaceClient();c.force_login(self.manager)
        with override_settings(ADC_READ_ONLY=True):
            self.assertIn(c.post(reverse('intake_change',args=[self.slot1.pk,'pause']),dict(reason='COORDINATION')).status_code,(403,409))
    def test_context_change_refuses_old_confirmation(self):
        p=self.preview();ctx=self.manager._adc_workspace
        WorkspaceContext.objects.filter(pk=ctx.pk).update(revision=ctx.revision+1)
        with self.assertRaises(PermissionDenied):self.commit(p)
    def test_existing_care_can_close_while_intake_paused(self):
        from care.services import complete_visit
        doctor=UserAccount.objects.create_user(username='intake_doctor',password='test-only-pass',dentist=self.d1)
        RoleAssignment.objects.create(user=doctor,role='DENTIST',scope_kind='SELF_DENTIST')
        v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        self.pause();v.refresh_from_db()
        complete_visit(actor=doctor,visit_id=v.pk,expected_version=v.lock_version,outcome='NO_TREATMENT',reason='合成无治疗关闭')
        v.refresh_from_db();self.assertEqual(v.status,'CLOSED_NO_TREATMENT');self.assertTrue(Invoice.objects.filter(visit=v).exists())
    def test_front_read_shows_saved_pause_without_manager_link(self):
        self.pause();self.front._adc_workspace=WorkspaceContext.objects.create(user=self.front,role='FRONT_DESK',clinic=self.a,revision=1)
        self.assertTrue(read_coordination_slot(actor=self.front,slot_id=self.slot1.pk)['slot']['paused'])
    def test_reverse_migration_refuses_used_intake_state(self):
        self.pause();module=import_module('scheduling.migrations.0002_slot_intake_control')
        from django.apps import apps
        from types import SimpleNamespace
        with self.assertRaises(RuntimeError):module.guard_reverse(apps,SimpleNamespace(connection=connection))
    def test_additive_migration_preserves_old_slots_and_default(self):
        old=(self.slot1.pk,self.slot1.starts_at,self.slot1.ends_at,self.slot1.dentist_id,self.slot1.clinic_id)
        executor=MigrationExecutor(connection)
        final_targets=executor.loader.graph.leaf_nodes()
        try:
            executor.migrate([('scheduling','0001_initial')])
            historical=executor.loader.project_state([('scheduling','0001_initial')]).apps.get_model('scheduling','AvailabilitySlot')
            self.assertTrue(historical.objects.filter(pk=self.slot1.pk).exists())
        finally:
            MigrationExecutor(connection).migrate(final_targets)
        self.slot1.refresh_from_db()
        self.assertEqual(old,(self.slot1.pk,self.slot1.starts_at,self.slot1.ends_at,self.slot1.dentist_id,self.slot1.clinic_id))
        self.assertFalse(self.slot1.booking_paused);self.assertEqual(self.slot1.intake_revision,0)

class IntakeConcurrencyTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql');self.make_fixture()
        self.ctx=WorkspaceContext.objects.create(user=self.manager,role='MANAGER',clinic=self.a,revision=1)
        self.manager._adc_workspace=self.ctx
    def wait_for_lock(self,app):
        deadline=monotonic()+8
        while monotonic()<deadline:
            with connection.cursor() as cur:
                cur.execute('SELECT wait_event_type FROM pg_stat_activity WHERE application_name=%s',[app])
                if any(row[0]=='Lock' for row in cur.fetchall()):return
            sleep(.03)
        self.fail('Competing database connection did not reach the shared row lock')
    def race(self,kind):
        from scheduling import intake_services
        plan=None;offer=None
        if kind in ('publish','accept'):
            entry=WaitRequest.objects.create(patient=self.p1,clinic=self.a,earliest=self.t,latest=self.t+timedelta(hours=4),created_by=self.front)
            plan=SchedulePlan.objects.create(clinic=self.a,created_by=self.manager,suggestions=[dict(request_id=entry.pk,request_revision=0,slot_id=self.slot1.pk,start=self.t.isoformat(),end=(self.t+timedelta(minutes=30)).isoformat(),intake_revision=0)])
            if kind=='accept':publish_plan(actor=self.manager,plan_id=plan.pk);offer=WaitOffer.objects.get(plan=plan)
        _,state=inspect_intake(actor=self.manager,slot_id=self.slot1.pk)
        preview=prepare_intake(actor=self.manager,slot_id=self.slot1.pk,state_token=state,action='pause',reason='COORDINATION')
        locked=Event();release=Event();original=intake_services._transition
        def block_transition(snapshot,action,reason):
            locked.set()
            if not release.wait(12):raise RuntimeError('test release timeout')
            return original(snapshot,action,reason)
        def pause_worker():
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.manager.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=self.ctx.pk)
                return confirm_intake(actor=actor,slot_id=self.slot1.pk,proposal_token=preview['proposal_token'],confirmed=True)
            finally:connection.close()
        app='adc_intake_race_'+kind
        def competing_worker():
            close_old_connections()
            try:
                with connection.cursor() as cur:cur.execute("SELECT set_config('application_name',%s,false)",[app])
                actor=UserAccount.objects.get(pk=self.front.pk)
                if kind=='publish':
                    # Separate manager account avoids serializing only on actor (rather than slot).
                    actor=UserAccount.objects.get(pk=self.manager2.pk)
                    return publish_plan(actor=actor,plan_id=plan.pk)
                if kind=='accept':return answer_offer(actor=actor,offer_id=offer.pk,accept=True)
                return create_appointment(actor=actor,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30))
            finally:connection.close()
        self.manager2=UserAccount.objects.create_user(username='race_manager2',password='synthetic-pass')
        RoleAssignment.objects.create(user=self.manager2,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        with ThreadPoolExecutor(max_workers=2) as pool,patch('scheduling.intake_services._transition',side_effect=block_transition):
            first=pool.submit(pause_worker)
            try:
                self.assertTrue(locked.wait(8));second=pool.submit(competing_worker);self.wait_for_lock(app)
            finally:release.set()
            first.result(timeout=15)
            if kind=='accept':self.assertEqual(second.result(timeout=15).state,'ACCEPTED')
            else:
                with self.assertRaises(RuleError):second.result(timeout=15)
        self.slot1.refresh_from_db();self.assertTrue(self.slot1.booking_paused)
        self.assertEqual(Visit.objects.count(),1 if kind=='accept' else 0)
    def test_pause_serializes_with_new_booking(self):self.race('book')
    def test_pause_serializes_with_new_offer_publication(self):self.race('publish')
    def test_valid_existing_offer_survives_concurrent_pause(self):self.race('accept')
