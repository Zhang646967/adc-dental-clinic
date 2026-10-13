"""New real DB acceptance cases. Authored; not executed without PostgreSQL."""
from datetime import timedelta
from unittest.mock import patch
from django.test import TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.db import OperationalError
from django.utils import timezone
from tests.test_v07 import V07Fixture
from coordination import services as co
from coordination.models import WaitRequest, WaitOffer
from scheduling.models import Visit
from portal.services import cancel_booking
from care.models import AuditEvent
from accounts.models import RoleAssignment
from workspaces.models import WorkspaceContext
from workspaces.context import token_for
from guidance.result_selectors import load_wait_fact

class ResultAcceptanceTests(V07Fixture, TransactionTestCase):
    def setUp(self): self.setup07()
    def check(self,e):return self.post('guide_result_wait',args=[e.pk])
    def test_patient_waiting(self):
        e=self.join();self.login(self.pa,'PATIENT');self.assertContains(self.check(e),'data-result-code="WAITING"')
    def test_explicit_check_does_not_accept_pending(self):
        e,p,o=self.offered();self.login(self.pa,'PATIENT');n=AuditEvent.objects.count()
        self.assertContains(self.check(e),'data-result-code="NEEDS_CONFIRMATION"');o.refresh_from_db()
        self.assertEqual(o.state,'PENDING');self.assertFalse(Visit.objects.exists());self.assertEqual(AuditEvent.objects.count(),n)
    def test_booked_links_exact_visit(self):
        e,p,o=self.offered();co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True);o.refresh_from_db()
        self.login(self.pa,'PATIENT');r=self.check(e)
        self.assertContains(r,o.visit.visit_no);self.assertContains(r,reverse('portal_visit',args=[o.visit_id]))
    def test_accepted_after_deadline_still_links_booking(self):
        e,p,o=self.offered();co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True);self.login(self.pa,'PATIENT')
        with patch('guidance.result_views.timezone.now',return_value=o.expires_at+timedelta(seconds=1)):
            self.assertContains(self.check(e),'data-result-code="BOOKING_FOUND"')
    def test_later_cancel_is_not_active_booking(self):
        e,p,o=self.offered();co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True);o.refresh_from_db()
        cancel_booking(actor=self.pa,visit_id=o.visit_id,expected_version=o.visit.lock_version,reason='演示取消')
        self.login(self.pa,'PATIENT');self.assertContains(self.check(e),'data-result-code="BOOKING_CANCELLED"')
    def test_expired_pending_is_not_accepted(self):
        e,p,o=self.offered();self.login(self.pa,'PATIENT')
        with patch('guidance.result_views.timezone.now',return_value=o.expires_at):
            self.assertContains(self.check(e),'data-result-code="OFFER_EXPIRED"')
        o.refresh_from_db();self.assertEqual(o.state,'PENDING');self.assertFalse(Visit.objects.exists())
    def test_wrong_patient_same_404_as_missing(self):
        e=self.join();self.login(self.pb,'PATIENT')
        self.assertEqual(self.check(e).status_code,404)
        self.assertEqual(self.post('guide_result_wait',args=[99999999]).status_code,404)
    def test_frontdesk_scope_enforced(self):
        e=self.join();self.login(self.front,'FRONT_DESK',self.b);self.assertEqual(self.check(e).status_code,404)
    def test_frontdesk_own_clinic(self):
        e=self.join();self.login(self.front,'FRONT_DESK',self.a);self.assertEqual(self.check(e).status_code,200)
    def test_manager_forbidden_despite_list_access(self):
        e=self.join();self.login(self.manager,'MANAGER',self.a);self.assertEqual(self.check(e).status_code,403)
    def test_doctor_forbidden(self):
        e=self.join();self.login(self.doctor,'DENTIST');self.assertEqual(self.check(e).status_code,403)
    def test_old_scope_token_rejected(self):
        e=self.join();self.login(self.front,'FRONT_DESK',self.a);old=token_for(self.ctx())
        self.post('activate_clinic',{'clinic':self.b.pk})
        r=self.c.post(reverse('guide_result_wait',args=[e.pk]),{'workspace_token':old});self.assertEqual(r.status_code,409)
    def test_revoked_patient_binding_rejected(self):
        e=self.join();self.login(self.pa,'PATIENT');self.access.is_active=False;self.access.save()
        self.assertEqual(self.check(e).status_code,409)
    def test_context_switch_during_read_suppresses_result(self):
        e,p,o=self.offered();self.login(self.pa,'PATIENT');original=load_wait_fact
        def switched(*args):
            result=original(*args);ctx=self.ctx();WorkspaceContext.objects.filter(pk=ctx.pk).update(revision=ctx.revision+1);return result
        with patch('guidance.result_views.load_wait_fact',side_effect=switched):
            r=self.check(e);self.assertEqual(r.status_code,409);self.assertNotContains(r,'NEEDS_CONFIRMATION',status_code=409)
    def test_database_error_does_not_claim_booking_failed(self):
        e=self.join();self.login(self.pa,'PATIENT')
        with patch('guidance.result_views.load_wait_fact',side_effect=OperationalError('private database detail')):
            r=self.check(e);self.assertContains(r,'不代表之前的确认失败',status_code=503)
            self.assertNotContains(r,'private database detail',status_code=503)
    def test_no_store_on_success(self):
        e=self.join();self.login(self.pa,'PATIENT');self.assertIn('no-store',self.check(e)['Cache-Control'])
    def test_no_store_on_unavailable(self):
        e=self.join();self.login(self.pa,'PATIENT')
        with patch('guidance.result_views.load_wait_fact',side_effect=OperationalError()):
            self.assertIn('no-store',self.check(e)['Cache-Control'])
    def test_get_is_not_supported(self):
        e=self.join();self.login(self.pa,'PATIENT');self.assertEqual(self.c.get(reverse('guide_result_wait',args=[e.pk])).status_code,405)
    def test_post_needs_csrf(self):
        e=self.join();self.login(self.pa,'PATIENT');strict=Client(enforce_csrf_checks=True)
        strict.cookies=self.c.cookies
        self.assertEqual(strict.post(reverse('guide_result_wait',args=[e.pk]),{'workspace_token':token_for(self.ctx())}).status_code,403)
    def test_read_only_mode_allows_check(self):
        e=self.join();self.login(self.pa,'PATIENT')
        with override_settings(ADC_READ_ONLY=True):self.assertEqual(self.check(e).status_code,200)
    def test_repeated_checks_do_not_change_business(self):
        e,p,o=self.offered();co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True);self.login(self.pa,'PATIENT')
        before=(Visit.objects.count(),AuditEvent.objects.count(),list(WaitRequest.objects.values()),list(WaitOffer.objects.values()))
        self.check(e);self.check(e)
        after=(Visit.objects.count(),AuditEvent.objects.count(),list(WaitRequest.objects.values()),list(WaitOffer.objects.values()))
        self.assertEqual(before,after)
