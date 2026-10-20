"""Business follow-up acceptance against real PostgreSQL and HTTP role boundaries."""
from datetime import datetime, timedelta, timezone as utc
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import Client, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment
from care.models import CorrectionRequest, Invoice, AuditEvent
from coordination import services as coordination
from coordination.models import CoordinationTask, WaitOffer, WaitRequest
from finance.models import Quarter
from finance.selectors import quarter_report, quarter_worklist
from scheduling.models import AvailabilitySlot, Visit
from scheduling.worklists import day_bounds, filtered_visits
from tests.test_v05 import V05Fixture
from tests.test_v07 import V07Fixture
from workspaces.models import WorkspaceContext
from workspaces.worklists import workspace_worklist


class BusinessFixture(V05Fixture, V07Fixture):
    def setup_business(self):
        self.setup05()
        self.c = Client()
        self.now = timezone.now()

    def attach(self, user, role, clinic=None):
        user._adc_workspace = WorkspaceContext.objects.create(user=user, role=role, clinic=clinic)
        return user

    def worklist(self, user, role, clinic=None):
        self.attach(user, role, clinic)
        with patch('workspaces.worklists.timezone.now', return_value=self.now):
            return workspace_worklist(user)

    def groups(self, result):
        return {row['key']: row for row in result['groups']}

    def visit_at(self, start, *, clinic=None, dentist=None, patient=None, status='SCHEDULED', attended_at=None):
        clinic, dentist, patient = clinic or self.a, dentist or self.d1, patient or self.p1
        end = start + timedelta(minutes=10)
        slot = AvailabilitySlot.objects.create(clinic=clinic, dentist=dentist, starts_at=start, ends_at=end)
        checked = status == 'CHECKED_IN'
        return Visit.objects.create(clinic=clinic, dentist=dentist, patient=patient, availability_slot=slot,
            scheduled_start=start, scheduled_end=end, status=status, attended=checked,
            attended_at=(attended_at or start) if checked else None)

    def offered(self):
        entry = coordination.join_waitlist(actor=self.pa, clinic_id=self.a.pk,
            earliest=self.t, latest=self.t + timedelta(hours=2))
        plan = coordination.create_plan(actor=self.front, clinic_id=self.a.pk)
        coordination.publish_plan(actor=self.front, plan_id=plan.pk)
        return entry, plan, WaitOffer.objects.get(request=entry)


