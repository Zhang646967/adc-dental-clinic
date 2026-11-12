"""Native patient HTTP contracts on PostgreSQL; no mocked business commands."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from django.db import connection, close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from accounts.models import UserAccount, RoleAssignment
from care.models import Invoice, AuditEvent
from finance.cash_models import CashEntry
from portal.models import PatientAccess, BookingReceipt
from scheduling.models import Visit
from scheduling.resource_models import ResourceBinding, ResourceClaim, ServicePresentation
from scheduling.service_content import draft_from_guide
from tests.test_reception_resources import ResourceFixture
from tests.workspace_client import WorkspaceClient
from workspaces.context import SESSION_KEY
from workspaces.models import WorkspaceContext


class MiniProgramTests(ResourceFixture, TransactionTestCase):
    def setUp(self):
        self.resources()
        self.profile = ServicePresentation.objects.create(service=self.service,
            **dict(draft_from_guide('CHECKUP'), title='本店初诊评估', is_published=True))
        self.password = 'Synthetic-mini-course-2026'
        self.user = UserAccount.objects.create_user(username='mini_patient', password=self.password)
        self.other = UserAccount.objects.create_user(username='mini_other', password=self.password)
        self.access = PatientAccess.objects.create(user=self.user, patient=self.p1)
        PatientAccess.objects.create(user=self.other, patient=self.p2)
        self.client, self.session = self.login(self.user)

    def login(self, user):
        client = Client(enforce_csrf_checks=True)
        data = client.get(reverse('mini_session')).json()['data']
        response = client.post(reverse('mini_login'), {'username': user.username, 'password': self.password},
            HTTP_X_CSRFTOKEN=data['csrf_token'])
        self.assertEqual(response.status_code, 200, response.content)
        return client, response.json()['data']

    def post(self, route, data, *, client=None, session=None, pk=None, **extra):
        client, session = client or self.client, session or self.session
        return client.post(reverse(route, kwargs={'pk': pk} if pk else None), data,
            HTTP_X_CSRFTOKEN=session['csrf_token'], HTTP_X_ADC_WORKSPACE=session['workspace_token'], **extra)

    def preview(self, *, client=None, session=None, slot=None, start=None):
        response = self.post('mini_book_preview', dict(slot=(slot or self.slot1).pk,
            start=(start or self.t).isoformat(), service=self.service.pk), client=client, session=session)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['data']['proposal_token']

    def book(self):
        response = self.post('mini_book_confirm', {'proposal_token': self.preview(), 'confirmed': 'on'})
        self.assertEqual(response.status_code, 200, response.content)
        return Visit.objects.get(pk=response.json()['data']['id'])

    def test_website_booking_native_reschedule_and_frontdesk_arrival(self):
        web = WorkspaceClient()
        web.force_login(self.user)
        url = reverse('portal_confirm')
        params = dict(slot=self.slot1.pk, start=self.t.isoformat(), service=self.service.pk)
        form = web.get(url, params).context['form']
        confirmed = web.post(url, dict(token=form.initial['token'], confirmed='on'))
        self.assertEqual(confirmed.status_code, 302, confirmed.content)
        original = Visit.objects.get()
        self.assertRedirects(confirmed, reverse('portal_visit', args=[original.pk]))

        def overview():
            return self.client.get(reverse('mini_overview')).json()['data']['primary_action']

        self.assertEqual((overview()['kind'], overview()['visit']['id']), ('UPCOMING_VISIT', original.pk))
        p = self.post('mini_reschedule_preview', dict(action='preview', expected_version=0,
            slot_id=self.slot2.pk, start=(self.t+timedelta(hours=1)).isoformat(), reason='更换课程合成时段'), pk=original.pk)
        self.assertEqual(p.status_code, 200, p.content)
        confirm = dict(proposal_token=p.json()['data']['proposal_token'], confirmed='on')
        first = self.post('mini_reschedule_confirm', confirm, pk=original.pk)
        repeated = self.post('mini_reschedule_confirm', confirm, pk=original.pk)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(repeated.status_code, 200, repeated.content)
        visit = Visit.objects.get(replaces_visit=original)
        self.assertEqual(repeated.json()['data']['visit']['id'], visit.pk)
        self.assertContains(web.get(reverse('portal_visit', args=[original.pk])), '查看后继预约')
        self.assertContains(web.get(reverse('portal_visit', args=[visit.pk])), '改期而来')
        self.assertEqual(Visit.objects.count(), 2)

        front = WorkspaceClient()
        front.force_login(self.front)
        worklist = front.get(reverse('frontdesk_home'))
        for label in ('安排待匹配候补', '核对到期邀约', '办理今日到诊', '核实逾期预约结果', '跟进取消回访'):
            self.assertContains(worklist, label)
        checked = front.post(reverse('visit_detail', args=[visit.pk]), dict(action='check_in', expected_version=0))
        self.assertEqual(checked.status_code, 302, checked.content)
        self.assertEqual((overview()['kind'], overview()['visit']['id']), ('CHECKED_IN', visit.pk))
        self.assertEqual(overview()['label'], '已到诊')
        self.assertContains(web.get(reverse('portal_home')), '<h2 id="patient-next-action">已到诊</h2>', html=True)
        other, _ = self.login(self.other)
        self.assertEqual(other.get(reverse('mini_visit', args=[visit.pk])).status_code, 404)
        self.assertEqual(other.get(reverse('mini_overview')).json()['data']['primary_action']['kind'], 'BOOK')

    def test_overdue_appointment_prompts_review_without_inferred_no_show(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        v = self.book()
        at_end = SimpleNamespace(now=lambda: v.scheduled_end)
        with (patch('portal.patient_dashboard.timezone', at_end), patch('portal.mini_api.timezone', at_end),
              patch('portal.views.timezone', at_end)):
            primary = self.client.get(reverse('mini_overview')).json()['data']['primary_action']
            self.assertEqual((primary['kind'], primary['visit']['id']), ('CONTACT_CLINIC', v.pk))
            self.assertTrue(primary['visit']['needs_outcome_review'])
            self.assertContains(self.client.get(reverse('portal_home')), '请联系门店核实')
            self.assertContains(self.client.get(reverse('portal_visit', args=[v.pk])), '请联系门店核实')
        v.refresh_from_db()
        self.assertEqual((v.status, v.attended), ('SCHEDULED', False))

    def test_website_cancellation_is_visible_to_native_and_frontdesk(self):
        v = self.book()
        web = WorkspaceClient()
        web.force_login(self.user)
        url = reverse('portal_cancel', args=[v.pk])
        form = web.get(url).context['form']
        cancelled = web.post(url, dict(expected_version=v.lock_version, confirmed='on',
            patient_authority=form.initial['patient_authority'], reason='课程合成：无法按原时间到店'))
        self.assertRedirects(cancelled, reverse('portal_visit', args=[v.pk]))
        detail = self.client.get(reverse('mini_visit', args=[v.pk])).json()['data']
        self.assertEqual((detail['status'], detail['can_change']), ('CANCELLED', False))
        front = WorkspaceClient()
        front.force_login(self.front)
        self.assertContains(front.get(reverse('cancellation_followups')), v.visit_no)

    def test_bootstrap_is_private_and_has_csrf(self):
        response = Client().get(reverse('mini_session'))
        self.assertFalse(response.json()['data']['authenticated'])
        self.assertIn('csrftoken', response.cookies)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_login_activates_only_patient(self):
        self.assertTrue(self.session['authenticated'])
        ctx = WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        self.assertEqual((ctx.role, ctx.clinic_id), ('PATIENT', None))
        self.assertNotIn('patient_id', self.session)

    def test_login_multi_role_still_patient(self):
        RoleAssignment.objects.create(user=self.user, role='FRONT_DESK', scope_kind='CLINIC', clinic=self.a)
        client, _ = self.login(self.user)
        self.assertEqual(WorkspaceContext.objects.get(pk=client.session[SESSION_KEY]).role, 'PATIENT')
        self.assertEqual(client.get(reverse('availability_list')).status_code, 403)

    def test_wrong_password_and_staff_login_rejected(self):
        c = Client(); c.get(reverse('mini_session'))
        self.assertEqual(c.post(reverse('mini_login'), {'username': self.user.username, 'password': 'wrong'}).status_code, 401)
        others = []
        for role, scope in [('DENTIST','SELF_DENTIST'), ('FINANCE','CHAIN'), ('HQ','CHAIN')]:
            staff = UserAccount.objects.create_user(username='mini_staff_'+role, password=self.password,
                dentist=self.d1 if role == 'DENTIST' else None)
            RoleAssignment.objects.create(user=staff, role=role, scope_kind=scope)
            others.append(staff)
        for staff in (self.front, self.manager, self.tech, *others):
            staff.set_password(self.password); staff.save(update_fields=['password'])
            with self.subTest(user=staff.username):
                self.assertEqual(c.post(reverse('mini_login'), {'username': staff.username, 'password': self.password}).status_code, 403)

    def test_unauthenticated_returns_json_not_redirect(self):
        response = Client().get(reverse('mini_visits'))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'LOGIN_REQUIRED')

    def test_csrf_not_waived_for_login(self):
        response = Client(enforce_csrf_checks=True).post(reverse('mini_login'), {'username': self.user.username, 'password': self.password})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'CSRF_FAILED')

    def test_https_wechat_referer_accepted(self):
        response = self.post('mini_book_preview', dict(slot=self.slot1.pk, start=self.t.isoformat(), service=self.service.pk),
            secure=True, HTTP_REFERER='https://servicewechat.com/wx-course/devtools/page-frame.html')
        self.assertEqual(response.status_code, 200, response.content)

    def test_unrelated_https_origin_rejected(self):
        response = self.post('mini_book_preview', {}, secure=True, HTTP_ORIGIN='https://unrelated.invalid')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'CSRF_FAILED')

    def test_workspace_header_required(self):
        response = self.client.post(reverse('mini_book_preview'), {}, HTTP_X_CSRFTOKEN=self.session['csrf_token'])
        self.assertEqual(response.status_code, 409)

    def test_context_change_invalidates_old_header_and_preview(self):
        token = self.preview()
        WorkspaceContext.objects.filter(pk=self.client.session[SESSION_KEY]).update(revision=9)
        self.assertEqual(self.post('mini_book_confirm', {'proposal_token': token, 'confirmed': 'on'}).status_code, 409)
        self.assertFalse(Visit.objects.exists())

    def test_login_rotates_session_and_csrf(self):
        c = Client(enforce_csrf_checks=True); before = c.get(reverse('mini_session')).json()['data']
        r = c.post(reverse('mini_login'), {'username': self.user.username, 'password': self.password}, HTTP_X_CSRFTOKEN=before['csrf_token'])
        self.assertNotEqual(before['csrf_token'], r.json()['data']['csrf_token'])
        self.assertEqual(c.post(reverse('mini_logout'), {}, HTTP_X_CSRFTOKEN=before['csrf_token']).status_code, 403)

    def test_logout_invalidates_session(self):
        self.assertEqual(self.post('mini_logout', {}).status_code, 200)
        self.assertEqual(self.client.get(reverse('mini_visits')).status_code, 401)

    def test_catalogue_exposes_patient_projection_only(self):
        data = self.client.get(reverse('mini_catalogue')).json()['data']
        self.assertEqual(data['services'][0]['id'], self.service.pk)
        self.assertEqual(set(data['services'][0]['dentists'][0]), {'id', 'name'})
        self.assertNotIn('home_address', str(data))
        self.assertNotIn('acquisition_cost', str(data))

    def test_candidates_use_shared_resource_calendar(self):
        params = {'clinic': self.a.pk, 'service': self.service.pk, 'day': self.t.date().isoformat()}
        response = self.client.get(reverse('mini_candidates'), params)
        self.assertEqual(response.status_code, 200, response.content)
        available = response.json()['data']
        self.assertEqual(available['status'], 'AVAILABLE')
        self.assertTrue(available['rows'])
        self.assertEqual({r['dentist_id'] for r in available['rows']}, {self.d1.pk, self.d2.pk})
        web = WorkspaceClient()
        web.force_login(self.user)
        grouped = web.get(reverse('portal_slots'), dict(params, by='doctor'))
        self.assertEqual(grouped.context['availability_status'], 'AVAILABLE')
        self.assertContains(grouped, '本次查询最早可约')
        self.assertEqual([r['start'].isoformat() for r in grouped.context['rows']], [r['start'] for r in available['rows']])
        empty_day = (self.t.date() + timedelta(days=1)).isoformat()
        self.assertContains(web.get(reverse('portal_slots'), dict(params, day=empty_day)), '暂无已发布出诊')
        empty = self.client.get(reverse('mini_candidates'), dict(params, day=empty_day)).json()['data']
        self.assertEqual(empty['status'], 'NO_SCHEDULE')
        future = self.client.get(reverse('mini_candidates'), {'clinic': self.a.pk, 'service': self.service.pk}).json()['data']
        self.assertEqual(future['status'], 'AVAILABLE')
        for chair in self.chairs: self.maintain(chair)
        blocked = self.client.get(reverse('mini_candidates'), params).json()['data']
        self.assertEqual((blocked['status'], blocked['rows']), ('NO_COMBINATION', []))
        self.assertContains(web.get(reverse('portal_slots'), params), '这次查询暂无合适时段')

    def test_slot_mode_and_confirmation_keep_filters_without_holding_a_slot(self):
        from urllib.parse import parse_qs, urlparse

        web = WorkspaceClient()
        web.force_login(self.user)
        params = {'clinic': str(self.a.pk), 'service': str(self.service.pk), 'dentist': str(self.d1.pk),
                  'day': self.t.date().isoformat(), 'by': 'doctor'}
        lookup = web.get(reverse('portal_slots'), params)
        self.assertEqual(lookup.context['mode'], 'doctor')
        self.assertEqual(parse_qs(urlparse(lookup.context['doctor_url']).query), {k: [v] for k, v in params.items()})
        option = lookup.context['rows'][0]
        preview = web.get(reverse('portal_confirm'), dict(params, slot=option['slot'].pk, start=option['start_iso']))
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(parse_qs(urlparse(preview.context['slots_url']).query), {k: [v] for k, v in params.items()})
        upcoming = web.get(lookup.context['future_url'])
        self.assertIsNone(upcoming.context['form'].cleaned_data['day'])
        self.assertFalse(Visit.objects.exists())
        self.assertFalse(ResourceClaim.objects.exists())

    def test_preview_never_creates_business_records(self):
        before = (Visit.objects.count(), AuditEvent.objects.count(), ResourceClaim.objects.count())
        self.preview()
        self.assertEqual(before, (Visit.objects.count(), AuditEvent.objects.count(), ResourceClaim.objects.count()))

    def test_booking_confirmation_replay_one_effect(self):
        token = self.preview()
        ids = [self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on')).json()['data']['id'] for _ in range(2)]
        self.assertEqual(ids[0], ids[1]); self.assertEqual(Visit.objects.count(), 1)
        self.assertEqual(BookingReceipt.objects.count(), 1)
        self.assertEqual(ResourceClaim.objects.filter(active=True).count(), 1)
        self.assertFalse(Invoice.objects.exists()); self.assertFalse(CashEntry.objects.exists())

    def test_explicit_confirmation_required(self):
        self.assertEqual(self.post('mini_book_confirm', {'proposal_token': self.preview()}).status_code, 409)
        self.assertFalse(Visit.objects.exists())

    def test_patient_id_injection_ignored(self):
        response = self.post('mini_book_confirm', dict(proposal_token=self.preview(), confirmed='on', patient_id=self.p2.pk, clinic=self.b.pk))
        visit = Visit.objects.get(pk=response.json()['data']['id'])
        self.assertEqual((visit.patient_id, visit.clinic_id), (self.p1.pk, self.a.pk))

    def test_foreign_preview_not_accepted(self):
        c, session = self.login(self.other)
        self.assertEqual(self.post('mini_book_confirm', dict(proposal_token=self.preview(), confirmed='on'), client=c, session=session).status_code, 409)
        self.assertFalse(Visit.objects.exists())

    def test_wrong_clinic_service_rejected(self):
        response = self.client.get(reverse('mini_candidates'), dict(clinic=self.b.pk, service=self.service.pk, day=self.t.date().isoformat()))
        self.assertEqual(response.status_code, 409)

    def test_access_revocation_between_preview_and_confirm(self):
        token = self.preview(); PatientAccess.objects.filter(pk=self.access.pk).update(is_active=False)
        response = self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on'))
        self.assertEqual(response.status_code, 409); self.assertFalse(Visit.objects.exists())

    def test_disabled_account_rejected(self):
        token = self.preview(); UserAccount.objects.filter(pk=self.user.pk).update(is_active=False)
        self.assertEqual(self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on')).status_code, 401)

    def test_password_change_invalidates_old_session(self):
        self.user.set_password('Changed-course-password'); self.user.save(update_fields=['password'])
        self.assertEqual(self.client.get(reverse('mini_visits')).status_code, 401)

    def test_old_preview_rejected_after_new_login(self):
        token = self.preview(); c, session = self.login(self.user)
        self.assertEqual(self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on'), client=c, session=session).status_code, 409)

    def test_private_detail_and_history_chain(self):
        visit = self.book(); c, _ = self.login(self.other)
        foreign = c.get(reverse('mini_visit', kwargs={'pk': visit.pk}))
        absent = c.get(reverse('mini_visit', kwargs={'pk': 99999999}))
        self.assertEqual(foreign.status_code, 404); self.assertEqual(foreign.json()['message'], absent.json()['message'])
        self.assertEqual(c.get(reverse('mini_visits')).json()['data']['rows'], [])

    def test_cancel_preview_confirm_and_original_reason(self):
        visit = self.book()
        p = self.post('mini_cancel_preview', dict(expected_version=0, reason='患者行程变化'), pk=visit.pk).json()['data']
        visit.refresh_from_db(); self.assertEqual(visit.status, 'SCHEDULED')
        response = self.post('mini_cancel_confirm', dict(proposal_token=p['proposal_token'], confirmed='on'), pk=visit.pk)
        self.assertEqual(response.status_code, 200, response.content)
        visit.refresh_from_db(); self.assertEqual((visit.status, visit.cancellation_party, visit.cancellation_reason), ('CANCELLED', 'PATIENT', '患者行程变化'))
        self.assertFalse(ResourceClaim.objects.filter(active=True).exists())
        self.assertEqual(self.post('mini_cancel_confirm', dict(proposal_token=p['proposal_token'], confirmed='on'), pk=visit.pk).status_code, 409)
        self.assertEqual(AuditEvent.objects.filter(event_type='PORTAL_CANCELLED').count(), 1)

    def test_reschedule_retains_chain_and_replays(self):
        visit = self.book()
        data = dict(action='preview', expected_version=0, slot_id=self.slot2.pk, start=(self.t+timedelta(hours=1)).isoformat(), reason='希望较晚到诊')
        response = self.post('mini_reschedule_preview', data, pk=visit.pk)
        self.assertEqual(response.status_code, 200, response.content)
        token = response.json()['data']['proposal_token']
        responses = [self.post('mini_reschedule_confirm', dict(proposal_token=token, confirmed='on'), pk=visit.pk).json()['data'] for _ in range(2)]
        self.assertEqual(responses[0]['visit']['id'], responses[1]['visit']['id']); self.assertTrue(responses[1]['replayed'])
        visit.refresh_from_db(); self.assertEqual(visit.status, 'RESCHEDULED')
        detail = self.client.get(reverse('mini_visit', kwargs={'pk': visit.pk})).json()['data']
        self.assertEqual(detail['successor'], responses[0]['visit']['id'])
        self.assertFalse(Invoice.objects.exists()); self.assertFalse(CashEntry.objects.exists())

    def test_reschedule_candidates_and_foreign_source(self):
        visit = self.book()
        response = self.client.get(reverse('mini_reschedule_candidates', kwargs={'pk':visit.pk}), {'day': self.t.date().isoformat()})
        self.assertEqual(response.status_code, 200, response.content); self.assertTrue(response.json()['data']['rows'])
        c, _ = self.login(self.other)
        self.assertEqual(c.get(reverse('mini_reschedule_candidates', kwargs={'pk':visit.pk}), {'day': self.t.date().isoformat()}).status_code, 404)

    def test_resource_changes_after_preview_preserve_other_business(self):
        token = self.preview()
        for chair in self.chairs: self.maintain(chair)
        self.assertEqual(self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on')).status_code, 409)
        self.assertFalse(Visit.objects.exists()); self.assertFalse(BookingReceipt.objects.exists())

    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_keeps_login_and_reads_but_rejects_business(self):
        c, session = self.login(self.user)
        self.assertTrue(session['read_only'])
        self.assertEqual(c.get(reverse('mini_catalogue')).status_code, 200)
        self.assertEqual(self.post('mini_book_preview', {}, client=c, session=session).status_code, 403)
        self.assertEqual(self.post('mini_logout', {}, client=c, session=session).status_code, 200)

    def test_http_resource_race_between_two_patients(self):
        ResourceBinding.objects.filter(asset=self.chairs[1]).update(is_active=False)
        other_client, other_session = self.login(self.other)
        first = self.preview(); second = self.preview(client=other_client, session=other_session, slot=self.slot2)
        barrier = Barrier(2)
        def run(client, session, token):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on'), client=client, session=session).status_code
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, c, ss, token) for c, ss, token in [(self.client,self.session,first),(other_client,other_session,second)]]
            codes = [f.result(timeout=30) for f in futures]
        self.assertEqual(sorted(codes), [200,409]); self.assertEqual(Visit.objects.count(), 1)
        self.assertEqual(ResourceClaim.objects.filter(active=True).count(), 1)

    def test_native_and_website_compete_for_same_chair(self):
        ResourceBinding.objects.filter(asset=self.chairs[1]).update(is_active=False)
        web, session = self.login(self.other)
        native_token = self.preview()
        page = web.get(reverse('portal_confirm'), dict(slot=self.slot2.pk, start=self.t.isoformat(), service=self.service.pk))
        web_token = page.context['form'].initial['token']
        barrier = Barrier(2)
        def run(native):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                if native:
                    return self.post('mini_book_confirm', dict(proposal_token=native_token, confirmed='on')).status_code == 200
                return web.post(reverse('portal_confirm'), dict(token=web_token, confirmed='on', workspace_token=session['workspace_token']),
                    HTTP_X_CSRFTOKEN=session['csrf_token']).status_code == 302
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run, native) for native in (True,False)]
            self.assertEqual(sorted(f.result(timeout=30) for f in futures), [False,True])
        self.assertEqual(Visit.objects.count(), 1)
        self.assertEqual(BookingReceipt.objects.count(), 1)
        self.assertEqual(ResourceClaim.objects.filter(active=True).count(), 1)
