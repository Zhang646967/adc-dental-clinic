"""Authored integration tests. Require PostgreSQL; execution NOT performed in source delivery."""
from datetime import timedelta
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction, connection
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent, Invoice, VisitRecordVersion
from scheduling.models import Visit
from scheduling.services import change_appointment, reschedule
from patients.selectors import visible_patients
from patients.models import Patient
from finance.models import Quarter, DentistQuarterCost
from tests.fixtures import FixtureMixin

class BusinessIntegrationTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql',"SQLite does not satisfy these tests")
        self.make_fixture()
    def test_create_appointment_and_event(self):
        v=self.book()
        self.assertEqual(v.status,'SCHEDULED')
        self.assertFalse(v.attended)
        self.assertEqual(AuditEvent.objects.filter(visit=v,event_type='VISIT_CREATED').count(),1)
    def test_dentist_double_booking_rejected(self):
        self.book()
        with self.assertRaises(RuleError): self.book(patient_no=self.p2.patient_no)
        self.assertEqual(Visit.objects.count(),1)
    def test_patient_cross_clinic_overlap_rejected(self):
        self.book()
        with self.assertRaises(RuleError): self.book(slot_id=self.slot2.pk)
    def test_adjacent_booking_accepted(self):
        self.book()
        self.book(start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2))
        self.assertEqual(Visit.objects.count(),2)
    def test_outside_slot_is_rejected(self):
        with self.assertRaises(RuleError): self.book(end=self.t+timedelta(hours=5))
    def test_audit_failure_rolls_back_booking(self):
        with patch('scheduling.services.emit',side_effect=RuntimeError('injected failure')):
            with self.assertRaises(RuntimeError): self.book()
        self.assertFalse(Visit.objects.exists())
    def test_check_in_keeps_time_consistent(self):
        v=self.book()
        result=change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        self.assertTrue(result.attended)
        self.assertIsNotNone(result.attended_at)
        self.assertIsNone(result.completed_at)
    def test_early_no_show_rejected(self):
        v=self.book()
        with self.assertRaises(RuleError): change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='no_show',reason='测试')
    def test_cancellation_reason_required(self):
        v=self.book()
        with self.assertRaises(RuleError): change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',party='PATIENT')
    def test_cancellation_does_not_generate_invoice(self):
        v=self.book()
        change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',party='PATIENT',reason='演示原因')
        self.assertFalse(Invoice.objects.exists())
    def test_stale_version_rejected(self):
        v=self.book()
        change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',party='PATIENT',reason='演示原因')
        with self.assertRaises(RuleError): change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
    def test_reschedule_keeps_predecessor(self):
        old=self.book()
        new=reschedule(actor=self.front,visit_id=old.pk,expected_version=0,new_slot_id=self.slot1.pk,start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2),reason='演示改期')
        old.refresh_from_db()
        self.assertEqual(old.status,'RESCHEDULED')
        self.assertEqual(new.replaces_visit_id,old.pk)
        self.assertEqual(Visit.objects.count(),2)
    def test_failed_reschedule_restores_original(self):
        old=self.book()
        self.book(patient_no=self.p2.patient_no,start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2))
        with self.assertRaises(RuleError): reschedule(actor=self.front,visit_id=old.pk,expected_version=0,new_slot_id=self.slot1.pk,start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2),reason='冲突改期')
        old.refresh_from_db()
        self.assertEqual(old.status,'SCHEDULED')
        self.assertEqual(old.lock_version,0)
    def test_database_rejects_false_attendance(self):
        v=self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Visit.objects.filter(pk=v.pk).update(attended=True)
    def test_database_rejects_closed_without_invoice(self):
        v=self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Visit.objects.filter(pk=v.pk).update(status='COMPLETED',attended=True,attended_at=self.t,completed_at=self.t)
    def test_database_rejects_unlinked_rescheduled_state(self):
        v=self.book()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Visit.objects.filter(pk=v.pk).update(status='RESCHEDULED')
    def test_database_prevents_audit_rewrite(self):
        self.book()
        with self.assertRaises(IntegrityError),transaction.atomic(): AuditEvent.objects.update(reason='overwrite')
    def test_cost_missing_is_not_zero(self):
        q=Quarter.objects.create(year=2026,quarter_no=3)
        c=DentistQuarterCost.objects.create(quarter=q,dentist=self.d1)
        self.assertIsNone(c.supply_cost)
        self.assertIsNone(c.operating_expense)
    def test_database_rejects_incomplete_cost_confirmation(self):
        q=Quarter.objects.create(year=2026,quarter_no=3)
        with self.assertRaises(IntegrityError),transaction.atomic():
            DentistQuarterCost.objects.create(quarter=q,dentist=self.d1,cost_status='CONFIRMED')
    def test_technical_superuser_no_business_bypass(self):
        with self.assertRaises(PermissionDenied): self.book(actor=self.tech)
        self.assertFalse(visible_patients(self.tech).exists())
    def test_role_scope_does_not_cross_combine(self):
        RoleAssignment.objects.filter(user=self.manager,clinic=self.a).delete()
        RoleAssignment.objects.create(user=self.manager,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        with self.assertRaises(PermissionDenied): self.book(actor=self.manager,slot_id=self.slot2.pk)
    def test_revoked_role_blocks_stale_page_submit(self):
        RoleAssignment.objects.filter(user=self.front).update(is_active=False)
        with self.assertRaises(PermissionDenied): self.book()
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_also_blocks_service_call(self):
        with self.assertRaises(PermissionDenied): self.book()
    def test_login_is_required(self):
        self.assertEqual(self.client.get(reverse('visits')).status_code,302)
    def test_direct_patient_url_scope_enforced(self):
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse('patient_detail',args=[self.p1.pk])).status_code,403)
    def test_dashboard_template_renders(self):
        self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse('dashboard')).status_code,200)
    def test_unauthorized_get_cannot_mutate(self):
        self.book()
        self.client.force_login(self.tech)
        self.assertEqual(self.client.get(reverse('visit_create')).status_code,403)
        self.assertEqual(Visit.objects.count(),1)
    def test_post_requires_csrf(self):
        from django.test import Client
        c=__import__("tests.workspace_client",fromlist=["WorkspaceClient"]).WorkspaceClient(enforce_csrf_checks=True)
        c.force_login(self.front)
        self.assertEqual(c.post(reverse('patient_create'),{}).status_code,403)