class WorkspaceWorklistTests(BusinessFixture, TransactionTestCase):
    def setUp(self): self.setup_business()

    def test_current_clinic_counts_exclude_other_granted_clinic(self):
        a = self.visit_at(self.now - timedelta(days=2))
        self.visit_at(self.now - timedelta(days=1), clinic=self.b, dentist=self.d2, patient=self.p2)
        result = self.groups(self.worklist(self.front, 'FRONT_DESK', self.a))['outcome']
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['url'], reverse('visit_detail', args=[a.pk]))

    def test_dentist_queue_includes_old_unclosed_care_only_for_self(self):
        own = self.visit_at(self.now - timedelta(days=3), status='CHECKED_IN')
        self.visit_at(self.now - timedelta(days=2), status='CHECKED_IN', clinic=self.b, dentist=self.d2, patient=self.p2)
        result = self.groups(self.worklist(self.doctor, 'DENTIST'))['care']
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['url'], reverse('care_workspace', args=[own.pk]))

    def test_preview_is_bounded_but_total_is_exact(self):
        for n in range(8): self.visit_at(self.now - timedelta(days=2) + timedelta(minutes=15*n))
        result = self.groups(self.worklist(self.front, 'FRONT_DESK', self.a))['outcome']
        self.assertEqual(result['total'], 8)
        self.assertEqual(len(result['items']), 5)

    def test_reads_do_not_infer_no_show_or_emit_audit(self):
        visit = self.visit_at(self.now - timedelta(days=1))
        before = AuditEvent.objects.count()
        self.worklist(self.front, 'FRONT_DESK', self.a)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'SCHEDULED')
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_manager_home_contains_aggregate_but_no_patient_identifiers(self):
        visit = self.visit_at(self.now - timedelta(days=1))
        self.login(self.manager, 'MANAGER', self.a)
        response = self.c.get(reverse('manager_home'))
        self.assertContains(response, '到期结果待核实')
        self.assertNotContains(response, self.p1.name)
        self.assertNotContains(response, self.p1.patient_no)
        self.assertNotContains(response, visit.visit_no)
        self.assertNotContains(response, '当前没有这些清单中的待办')

    def test_active_role_does_not_combine_finance_with_frontdesk(self):
        RoleAssignment.objects.create(user=self.fin, role='FRONT_DESK', scope_kind='CLINIC', clinic=self.a)
        self.visit_at(self.now - timedelta(days=1))
        result = self.worklist(self.fin, 'FINANCE')
        self.assertNotIn('outcome', self.groups(result))
        self.assertEqual(result['cards'], [])

    def test_technical_home_has_no_business_read_projection(self):
        self.visit_at(self.now - timedelta(days=1))
        result = self.worklist(self.tech, 'SYSADMIN')
        self.assertEqual(result['groups'], [])
        self.assertEqual(result['cards'], [])

    def test_unselected_clinic_refused(self):
        self.attach(self.front, 'FRONT_DESK')
        with self.assertRaises(PermissionDenied): workspace_worklist(self.front)

    def test_revoked_grant_refused(self):
        self.attach(self.front, 'FRONT_DESK', self.a)
        RoleAssignment.objects.filter(user=self.front, clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied): workspace_worklist(self.front)

    def test_stale_context_refused(self):
        self.attach(self.front, 'FRONT_DESK', self.a)
        WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(revision=1, clinic=self.b)
        with self.assertRaises(PermissionDenied): workspace_worklist(self.front)
        with self.assertRaises(PermissionDenied): filtered_visits(self.front, {'queue': 'all'})

    def test_readonly_instance_can_read_worklist(self):
        self.visit_at(self.now - timedelta(days=1))
        self.login(self.front, 'FRONT_DESK', self.a)
        with override_settings(ADC_READ_ONLY=True):
            self.assertContains(self.c.get(reverse('frontdesk_home')), '到期预约结果待核实')

    def test_frontdesk_queries_do_not_grow_per_preview_row(self):
        self.visit_at(self.now - timedelta(days=2))
        self.attach(self.front, 'FRONT_DESK', self.a)
        with CaptureQueriesContext(connection) as one: workspace_worklist(self.front)
        for n in range(1, 5): self.visit_at(self.now - timedelta(days=2) + timedelta(minutes=15*n))
        with CaptureQueriesContext(connection) as many: workspace_worklist(self.front)
        self.assertEqual(len(one), len(many))


