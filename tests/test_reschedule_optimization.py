"""Real PostgreSQL/HTTP acceptance for replacement search and confirmed moves."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Barrier
from unittest.mock import patch
import time

from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import connection, close_old_connections, connections
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from coordination.models import WaitRequest, WaitOffer, SchedulePlan
from registry.models import Dentist
from scheduling.models import Visit, AvailabilitySlot
from scheduling.services import create_appointment, change_appointment, reschedule
from scheduling.reschedule_selectors import replacement_options
from scheduling.reschedule_services import prepare_reschedule, confirm_reschedule, SALT, MAX_AGE
from tests.test_v07 import V07Fixture
from workspaces.models import WorkspaceContext


class MoveFixture(V07Fixture):
    def setup_move(self):
        self.setup07()
        self.old = self.book()
        self.front._adc_workspace = WorkspaceContext.objects.create(user=self.front, role='FRONT_DESK', clinic=self.a)
        self.front2._adc_workspace = WorkspaceContext.objects.create(user=self.front2, role='FRONT_DESK', clinic=self.a)

    def options(self, **kwargs):
        return replacement_options(actor=self.front, visit_id=self.old.pk,
            day=timezone.localtime(self.t).date(), **kwargs)

    def preview(self, **kwargs):
        data = dict(actor=self.front, visit_id=self.old.pk, expected_version=0, new_slot_id=self.slot1.pk,
                    start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2), reason='合成患者确认改期')
        data.update(kwargs)
        return prepare_reschedule(**data)

    def confirm(self, preview, **kwargs):
        data = dict(actor=self.front, visit_id=self.old.pk, proposal_token=preview['proposal_token'], confirmed=True)
        data.update(kwargs)
        return confirm_reschedule(**data)

    def unchanged(self):
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'SCHEDULED')
        self.assertEqual(self.old.lock_version, 0)
        self.assertFalse(Visit.objects.filter(replaces_visit_id=self.old.pk).exists())

    def offer(self, *, patient=None, slot=None, expires=None):
        slot = slot or self.slot1
        entry = WaitRequest.objects.create(patient=patient or self.p2, clinic=slot.clinic,
            earliest=self.t+timedelta(hours=1), latest=self.t+timedelta(hours=3), state='OFFERED', created_by=self.front2)
        plan = SchedulePlan.objects.create(clinic=slot.clinic, created_by=self.manager, state='PUBLISHED', published_at=timezone.now())
        return WaitOffer.objects.create(request=entry, plan=plan, slot=slot,
            starts_at=self.t+timedelta(hours=1), ends_at=self.t+timedelta(hours=1, minutes=30),
            expires_at=expires or timezone.now()+timedelta(minutes=10))

    def another_dentist(self, number=3):
        doctor = Dentist.objects.create(employee_no=f'MOVE-{number}', name=f'合成替代牙医{number}',
            date_of_birth=date(1990, 1, 1), home_address='虚构地址', phone='000', email=f'd{number}@example.invalid')
        slot = AvailabilitySlot.objects.create(clinic=self.a, dentist=doctor, starts_at=self.t, ends_at=self.t+timedelta(hours=4))
        return doctor, slot


class ReplacementSearchTests(MoveFixture, TransactionTestCase):
    def setUp(self): self.setup_move()

    def test_search_does_not_modify_original_or_create_reservation(self):
        before = AuditEvent.objects.count()
        rows = self.options()['rows']
        self.assertTrue(rows)
        self.unchanged()
        self.assertEqual(Visit.objects.count(), 1)
        self.assertFalse(WaitOffer.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_original_duration_preserved_even_when_not_thirty_minutes(self):
        result = self.options()
        self.assertTrue(all(row['end']-row['start']==timedelta(hours=1) for row in result['rows']))
        self.assertEqual(result['duration_minutes'], 60)

    def test_original_interval_not_recommended_but_partial_overlap_is_possible(self):
        starts = {row['start'] for row in self.options()['rows']}
        self.assertNotIn(self.t, starts)
        self.assertIn(self.t+timedelta(minutes=30), starts)

    def test_other_dentist_at_original_time_is_a_real_change(self):
        doctor, slot = self.another_dentist()
        rows = self.options(dentist_id=doctor.pk)['rows']
        self.assertIn(self.t, {row['start'] for row in rows})
        self.assertTrue(all(row['slot_id']==slot.pk for row in rows))

    def test_other_patient_booking_blocks_dentist_interval(self):
        create_appointment(actor=self.front2, patient_no=self.p2.patient_no, slot_id=self.slot1.pk,
            start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2))
        rows = self.options()['rows']
        self.assertTrue(all(not (row['start']<self.t+timedelta(hours=2) and self.t+timedelta(hours=1)<row['end']) for row in rows))

    def test_cross_clinic_patient_booking_blocks_without_disclosing_other_clinic(self):
        actor = UserAccount.objects.get(pk=self.front2.pk)  # trusted core fixture actor with both grants
        create_appointment(actor=actor, patient_no=self.p1.patient_no, slot_id=self.slot2.pk,
            start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2))
        result = self.options()
        self.assertTrue(all(row['start']>=self.t+timedelta(hours=2) for row in result['rows']))
        self.assertNotIn(self.b.name, str(result))

    def test_live_dentist_offer_blocks_candidate(self):
        self.offer()
        rows = self.options()['rows']
        self.assertTrue(all(not (row['start']<self.t+timedelta(hours=1, minutes=30) and self.t+timedelta(hours=1)<row['end']) for row in rows))

    def test_cross_clinic_patient_offer_blocks_candidate(self):
        self.offer(patient=self.p1, slot=self.slot2)
        rows = self.options()['rows']
        self.assertTrue(all(not (row['start']<self.t+timedelta(hours=1, minutes=30) and self.t+timedelta(hours=1)<row['end']) for row in rows))

    def test_expired_pending_offer_does_not_block_or_recycle(self):
        offer = self.offer(expires=timezone.now()-timedelta(seconds=1))
        self.assertIn(self.t+timedelta(hours=1), {row['start'] for row in self.options()['rows']})
        offer.refresh_from_db(); self.assertEqual(offer.state, 'PENDING')

    def test_paused_source_is_not_a_destination_but_original_stays_valid(self):
        doctor, slot = self.another_dentist()
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=True, intake_revision=1)
        rows = self.options()['rows']
        self.assertTrue(rows)
        self.assertTrue(all(row['slot_id']==slot.pk for row in rows))
        self.unchanged()

    def test_inactive_destination_dentist_not_recommended(self):
        doctor, slot = self.another_dentist()
        Dentist.objects.filter(pk=doctor.pk).update(is_active=False)
        self.assertNotIn(slot.pk, {row['slot_id'] for row in self.options()['rows']})

    def test_filter_does_not_borrow_other_clinic_doctor(self):
        self.assertEqual(self.options(dentist_id=self.d2.pk)['rows'], [])

    def test_outside_search_horizon_refused(self):
        for offset in (-1, 15):
            with self.assertRaises(RuleError):
                replacement_options(actor=self.front, visit_id=self.old.pk, day=timezone.localdate()+timedelta(days=offset))

    def test_source_wrong_clinic_refused(self):
        self.front._adc_workspace = WorkspaceContext.objects.create(user=self.front, role='FRONT_DESK', clinic=self.b)
        with self.assertRaises(Visit.DoesNotExist): self.options()

    def test_inactive_patient_refused(self):
        from patients.models import Patient
        Patient.objects.filter(pk=self.p1.pk).update(is_active=False)
        with self.assertRaises(RuleError): self.options()

    def test_checked_in_source_refused(self):
        change_appointment(actor=self.front, visit_id=self.old.pk, expected_version=0, action='check_in')
        with self.assertRaises(RuleError): self.options()

    def test_option_count_and_incomplete_flag_are_explicit(self):
        for n in range(3, 9): self.another_dentist(n)
        result = self.options()
        self.assertEqual(len(result['rows']), 30)
        self.assertTrue(result['limited'])

    def test_large_relation_set_fails_closed_without_claiming_no_capacity(self):
        start = self.t+timedelta(hours=1)
        Visit.objects.bulk_create([Visit(patient=self.p2, dentist=self.d1, clinic=self.a, availability_slot=self.slot1,
            scheduled_start=start+timedelta(seconds=2*n), scheduled_end=start+timedelta(seconds=2*n+1)) for n in range(1001)])
        result = self.options()
        self.assertEqual(result['rows'], [])
        self.assertTrue(result['limited'])
        self.assertIn('关联安排', result['limit_reason'])

    def test_search_queries_do_not_grow_per_candidate_dentist(self):
        with CaptureQueriesContext(connection) as one: self.options()
        for n in range(3, 7): self.another_dentist(n)
        with CaptureQueriesContext(connection) as many: self.options()
        self.assertEqual(len(one), len(many))


class RescheduleConfirmationTests(MoveFixture, TransactionTestCase):
    def setUp(self): self.setup_move()

    def test_preview_is_read_only(self):
        before = AuditEvent.objects.count()
        result = self.preview()
        self.assertIn('proposal_token', result)
        self.unchanged()
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_unchanged_arrangement_cannot_create_pointless_successor(self):
        with self.assertRaises(RuleError): self.preview(start=self.t, end=self.t+timedelta(hours=1))
        self.unchanged()

    def test_success_keeps_history_and_copies_requests(self):
        from scheduling.models import VisitRequest
        VisitRequest.objects.create(visit=self.old, description='合成治疗意向，非已治疗')
        result = self.confirm(self.preview())
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'RESCHEDULED')
        self.assertEqual(self.old.scheduled_start, self.t)
        self.assertEqual(result.visit.replaces_visit_id, self.old.pk)
        self.assertEqual(result.visit.requests.get().description, '合成治疗意向，非已治疗')
        self.assertEqual(Visit.objects.count(), 2)
        self.assertFalse(result.repeated)

    def test_repeat_returns_unique_existing_successor(self):
        preview = self.preview(); first = self.confirm(preview); repeated = self.confirm(preview)
        self.assertEqual(first.visit.pk, repeated.visit.pk)
        self.assertTrue(repeated.repeated)
        self.assertEqual(Visit.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(event_type='VISIT_RESCHEDULED').count(), 1)

    def test_repeat_does_not_revive_cancelled_successor(self):
        preview = self.preview(); result = self.confirm(preview)
        change_appointment(actor=self.front, visit_id=result.visit.pk, expected_version=result.visit.lock_version,
            action='cancel', party='PATIENT', reason='合成患者随后另行取消')
        repeated = self.confirm(preview)
        self.assertTrue(repeated.repeated)
        self.assertEqual(repeated.visit.status, 'CANCELLED')
        self.assertEqual(Visit.objects.count(), 2)

    def test_saved_repeat_survives_later_admission_pause(self):
        preview = self.preview(); result = self.confirm(preview)
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=True, intake_revision=1)
        self.assertEqual(self.confirm(preview).visit.pk, result.visit.pk)

    def test_another_preview_cannot_overwrite_completed_move(self):
        first = self.preview()
        second = self.preview(start=self.t+timedelta(hours=2), end=self.t+timedelta(hours=3))
        self.confirm(first)
        with self.assertRaises(RuleError): self.confirm(second)
        self.assertEqual(Visit.objects.count(), 2)

    def test_new_booking_after_preview_refused_and_source_preserved(self):
        preview = self.preview()
        create_appointment(actor=self.front2, patient_no=self.p2.patient_no, slot_id=self.slot1.pk,
            start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2))
        with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_new_offer_after_preview_refused_and_source_preserved(self):
        preview = self.preview(); self.offer()
        with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_cross_clinic_patient_commitment_after_preview_refused(self):
        preview = self.preview()
        create_appointment(actor=UserAccount.objects.get(pk=self.front2.pk), patient_no=self.p1.patient_no,
            slot_id=self.slot2.pk, start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2))
        with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_pause_resume_invalidates_old_confirmation(self):
        preview = self.preview()
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=True, intake_revision=1)
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=False, intake_revision=2)
        with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_inactive_dentist_after_preview_rolls_back_move(self):
        preview = self.preview()
        Dentist.objects.filter(pk=self.d1.pk).update(is_active=False)
        with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_source_check_in_after_preview_refused(self):
        preview = self.preview()
        change_appointment(actor=self.front, visit_id=self.old.pk, expected_version=0, action='check_in')
        with self.assertRaises(RuleError): self.confirm(preview)
        self.assertFalse(Visit.objects.filter(replaces_visit_id=self.old.pk).exists())

    def test_source_cancel_after_preview_refused(self):
        preview = self.preview()
        change_appointment(actor=self.front, visit_id=self.old.pk, expected_version=0,
            action='cancel', party='PATIENT', reason='合成患者改为取消')
        with self.assertRaises(RuleError): self.confirm(preview)
        self.assertFalse(Visit.objects.filter(replaces_visit_id=self.old.pk).exists())

    def test_different_account_cannot_use_confirmation(self):
        with self.assertRaises(RuleError): self.confirm(self.preview(), actor=self.front2)
        self.unchanged()

    def test_context_switch_and_return_still_invalidates_confirmation(self):
        preview = self.preview(); ctx = self.front._adc_workspace
        WorkspaceContext.objects.filter(pk=ctx.pk).update(revision=ctx.revision+2)
        self.front._adc_workspace = WorkspaceContext.objects.get(pk=ctx.pk)
        with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_revoked_grant_prevents_confirmation(self):
        preview = self.preview()
        RoleAssignment.objects.filter(user=self.front, clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.confirm(preview)
        self.unchanged()

    def test_expired_and_tampered_confirmation_refused(self):
        preview = self.preview()
        with self.assertRaises(RuleError): self.confirm(preview, proposal_token=preview['proposal_token']+'x')
        with patch('django.core.signing.time.time', return_value=time.time()+MAX_AGE+2):
            with self.assertRaises(RuleError): self.confirm(preview)
        self.unchanged()

    def test_explicit_confirmation_required(self):
        with self.assertRaises(RuleError): self.confirm(self.preview(), confirmed=False)
        self.unchanged()

    def test_readonly_cannot_confirm_but_can_preview(self):
        with override_settings(ADC_READ_ONLY=True):
            preview = self.preview()
            with self.assertRaises(PermissionDenied): self.confirm(preview)
        self.unchanged()

    def test_audit_failure_rolls_back_original_and_successor(self):
        preview = self.preview()
        with patch('scheduling.services.emit', side_effect=RuntimeError('injected audit failure')):
            with self.assertRaises(RuntimeError): self.confirm(preview)
        self.unchanged()
        self.assertEqual(Visit.objects.count(), 1)


class RescheduleHTTPTests(MoveFixture, TransactionTestCase):
    def setUp(self):
        self.setup_move(); self.login(self.front, 'FRONT_DESK', self.a)
        self.url = reverse('visit_reschedule', args=[self.old.pk])

    def post_preview(self, **kwargs):
        data = {'expected_version':0, 'slot':self.slot1.pk, 'start':(self.t+timedelta(hours=1)).isoformat(),
                'end':(self.t+timedelta(hours=2)).isoformat(), 'reason':'合成患者同意'}
        data.update(kwargs)
        return self.post('visit_reschedule', data, args=[self.old.pk])

    def test_get_and_choose_only_prefill_no_write(self):
        response = self.c.get(self.url)
        self.assertContains(response, '查询替代时间')
        row = response.context['options']['rows'][0]
        selected = self.c.get(row['choose_url'])
        self.assertEqual(selected.context['form'].initial['start'], row['start'])
        self.assertEqual(selected.context['form'].initial['end'], row['end'])
        self.unchanged()

    def test_old_html_post_is_now_preview_then_explicit_confirmation(self):
        preview = self.post_preview()
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, '尚未保存')
        self.unchanged()
        data = {'action':'confirm', 'proposal_token':preview.context['preview']['proposal_token'], 'confirmed':'on'}
        response = self.post('visit_reschedule', data, args=[self.old.pk])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Visit.objects.count(), 2)
        repeated = self.post('visit_reschedule', data, args=[self.old.pk])
        self.assertEqual(repeated.url, response.url)
        self.assertEqual(Visit.objects.count(), 2)

    def test_confirm_ignores_injected_raw_destination_fields(self):
        preview = self.post_preview()
        response = self.post('visit_reschedule', {'action':'confirm', 'proposal_token':preview.context['preview']['proposal_token'],
            'confirmed':'on', 'slot':self.slot2.pk, 'start':self.t.isoformat()}, args=[self.old.pk])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Visit.objects.get(replaces_visit_id=self.old.pk).availability_slot_id, self.slot1.pk)

    def test_missing_confirm_checkbox_no_write(self):
        preview = self.post_preview()
        response = self.post('visit_reschedule', {'action':'confirm', 'proposal_token':preview.context['preview']['proposal_token']}, args=[self.old.pk])
        self.assertEqual(response.status_code, 409)
        self.unchanged()

    def test_bad_search_filters_do_not_return_unfiltered_options(self):
        for query in ({'day':'wrong'}, {'dentist':str(self.d2.pk)}):
            response = self.c.get(self.url, query)
            self.assertIsNone(response.context['options'])
            self.unchanged()

    def test_foreign_candidate_does_not_prefill_or_disclose_foreign_clinic(self):
        response = self.c.get(self.url, {'slot':self.slot2.pk, 'start':self.t.isoformat(), 'end':(self.t+timedelta(hours=1)).isoformat()})
        self.assertContains(response, '选定时段已变化或无权使用')
        self.assertNotContains(response, self.b.name)
        self.assertNotIn('slot', response.context['form'].initial)

    def test_manager_role_cannot_read_or_submit_reschedule(self):
        self.login(self.manager, 'MANAGER', self.a)
        self.assertEqual(self.c.get(self.url).status_code, 403)
        self.assertEqual(self.post_preview().status_code, 403)
        self.unchanged()

    def test_error_after_occupied_preview_retains_original_and_recovery_link(self):
        preview = self.post_preview()
        create_appointment(actor=self.front2, patient_no=self.p2.patient_no, slot_id=self.slot1.pk,
            start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2))
        response = self.post('visit_reschedule', {'action':'confirm', 'proposal_token':preview.context['preview']['proposal_token'], 'confirmed':'on'}, args=[self.old.pk])
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, '打开原预约核对结果', status_code=409)
        self.unchanged()


class RescheduleRaceTests(MoveFixture, TransactionTestCase):
    def setUp(self): self.setup_move()

    def race(self, call):
        barrier = Barrier(2, timeout=15)
        def worker(index):
            close_old_connections()
            try: barrier.wait(); return call(index)
            finally: connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, (0, 1)))

    def actor(self, original):
        actor = UserAccount.objects.get(pk=original.pk)
        actor._adc_workspace = WorkspaceContext.objects.get(pk=original._adc_workspace.pk)
        return actor

    def test_concurrent_duplicate_confirmation_returns_one_successor(self):
        preview = self.preview()
        def call(index):
            return confirm_reschedule(actor=self.actor(self.front), visit_id=self.old.pk,
                proposal_token=preview['proposal_token'], confirmed=True).visit.pk
        rows = self.race(call)
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(Visit.objects.count(), 2)
        self.assertEqual(AuditEvent.objects.filter(event_type='VISIT_RESCHEDULED').count(), 1)

    def test_competing_booking_and_confirmation_share_resource_locks(self):
        preview = self.preview()
        def call(index):
            try:
                if index == 0:
                    confirm_reschedule(actor=self.actor(self.front), visit_id=self.old.pk,
                        proposal_token=preview['proposal_token'], confirmed=True)
                else:
                    create_appointment(actor=self.actor(self.front2), patient_no=self.p2.patient_no, slot_id=self.slot1.pk,
                        start=self.t+timedelta(hours=1), end=self.t+timedelta(hours=2))
                return ('ok', index)
            except RuleError: return ('conflict', index)
        rows = self.race(call)
        self.assertEqual(sorted(row[0] for row in rows), ['conflict', 'ok'])
        self.assertEqual(Visit.objects.count(), 2)
        self.old.refresh_from_db()
        self.assertEqual(self.old.status, 'RESCHEDULED' if ('ok',0) in rows else 'SCHEDULED')
