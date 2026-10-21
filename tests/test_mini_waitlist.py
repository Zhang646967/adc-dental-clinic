"""Native waitlist and website share PostgreSQL facts and coordination commands."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from django.db import connection, close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from care.models import AuditEvent, Invoice
from coordination.models import WaitRequest, WaitOffer
from coordination.services import create_plan, publish_plan, answer_offer, withdraw
from finance.cash_models import CashEntry
from portal.models import PatientAccess
from scheduling.models import Visit
from scheduling.resource_models import ResourceClaim, BookingService
from tests.test_reception_resources import ResourceFixture
from tests import test_mini_program as base


class MiniWaitlistTests(ResourceFixture, TransactionTestCase):
    setUp = base.MiniProgramTests.setUp
    login = base.MiniProgramTests.login
    post = base.MiniProgramTests.post
    preview = base.MiniProgramTests.preview
    book = base.MiniProgramTests.book

    def join_preview(self, **changes):
        data = dict(clinic=self.a.pk, service=self.service.pk, earliest=self.t.isoformat(),
            latest=(self.t+timedelta(hours=8)).isoformat())
        data.update(changes)
        return self.post('mini_wait_join_preview', data)

    def join(self):
        token = self.join_preview().json()['data']['proposal_token']
        r = self.post('mini_wait_join_confirm', dict(proposal_token=token, confirmed='on'))
        self.assertEqual(r.status_code, 200, r.content)
        return WaitRequest.objects.get(pk=r.json()['data']['wait']['id']), token

    def offered(self):
        e, _ = self.join()
        p = create_plan(actor=self.front, clinic_id=self.a.pk)
        publish_plan(actor=self.front, plan_id=p.pk)
        return WaitOffer.objects.get(request=e)

    def action_token(self, o, action='accept'):
        r = self.post('mini_offer_preview', dict(action=action), pk=o.pk)
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()['data']['proposal_token']

    def test_join_preview_does_not_create_wait_or_occupancy(self):
        count = AuditEvent.objects.count()
        self.assertEqual(self.join_preview().status_code, 200)
        self.assertFalse(WaitRequest.objects.exists()); self.assertFalse(Visit.objects.exists())
        self.assertFalse(ResourceClaim.objects.exists()); self.assertEqual(AuditEvent.objects.count(), count)

    def test_join_explicit_confirmation_and_patient_injection(self):
        p = self.join_preview().json()['data']['proposal_token']
        self.assertEqual(self.post('mini_wait_join_confirm', {'proposal_token':p}).status_code, 409)
        r = self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on', patient_id=self.p2.pk, clinic=self.b.pk))
        self.assertEqual(r.status_code, 200, r.content)
        e = WaitRequest.objects.get(); self.assertEqual((e.patient_id,e.clinic_id), (self.p1.pk,self.a.pk))
        self.assertFalse(Visit.objects.exists()); self.assertFalse(Invoice.objects.exists()); self.assertFalse(CashEntry.objects.exists())

    def test_registration_replay_after_withdraw_does_not_revive(self):
        e, p = self.join()
        withdraw(actor=self.front, entry_id=e.pk)
        r = self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on'))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['data']['wait']['state'], 'WITHDRAWN')
        self.assertEqual(WaitRequest.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(event_type='MINI_WAIT_REGISTERED').count(), 1)

    def test_two_previews_only_first_creates_registration(self):
        p = [self.join_preview().json()['data']['proposal_token'] for _ in range(2)]
        codes = [self.post('mini_wait_join_confirm', dict(proposal_token=t, confirmed='on')).status_code for t in p]
        self.assertEqual(codes, [200,409]); self.assertEqual(WaitRequest.objects.count(), 1)

    def test_preview_stale_after_other_channel_registration(self):
        p = self.join_preview().json()['data']['proposal_token']
        from coordination.services import join_waitlist
        join_waitlist(actor=self.front, clinic_id=self.a.pk, patient_no=self.p1.patient_no,
            service_id=self.service.pk, earliest=self.t, latest=self.t+timedelta(hours=8))
        self.assertEqual(self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on')).status_code, 409)
        self.assertEqual(WaitRequest.objects.count(), 1)

    def test_cross_clinic_service_rejected(self):
        self.assertIn(self.join_preview(clinic=self.b.pk).status_code, (404,409))
        self.assertFalse(WaitRequest.objects.exists())

    def test_invalid_window_and_incompatible_dentist(self):
        for change in [dict(latest=(self.t+timedelta(minutes=15)).isoformat()),dict(earliest=timezone.now().isoformat()),dict(dentist=999999)]:
            with self.subTest(change=change):self.assertIn(self.join_preview(**change).status_code, (404,409))
        self.assertFalse(WaitRequest.objects.exists())

    def test_service_change_invalidates_join_confirmation(self):
        p = self.join_preview().json()['data']['proposal_token']
        BookingService.objects.filter(pk=self.service.pk).update(duration_minutes=45)
        self.assertEqual(self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on')).status_code, 409)
        self.assertFalse(WaitRequest.objects.exists())

    def test_revocation_between_preview_and_join(self):
        p = self.join_preview().json()['data']['proposal_token']
        PatientAccess.objects.filter(pk=self.access.pk).update(is_active=False)
        self.assertIn(self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on')).status_code, (403,409))
        self.assertFalse(WaitRequest.objects.exists())

    def test_foreign_patient_cannot_use_registration_preview(self):
        p = self.join_preview().json()['data']['proposal_token']; c,s = self.login(self.other)
        self.assertEqual(self.post('mini_wait_join_confirm',dict(proposal_token=p,confirmed='on'),client=c,session=s).status_code,409)

    def test_waitlist_and_offer_are_own_only(self):
        o = self.offered(); c,_ = self.login(self.other)
        self.assertEqual(c.get(reverse('mini_waitlist')).json()['data']['rows'], [])
        absent = c.get(reverse('mini_offer',kwargs={'pk':999999}))
        foreign = c.get(reverse('mini_offer',kwargs={'pk':o.pk}))
        self.assertEqual((foreign.status_code,foreign.json()['message']), (absent.status_code,absent.json()['message']))

    def test_website_shows_native_wait_and_dashboard_offer(self):
        o = self.offered()
        self.assertContains(self.client.get(reverse('waitlist')), self.a.name)
        self.assertContains(self.client.get(reverse('portal_home')), '有 1 条邀约等待你确认')
        d = self.client.get(reverse('mini_overview')).json()['data']
        self.assertEqual((d['waiting_count'],d['offer_count'],d['active_count']), (1,1,0))

    def test_accept_preview_replay_one_booking_and_current_result(self):
        o = self.offered(); p = self.action_token(o)
        ids = [self.post('mini_offer_confirm',dict(proposal_token=p,confirmed='on'),pk=o.pk).json()['data']['visit']['id'] for _ in range(2)]
        self.assertEqual(ids[0],ids[1]); self.assertEqual(Visit.objects.count(),1)
        self.assertEqual(ResourceClaim.objects.filter(active=True).count(),1)
        self.assertFalse(Invoice.objects.exists()); self.assertFalse(CashEntry.objects.exists())
        self.assertContains(self.client.get(reverse('portal_visit',kwargs={'pk':ids[0]})), self.a.name)

    def test_decline_keeps_waiting_and_existing_appointment(self):
        v = self.book(); o = self.offered(); p = self.action_token(o,'decline')
        r = self.post('mini_offer_confirm',dict(proposal_token=p,confirmed='on'),pk=o.pk)
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(r.json()['data']['wait']['state'],'WAITING')
        v.refresh_from_db(); self.assertEqual(v.status,'SCHEDULED'); self.assertEqual(Visit.objects.count(),1)
        self.assertEqual(ResourceClaim.objects.filter(active=True).count(),1)

    def test_withdraw_preview_stale_after_offer_published(self):
        e,_=self.join()
        p = self.post('mini_wait_withdraw_preview',{},pk=e.pk).json()['data']['proposal_token']
        plan = create_plan(actor=self.front,clinic_id=self.a.pk);publish_plan(actor=self.front,plan_id=plan.pk)
        self.assertEqual(self.post('mini_wait_withdraw_confirm',dict(proposal_token=p,confirmed='on'),pk=e.pk).status_code,409)
        e.refresh_from_db();self.assertEqual(e.state,'OFFERED')

    def test_withdraw_replay_releases_hold_but_keeps_visit(self):
        v=self.book();o=self.offered();p=self.post('mini_wait_withdraw_preview',{},pk=o.request_id).json()['data']['proposal_token']
        for _ in range(2):self.assertEqual(self.post('mini_wait_withdraw_confirm',dict(proposal_token=p,confirmed='on'),pk=o.request_id).status_code,200)
        o.refresh_from_db();v.refresh_from_db();self.assertEqual((o.state,v.status),('REVOKED','SCHEDULED'))
        self.assertEqual(Visit.objects.count(),1);self.assertEqual(ResourceClaim.objects.filter(active=True).count(),1)

    def test_offer_token_cannot_withdraw_or_answer_another_offer(self):
        o=self.offered();p=self.action_token(o)
        self.assertEqual(self.post('mini_wait_withdraw_confirm',dict(proposal_token=p,confirmed='on'),pk=o.request_id).status_code,409)
        self.assertEqual(self.post('mini_offer_confirm',dict(proposal_token=p,confirmed='on'),pk=o.pk+1).status_code,409)
        self.assertFalse(Visit.objects.exists())

    def test_expired_offer_display_and_confirmation(self):
        o=self.offered();p=self.action_token(o)
        WaitOffer.objects.filter(pk=o.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        d=self.client.get(reverse('mini_offer',kwargs={'pk':o.pk})).json()['data']['offer']
        self.assertFalse(d['active']);self.assertIn('到期',d['status_label'])
        self.assertEqual(self.post('mini_offer_confirm',dict(proposal_token=p,confirmed='on'),pk=o.pk).status_code,409)
        self.assertFalse(Visit.objects.exists())

    def test_old_answer_after_frontdesk_declines_rejected(self):
        o=self.offered();p=self.action_token(o)
        answer_offer(actor=self.front,offer_id=o.pk,accept=False)
        self.assertEqual(self.post('mini_offer_confirm',dict(proposal_token=p,confirmed='on'),pk=o.pk).status_code,409)
        self.assertFalse(Visit.objects.exists())

    def test_retained_service_label_survives_catalogue_rename(self):
        visit=self.book();o=self.offered();original=self.service.name
        BookingService.objects.filter(pk=self.service.pk).update(name='课程后续服务目录名称')
        v=self.client.get(reverse('mini_visit',kwargs={'pk':visit.pk})).json()['data']
        offer=self.client.get(reverse('mini_offer',kwargs={'pk':o.pk})).json()['data']['offer']
        self.assertEqual((v['service'],offer['service']),(original,original))

    def test_offer_can_replace_exact_own_source_with_one_successor(self):
        source=self.book();o=self.offered()
        d=self.client.get(reverse('mini_offer',kwargs={'pk':o.pk})).json()['data']
        self.assertEqual([v['id'] for v in d['sources']],[source.pk])
        r=self.post('mini_reschedule_preview',dict(action='preview',expected_version=0,offer_id=o.pk,slot_id=o.slot_id,start=o.starts_at.isoformat(),reason='选择候补提供的新安排'),pk=source.pk)
        self.assertEqual(r.status_code,200,r.content)
        p=r.json()['data']['proposal_token']
        for _ in range(2):
            r=self.post('mini_reschedule_confirm',dict(proposal_token=p,confirmed='on'),pk=source.pk)
            self.assertEqual(r.status_code,200,r.content)
        source.refresh_from_db();o.refresh_from_db();self.assertEqual(source.status,'RESCHEDULED')
        self.assertEqual(o.visit_id,Visit.objects.get(replaces_visit=source).pk)
        self.assertEqual(Visit.objects.count(),2);self.assertEqual(ResourceClaim.objects.filter(active=True).count(),1)
        self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())

    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_waitlist_reads_but_rejects_writes(self):
        self.assertEqual(self.client.get(reverse('mini_waitlist')).status_code,200)
        self.assertEqual(self.join_preview().status_code,403)

    def test_native_writes_still_require_csrf_and_workspace(self):
        path=reverse('mini_wait_join_preview')
        self.assertEqual(self.client.post(path,{},HTTP_X_ADC_WORKSPACE=self.session['workspace_token']).status_code,403)
        self.assertEqual(self.client.post(path,{},HTTP_X_CSRFTOKEN=self.session['csrf_token']).status_code,409)

    def test_concurrent_registration_same_preview_one_effect(self):
        p=self.join_preview().json()['data']['proposal_token'];barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                c=Client(enforce_csrf_checks=True);c.cookies=self.client.cookies.copy();barrier.wait(timeout=10)
                r=self.post('mini_wait_join_confirm',dict(proposal_token=p,confirmed='on'),client=c)
                return r.status_code,r.json()['data']['wait']['id']
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run) for _ in range(2)];results=[f.result(timeout=30) for f in futures]
        self.assertEqual(results[0],results[1]);self.assertEqual(results[0][0],200)
        self.assertEqual(WaitRequest.objects.count(),1)

    def test_concurrent_website_and_native_accept_one_visit(self):
        o=self.offered();p=self.action_token(o);barrier=Barrier(2)
        def run(native):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                if native:
                    c=Client(enforce_csrf_checks=True);c.cookies=self.client.cookies.copy()
                    r=self.post('mini_offer_confirm',dict(proposal_token=p,confirmed='on'),pk=o.pk,client=c)
                    self.assertEqual(r.status_code,200,r.content);return r.json()['data']['visit']['id']
                web=Client(enforce_csrf_checks=True);web.cookies=self.client.cookies.copy()
                r=web.post(reverse('wait_offer',kwargs={'pk':o.pk}),dict(action='accept',confirmed='on',workspace_token=self.session['workspace_token']),HTTP_X_CSRFTOKEN=self.session['csrf_token'])
                self.assertEqual(r.status_code,302,r.content)
                return WaitOffer.objects.get(pk=o.pk).visit_id
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(run,x) for x in (True,False)];ids=[f.result(timeout=30) for f in futures]
        self.assertEqual(ids[0],ids[1]);self.assertEqual(Visit.objects.count(),1)