class VisitWorklistFilterTests(BusinessFixture, TransactionTestCase):
    def setUp(self): self.setup_business()

    def test_china_day_is_half_open_at_utc_boundary(self):
        day = datetime(2026, 10, 14).date()
        start, end = day_bounds(day)
        self.assertEqual(start.astimezone(utc.utc), datetime(2026, 10, 13, 16, tzinfo=utc.utc))
        first = self.visit_at(start)
        self.visit_at(end)
        self.attach(self.front, 'FRONT_DESK', self.a)
        self.assertEqual(list(filtered_visits(self.front, {'day': day}).values_list('pk', flat=True)), [first.pk])

    def test_exact_end_time_is_unresolved(self):
        visit = self.visit_at(self.now - timedelta(minutes=10))
        self.attach(self.front, 'FRONT_DESK', self.a)
        self.assertEqual(list(filtered_visits(self.front, {'queue': 'outcome'}, self.now)), [visit])

    def test_today_arrival_excludes_overdue_and_checked_in(self):
        self.now = datetime(2026, 10, 14, 2, tzinfo=utc.utc)
        self.visit_at(self.now - timedelta(hours=1))
        upcoming = self.visit_at(self.now + timedelta(hours=1))
        self.visit_at(self.now + timedelta(hours=2), status='CHECKED_IN')
        self.attach(self.front, 'FRONT_DESK', self.a)
        self.assertEqual(list(filtered_visits(self.front, {'queue': 'arrival'}, self.now)), [upcoming])

    def test_dentist_can_search_only_own_patient(self):
        own = self.visit_at(self.now - timedelta(days=1))
        self.attach(self.doctor, 'DENTIST')
        self.assertEqual(list(filtered_visits(self.doctor, {'q': self.p1.name})), [own])
        self.assertFalse(filtered_visits(self.doctor, {'q': self.p2.name}).exists())

    def test_manager_cannot_search_by_patient_name_or_number(self):
        visit = self.visit_at(self.now - timedelta(days=1))
        self.attach(self.manager, 'MANAGER', self.a)
        self.assertFalse(filtered_visits(self.manager, {'q': self.p1.name}).exists())
        self.assertFalse(filtered_visits(self.manager, {'q': self.p1.patient_no}).exists())
        self.assertEqual(list(filtered_visits(self.manager, {'q': visit.visit_no})), [visit])

    def test_manager_list_never_fetches_patient_columns(self):
        self.visit_at(self.now - timedelta(days=1))
        self.login(self.manager, 'MANAGER', self.a)
        with CaptureQueriesContext(connection) as captured:
            response = self.c.get(reverse('visits'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.p1.name)
        visit_selects = [q['sql'] for q in captured if q['sql'].startswith('SELECT') and 'adc_visit' in q['sql']]
        self.assertTrue(visit_selects)
        self.assertTrue(all('adc_patient' not in sql for sql in visit_selects))

    def test_invalid_filter_returns_400_without_unfiltered_data(self):
        self.visit_at(self.now - timedelta(days=1))
        self.login(self.front, 'FRONT_DESK', self.a)
        for query in ({'queue': 'invented'}, {'day': 'bad-date'}, {'status': 'invented'}, {'q': 'x'*81}):
            response = self.c.get(reverse('visits'), query)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, self.p1.name, status_code=400)

    def test_pagination_preserves_queue_status_and_search(self):
        for n in range(21): self.visit_at(self.now - timedelta(days=2) + timedelta(minutes=15*n))
        self.login(self.front, 'FRONT_DESK', self.a)
        response = self.c.get(reverse('visits'), {'queue': 'outcome', 'status': 'SCHEDULED', 'q': self.p1.patient_no})
        self.assertContains(response, 'page=2&amp;queue=outcome&amp;status=SCHEDULED&amp;q=')
        page2 = self.c.get(reverse('visits'), {'queue': 'outcome', 'status': 'SCHEDULED', 'q': self.p1.patient_no, 'page': '2'})
        self.assertEqual(len(page2.context['rows']), 1)


class FinancialWorklistTests(BusinessFixture, TransactionTestCase):
    def setUp(self): self.setup_business()

    def test_unconfirmed_zero_is_blocked_until_explicit_confirmation(self):
        quarter = self.make_quarter()
        cost = self.member(quarter)
        self.savecost(quarter, cost, '0', '0')
        self.roster(quarter)
        row = quarter_worklist(self.fin)['quarters'][0]
        self.assertFalse(row['ready'])
        self.assertEqual(row['unconfirmed_costs'], 1)
        self.confirmcost(quarter, cost)
        self.assertTrue(quarter_worklist(self.fin)['quarters'][0]['ready'])

    def test_empty_roster_is_still_blocked(self):
        quarter = self.make_quarter()
        row = quarter_worklist(self.fin)['quarters'][0]
        self.assertFalse(row['ready'])
        self.assertIn('纳入清单为空，不能推断为全链零成本', row['reasons'])

    def test_invoice_dentist_off_roster_blocks_completeness(self):
        quarter = self.make_quarter()
        cost = self.member(quarter, self.d2)
        self.savecost(quarter, cost, '0', '0'); self.confirmcost(quarter, cost); self.roster(quarter)
        # A new billed dentist can appear after the scope was confirmed.
        self.billed()
        row = quarter_worklist(self.fin)['quarters'][0]
        self.assertEqual(row['unlisted_dentists'], 1)
        self.assertFalse(row['ready'])
        self.assertEqual(row['reasons'], quarter_report(self.fin, quarter.pk).result.reasons)

    def test_ready_matches_financial_report_and_current_correction(self):
        visit, invoice, request = self.correction()
        quarter = self.make_quarter(); cost = self.member(quarter)
        self.savecost(quarter, cost); self.confirmcost(quarter, cost); self.roster(quarter)
        from care.corrections import review_correction
        review_correction(actor=self.fin, request_id=request.pk, decision='approve', reason='已独立核对一单位')
        report = quarter_report(self.fin, quarter.pk)
        self.assertEqual(str(report.result.income), '99.99')
        self.assertEqual(quarter_worklist(self.fin)['quarters'][0]['ready'], report.result.ready)

    def test_finance_worklist_excludes_same_account_request(self):
        visit, invoice, request = self.correction()
        RoleAssignment.objects.create(user=self.doctor, role='FINANCE', scope_kind='CHAIN')
        result = self.groups(self.worklist(self.doctor, 'FINANCE'))['corrections']
        self.assertEqual(result['total'], 0)
        self.login(self.doctor, 'FINANCE')
        response = self.c.get(reverse('corrections'), {'queue': 'review'})
        self.assertEqual(response.context['page'].paginator.count, 0)

    def test_finance_link_opens_pending_independent_review(self):
        visit, invoice, request = self.correction()
        result = self.groups(self.worklist(self.fin, 'FINANCE'))['corrections']
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['url'], reverse('correction_detail', args=[request.pk]))
        self.login(self.fin, 'FINANCE')
        self.assertContains(self.c.get(result['items'][0]['url']), '审核决定')

    def test_front_cannot_query_quarter_worklist(self):
        with self.assertRaises(PermissionDenied): quarter_worklist(self.front)

    def test_hq_reads_completeness_without_write_forms_or_patient_identity(self):
        self.billed(); self.make_quarter(); self.login(self.hq, 'HQ')
        response = self.c.get(reverse('finance_quarters'))
        self.assertContains(response, '待补齐，暂不发布总体利润')
        self.assertNotContains(response, self.p1.name)
        self.assertNotContains(response, 'name="action"')

    def test_recent_quarter_scope_is_explicit_and_complete_list_is_paginated(self):
        for year in range(2018, 2025): Quarter.objects.create(year=year, quarter_no=1)
        result = self.groups(self.worklist(self.fin, 'FINANCE'))['quarters']
        self.assertEqual(result['total'], 6)
        self.assertIn('最近 6 个', result['note'])
        self.assertEqual(quarter_worklist(self.fin)['page'].paginator.count, 7)


class PatientAndCoordinationWorklistTests(BusinessFixture, TransactionTestCase):
    def setUp(self): self.setup_business()

    def test_live_offer_is_visible_and_get_does_not_accept(self):
        entry, plan, offer = self.offered()
        self.login(self.pa, 'PATIENT')
        before = Visit.objects.count()
        response = self.c.get(reverse('portal_home'))
        self.assertContains(response, reverse('wait_offer', args=[offer.pk]))
        self.assertEqual(Visit.objects.count(), before)
        offer.refresh_from_db(); self.assertEqual(offer.state, 'PENDING')

    def test_patient_does_not_see_another_patients_offer(self):
        entry, plan, offer = self.offered()
        result = self.groups(self.worklist(self.pb, 'PATIENT'))
        self.assertEqual(result['offers']['total'], 0)

    def test_paused_slot_does_not_hide_an_existing_valid_offer(self):
        entry, plan, offer = self.offered()
        AvailabilitySlot.objects.filter(pk=offer.slot_id).update(booking_paused=True, intake_revision=1)
        self.assertEqual(self.groups(self.worklist(self.pa, 'PATIENT'))['offers']['total'], 1)

    def test_expired_offer_is_not_shown_as_answerable_or_recycled_on_get(self):
        entry, plan, offer = self.offered()
        WaitOffer.objects.filter(pk=offer.pk).update(expires_at=self.now)
        result = self.groups(self.worklist(self.pa, 'PATIENT'))
        self.assertEqual(result['offers']['total'], 0)
        self.assertEqual(result['wait_review']['total'], 1)
        offer.refresh_from_db(); entry.refresh_from_db()
        self.assertEqual(offer.state, 'PENDING'); self.assertEqual(entry.state, 'OFFERED')

    def test_frontdesk_expired_count_stays_in_current_clinic(self):
        entry, plan, offer = self.offered()
        WaitOffer.objects.filter(pk=offer.pk).update(expires_at=self.now)
        result = self.worklist(self.front, 'FRONT_DESK', self.b)
        self.assertEqual(next(c for c in result['cards'] if c['label']=='过期邀约待回收')['count'], 0)

    def test_patient_billing_links_are_owner_only_and_current_version(self):
        visit, invoice, request = self.correction()
        from care.corrections import review_correction
        review_correction(actor=self.fin, request_id=request.pk, decision='approve', reason='独立核对')
        own = self.groups(self.worklist(self.pa, 'PATIENT'))['invoices']
        other = self.groups(self.worklist(self.pb, 'PATIENT'))['invoices']
        self.assertIn('99.99', own['items'][0]['detail'])
        self.assertEqual(own['items'][0]['url'], reverse('portal_invoice', args=[invoice.pk]))
        self.assertEqual(other['total'], 0)

    def test_paused_without_active_task_shows_separate_maintenance_link(self):
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=True, intake_revision=1)
        group = self.groups(self.worklist(self.front, 'FRONT_DESK', self.a))['paused']
        self.assertEqual(group['total'], 1)
        self.assertEqual(group['items'][0]['url'], reverse('availability_detail', args=[self.slot1.pk]))
        self.slot1.refresh_from_db(); self.assertTrue(self.slot1.booking_paused)

    def test_open_task_counts_exclude_other_clinic_and_maintenance_queue(self):
        from uuid import uuid4
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(booking_paused=True, intake_revision=1)
        CoordinationTask.objects.create(slot=self.slot1, purpose='DEACTIVATE', opening_reason='PLAN_CHANGE',
            creation_operation=uuid4(), created_by=self.manager)
        own = self.groups(self.worklist(self.front, 'FRONT_DESK', self.a))
        other = self.groups(self.worklist(self.front2, 'FRONT_DESK', self.b))
        self.assertEqual(own['unclaimed']['total'], 1)
        self.assertEqual(other['unclaimed']['total'], 0)
        self.assertEqual(self.groups(self.worklist(self.front, 'FRONT_DESK', self.a))['paused']['total'], 0)

    def test_manager_never_gets_self_submitted_review_task(self):
        from uuid import uuid4
        RoleAssignment.objects.create(user=self.manager, role='FRONT_DESK', scope_kind='CLINIC', clinic=self.a)
        CoordinationTask.objects.create(slot=self.slot1, purpose='DEACTIVATE', opening_reason='PLAN_CHANGE',
            creation_operation=uuid4(), created_by=self.manager, state='READY', assignee=self.manager,
            submitted_by=self.manager, submitted_at=self.now, submitted_digest='a'*64)
        self.assertEqual(self.groups(self.worklist(self.manager, 'MANAGER', self.a))['review']['total'], 0)
