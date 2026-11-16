"""PostgreSQL and HTTP regression for the report to follow-up workflow."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from adc_core.rules import RuleError
from care.services import complete_visit
from clinical import examination_followup as followups, examinations, executions, next_visits, preflight, recall
from clinical.examination_models import ExaminationFollowup, ExaminationNotice
from clinical.plan_models import NextVisitInstruction, PlanAppointment, PerformedProcedure
from portal import medical_proxies, relationships, report_notices, rescheduling, services
from portal.models import BookingReceipt
from registry.models import TreatmentType
from scheduling.models import Visit
from tests.test_examination_reports import BODY1, BODY2, ExaminationFixture


class ReportFollowupFixture(ExaminationFixture):
    def release(self, order, *, kind='BOOK', body=BODY1, reason='', **fields):
        if not order.performed_at:
            order = self.execute(order)
        self.step(order, 'SUBMIT', body=body, reason=reason)
        self.step(order, 'APPROVE', self.reviewer)
        if kind == 'BOOK' and 'instruction' not in fields:
            fields = dict(service=self.service.pk, step_version=None, earliest_on=timezone.localdate().isoformat(),
                latest_on=(timezone.localdate()+timedelta(days=5)).isoformat(), clinical_purpose='课程合成复诊目标',
                completion_rule='EXAM_CONFIRMED', booking_note='按建议窗口安排') | fields
        return self.step(order, 'PUBLISH', followup_kind=kind, **fields)

    def bound_fields(self, order):
        order.refresh_from_db()
        return dict(followup_visit=self.v.pk, followup_examination=order.pk,
            followup_revision=order.active_release.report.number)

    def scoped_preview(self, order, *, hours=2, slot=None):
        _, _, token = services.preview_booking(user=self.patient_user, slot_id=(slot or self.slot1).pk,
            start=self.t+timedelta(hours=hours), service_id=self.service.pk, followup=self.bound_fields(order))
        return token

    def report(self, order, *, client=None):
        response = (client or self.mini).get(reverse('mini_examination', args=[self.v.pk, order.pk]))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['data']


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ExaminationFollowupTests(ReportFollowupFixture, TransactionTestCase):
    def setUp(self):
        self.setup_examinations()

    def mini_post(self, route, payload, args=(), *, client=None):
        client = client or self.mini
        session = client.get(reverse('mini_session')).json()['data']
        return client.post(reverse(route, args=args), payload, HTTP_X_CSRFTOKEN=session['csrf_token'],
            HTTP_X_ADC_WORKSPACE=session['workspace_token'])

    def test_report_uses_published_service_title_and_keeps_appointment_after_unpublishing(self):
        order = self.release(self.open_order())
        profile = self.service.patient_presentation
        self.assertNotEqual(self.service.name, profile.title)
        args = [self.v.pk, order.pk]
        source = self.report(order)['followup']
        self.assertEqual((source['action'], source['service_id'], source['service']),
            ('BOOK', self.service.pk, profile.title))
        self.assertContains(self.web.get(reverse('portal_examination', args=args)), profile.title)

        fields = self.bound_fields(order) | dict(service=self.service.pk, slot=self.slot1.pk,
            start=(self.t + timedelta(hours=2)).isoformat())
        mini = self.mini_post('mini_book_preview', fields)
        self.assertEqual(mini.status_code, 200, mini.content)
        self.assertEqual(mini.json()['data']['service'], profile.title)
        self.assertContains(self.web.get(reverse('portal_confirm'), fields), profile.title)
        self.assertEqual(Visit.objects.count(), 1)

        payload = dict(proposal_token=mini.json()['data']['proposal_token'], confirmed=True)
        appointment = self.mini_post('mini_book_confirm', payload).json()['data']['id']
        profile.is_published = False
        profile.save(update_fields=['is_published'])
        retained = self.report(order)['followup']
        self.assertEqual((retained['action'], retained['service_id'], retained['service'],
            retained['appointment']['id']), ('VIEW_APPOINTMENT', self.service.pk, self.service.name, appointment))
        self.assertEqual(Visit.objects.get(pk=appointment).status, 'SCHEDULED')

    def test_reports_require_self_for_valid_proxies_but_leave_other_scopes_active(self):
        order = self.release(self.open_order(), kind='NONE')
        notice = ExaminationNotice.objects.get(event__order=order)
        delegate, relationship, grant = self.create_delegate()
        step = self.publish_plan(self.new_plan()).steps.get()
        medical = UserAccount.objects.create_user(username='report_medical_proxy', password=self.password)
        RoleAssignment.objects.filter(user=self.front, clinic=self.a, role='FRONT_DESK').update(
            can_verify_medical_proxy_identity=True)
        prepared = medical_proxies.prepare_submit(actor=self.front, fields=dict(
            patient_no=self.p1.patient_no, username=medical.username, delegate_name='课程合成代理人',
            kind='WRITTEN', plan=step.version.plan_id, steps=[step.step_id],
            identity_reference='SYNTHETIC-REPORT-ID', authority_reference='SYNTHETIC-REPORT-AUTHORITY',
            applicability='课程合成：已核对本人书面委托及方案步骤。',
            valid_from=(timezone.now() - timedelta(minutes=2)).isoformat(),
            valid_until=(timezone.now() + timedelta(days=3)).isoformat()))
        proxy, _ = medical_proxies.confirm(actor=self.front, **prepared, confirmed=True)
        for action, actor in [('MATERIALS_OK', self.front), ('APPROVE', self.doc)]:
            prepared = medical_proxies.prepare_action(actor=actor, case_id=proxy.pk, action=action,
                note='课程合成：核对本次原件及授权范围。', applicable=True)
            proxy, _ = medical_proxies.confirm(actor=actor, **prepared, confirmed=True)

        report_args = [self.v.pk, order.pk]
        for actor, subject, allowed_route, allowed_args in [
            (delegate, f'grant:{grant.pk}', 'mini_visit', [self.v.pk]),
            (medical, f'medical:{proxy.pk}', 'mini_medical_authorization', [proxy.pk]),
        ]:
            with self.subTest(subject=subject):
                mini = self.mini_client(actor)
                web = self.web_client(actor)
                selected = self.mini_post('mini_subject_select', {'subject': subject}, client=mini)
                self.assertEqual(selected.status_code, 200, selected.content)
                self.assertEqual(web.post(reverse('portal_subjects'), {'subject': subject}).status_code, 302)
                responses = [
                    mini.get(reverse('mini_report_notices')),
                    mini.get(reverse('mini_examination', args=report_args)),
                    self.mini_post('mini_report_notice_read', {}, [notice.pk], client=mini),
                ]
                for response in responses:
                    self.assertEqual(response.status_code, 403, response.content)
                    detail = response.json()
                    self.assertEqual(detail['code'], 'REPORT_SELF_REQUIRED')
                    self.assertEqual(set(detail), {'ok', 'request_id', 'code', 'message'})
                    self.assertTrue(detail['request_id'])
                    self.assertIn('仅限患者本人查看', detail['message'])
                for response in [
                    web.get(reverse('portal_report_notices')),
                    web.get(reverse('portal_examination', args=report_args)),
                    web.post(reverse('portal_report_notice_read', args=[notice.pk]), {}),
                ]:
                    self.assertContains(response, '仅限患者本人查看', status_code=403)
                    self.assertContains(response, '返回患者工作台', status_code=403)
                    self.assertNotContains(response, BODY1, status_code=403)
                self.assertEqual(mini.get(reverse(allowed_route, args=allowed_args)).status_code, 200)
                if actor == delegate:
                    revoked_client = mini

        notice.refresh_from_db()
        self.assertIsNone(notice.read_at)
        token = relationships.prepare_action(actor=self.front, case_id=relationship.pk,
            action='REVOKE', note='课程合成：结束试验代约授权。')
        relationships.confirm(actor=self.front, token=token, confirmed=True)
        stale = revoked_client.get(reverse('mini_report_notices'))
        self.assertEqual(stale.status_code, 409)
        self.assertIn(stale.json()['code'], ('SUBJECT_REQUIRED', 'WORKSPACE_CHANGED'))
        self.assertEqual(self.mini.get(reverse('mini_report_notices')).status_code, 200)

    def test_notice_only_after_release_and_read_state_shared_with_web(self):
        order = self.execute(self.open_order())
        self.step(order, 'SUBMIT', body=BODY1)
        self.step(order, 'APPROVE', self.reviewer)
        listing = reverse('mini_report_notices')
        self.assertEqual(self.mini.get(listing).json()['data']['unread_count'], 0)
        token = self.prepare_step(order, 'PUBLISH', followup_kind='NONE')
        for replay in (False, True):
            self.assertEqual(examinations.confirm(actor=self.doc, proposal_token=token, confirmed=True)[1], replay)
        first = self.mini.get(listing).json()['data']
        row, = first['rows']
        self.assertEqual((row['kind'], row['revision'], first['unread_count']), ('RELEASED', 1, 1))
        self.assertEqual(set(row), {'id', 'kind', 'title', 'clinic', 'occurred_at', 'read_at', 'visit_id',
            'examination_id', 'revision'})
        self.assertContains(self.web.get(reverse('portal_report_notices')), '1 条未读')
        response = self.mini_post('mini_report_notice_read', {}, [row['id']])
        self.assertEqual(response.status_code, 200, response.content)
        read = response.json()['data']
        self.assertEqual(read['unread_count'], 0)
        self.assertEqual(report_notices.mark_read(self.patient_user, row['id'])['read_at'].isoformat()[:19],
            read['read_at'][:19])
        self.assertContains(self.web.get(reverse('portal_report_notices')), '0 条未读')
        self.assertEqual(self.mini.get(reverse('mini_overview')).json()['data']['report_unread_count'], 0)
        order = self.release(order, kind='NONE', body=BODY2, reason='课程合成更正')
        corrected, = self.mini.get(listing).json()['data']['rows']
        self.assertEqual((corrected['kind'], corrected['revision'], corrected['read_at']), ('CORRECTED', 2, None))
        self.assertEqual(self.mini_post('mini_report_notice_read', {}, [row['id']]).status_code, 404)
        self.step(order, 'WITHDRAW', reason='课程合成撤回')
        withdrawn, = self.mini.get(listing).json()['data']['rows']
        self.assertEqual((withdrawn['kind'], withdrawn['revision']), ('WITHDRAWN', None))
        self.assertEqual(ExaminationNotice.objects.count(), 3)

    def test_next_action_follows_report_read_booking_cancellation_and_current_revision(self):
        order = self.release(self.open_order())
        self.v.refresh_from_db()
        complete_visit(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version,
            outcome='NO_TREATMENT', reason='课程合成：单独核对报告复诊待办。')
        notice = ExaminationNotice.objects.get(event__order=order)
        report_link = reverse('portal_examination', args=[self.v.pk, order.pk])

        def overview(client=self.mini):
            response = client.get(reverse('mini_overview'))
            self.assertEqual(response.status_code, 200, response.content)
            return response.json()['data']

        pending = overview()['primary_action']
        self.assertEqual(pending['kind'], 'REPORT_FOLLOWUP')
        self.assertEqual(pending['report'], {'visit_id': self.v.pk, 'id': order.pk, 'revision': 1})
        self.assertContains(self.web.get(reverse('portal_home')), report_link + '?revision=1')
        self.assertEqual(self.mini_post('mini_report_notice_read', {}, [notice.pk]).status_code, 200)
        self.assertEqual(overview()['report_unread_count'], 0)
        self.assertEqual(overview()['primary_action'], pending)
        other = self.mini_client(self.create_other())
        self.assertNotIn('report', overview(other)['primary_action'])
        delegate, _, grant = self.create_delegate()
        proxy = self.mini_client(delegate)
        self.assertEqual(self.mini_post('mini_subject_select', {'subject': f'grant:{grant.pk}'}, client=proxy).status_code, 200)
        self.assertNotIn('report', overview(proxy)['primary_action'])

        visit = services.confirm_booking(actor=self.patient_user, token=self.scoped_preview(order), require_published_service=True)
        self.assertEqual(overview()['primary_action']['visit']['id'], visit.pk)
        self.assertNotContains(self.web.get(reverse('portal_home')), '查看报告与复诊')
        services.cancel_booking(actor=self.patient_user, visit_id=visit.pk, expected_version=visit.lock_version,
            reason='课程合成：取消复诊，保留原报告。')
        self.assertEqual(overview()['primary_action'], pending)
        self.assertEqual(self.report(order)['followup']['action'], 'BOOK')
        with patch.object(timezone, 'now', return_value=timezone.now() + timedelta(days=6)):
            client = self.mini_client(self.patient_user)
            late = overview(client)['primary_action']
            self.assertEqual(late['report'], pending['report'])
            self.assertEqual(late['label'], '复诊待门店协助')
            self.assertEqual(late['hint'], self.report(order, client=client)['followup']['message'])
            self.assertContains(self.web_client(self.patient_user).get(reverse('portal_home')), late['hint'])

        order = self.release(order, body=BODY2, reason='课程合成：更新报告和复诊建议。')
        self.assertEqual(overview()['primary_action']['report']['revision'], 2)
        self.assertContains(self.web.get(reverse('portal_home')), report_link + '?revision=2')
        self.assertEqual(self.web.get(report_link + '?revision=1').status_code, 404)
        self.step(order, 'WITHDRAW', reason='课程合成：撤回患者报告。')
        self.assertEqual(overview()['primary_action']['kind'], 'BOOK')
        self.assertEqual(Visit.objects.filter(patient=self.p1).count(), 2)
        self.assertEqual(PlanAppointment.objects.filter(visit=visit).count(), 1)

    def test_report_linked_booking_web_and_mini_replay_and_successor(self):
        order = self.release(self.open_order())
        source = self.report(order)['followup']
        self.assertEqual(source['action'], 'BOOK')
        fields = dict(self.bound_fields(order), clinic=self.a.pk, service=self.service.pk,
            day=timezone.localdate(self.t).isoformat())
        page = self.web.get(reverse('portal_slots'), fields)
        self.assertContains(page, '预约复诊')
        self.assertContains(page, 'followup_revision=1')
        params = dict(fields, slot=self.slot1.pk, start=(self.t+timedelta(hours=2)).isoformat())
        preview = self.web.get(reverse('portal_confirm'), params)
        self.assertEqual(preview.status_code, 200, preview.content)
        payload = {'token': preview.context['form'].initial['token'], 'confirmed': 'on'}
        web_path = reverse('portal_confirm')
        result = self.web.post(web_path, payload)
        self.assertEqual(result.status_code, 302, result.content)
        link = PlanAppointment.objects.get(report_followup__release__order=order)
        self.assertRedirects(result, reverse('portal_visit', args=[link.visit_id]), fetch_redirect_response=False)
        self.assertEqual(self.web.post(web_path, payload).url, result.url)
        self.assertEqual(self.report(order)['followup']['appointment']['visit_no'], link.visit.visit_no)
        prepare = rescheduling.prepare(actor=self.patient_user, visit_id=link.visit_id,
            expected_version=link.visit.lock_version, slot_id=self.slot1.pk, start=self.t+timedelta(hours=3),
            reason='合成复诊改期')
        replacement, _ = rescheduling.confirm(actor=self.patient_user, visit_id=link.visit_id,
            proposal_token=prepare['proposal_token'], confirmed=True)
        self.assertEqual(self.report(order)['followup']['appointment']['id'], replacement.pk)
        with self.assertRaises(RuleError):
            rescheduling.options(actor=self.patient_user, visit_id=replacement.pk,
                day=timezone.localdate()+timedelta(days=9))
        self.step(order, 'WITHDRAW', reason='课程合成撤回')
        with self.assertRaises(RuleError):
            rescheduling.options(actor=self.patient_user, visit_id=replacement.pk, day=timezone.localdate())
        replacement.refresh_from_db()
        self.assertEqual(replacement.status, 'SCHEDULED')
        services.cancel_booking(actor=self.patient_user, visit_id=replacement.pk,
            expected_version=replacement.lock_version, reason='本人取消课程合成安排')
        self.assertEqual(Visit.objects.get(pk=replacement.pk).status, 'CANCELLED')
        self.assertEqual(PlanAppointment.objects.filter(report_followup__release__order=order).count(), 1)

    def test_booking_conflicts_are_atomic_and_one_result_for_two_tokens(self):
        order = self.release(self.open_order())
        first, second = (self.scoped_preview(order, hours=hours) for hours in (2, 3))
        money = self.money()
        gate = Barrier(2)

        def confirm(token):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                try:
                    return services.confirm_booking(actor=self.patient_user, token=token, require_published_service=True).pk
                except RuleError:
                    return None
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(confirm, (first, second)))
        self.assertEqual(responses.count(None), 1)
        link = PlanAppointment.objects.get(report_followup__release__order=order)
        self.assertIn(link.visit_id, responses)
        self.assertEqual(BookingReceipt.objects.filter(visit=link.visit).count(), 1)
        self.assertEqual(Visit.objects.count(), 2)
        self.assertEqual(self.money(), money)

    def test_mini_booking_matches_web_receipt_and_replay(self):
        order = self.release(self.open_order())
        parameters = self.bound_fields(order) | dict(slot=self.slot1.pk,
            start=(self.t + timedelta(hours=2)).isoformat(), service=self.service.pk)
        preview = self.mini_post('mini_book_preview', parameters)
        self.assertEqual(preview.status_code, 200, preview.content)
        payload = dict(proposal_token=preview.json()['data']['proposal_token'], confirmed=True)
        first = self.mini_post('mini_book_confirm', payload)
        self.assertEqual(first.status_code, 200, first.content)
        again = self.mini_post('mini_book_confirm', payload)
        self.assertEqual(again.status_code, 200, again.content)
        visit = first.json()['data']
        self.assertEqual(again.json()['data']['id'], visit['id'])
        self.assertEqual(self.report(order)['followup']['appointment']['id'], visit['id'])
        web = self.web.get(reverse('portal_examination', args=[self.v.pk, order.pk]))
        self.assertContains(web, visit['visit_no'])
        self.assertEqual(PlanAppointment.objects.filter(report_followup__release__order=order).count(), 1)

    def test_frontdesk_link_and_self_service_confirm_share_the_same_instruction(self):
        order = self.release(self.open_order())
        decision = followups.current_decision(order)
        available = self.scoped_preview(order, hours=2)
        existing = self.booking(start=self.t + timedelta(hours=3))
        prepared = next_visits.prepare_link(actor=self.front, instruction_id=decision.instruction_id, visit_id=existing.pk)
        gate = Barrier(2)

        def run(action):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                return action()
            except RuleError:
                return None
            finally:
                close_old_connections()

        def link():
            row, _ = next_visits.confirm_link(actor=self.front,
                proposal_token=prepared['proposal_token'], confirmed=True)
            return row.visit_id

        def book():
            return services.confirm_booking(actor=self.patient_user, token=available, require_published_service=True).pk

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(run, (link, book)))
        self.assertEqual(outcomes.count(None), 1)
        row = PlanAppointment.objects.get(instruction=decision.instruction)
        self.assertEqual(row.report_followup_id, decision.pk)
        self.assertIn(row.visit_id, outcomes)
        self.assertEqual(self.report(order)['followup']['appointment']['id'], row.visit_id)
        self.assertTrue(Visit.objects.filter(pk=existing.pk, status='SCHEDULED').exists())
        self.assertEqual(Visit.objects.count(), 2 + int(row.visit_id != existing.pk))

    def test_stale_report_and_cross_patient_cannot_confirm_or_read(self):
        order = self.release(self.open_order())
        old_token = self.scoped_preview(order)
        original = followups.current_decision(order)
        order = self.release(order, body=BODY2, reason='课程合成换版', instruction=original.instruction_id)
        with self.assertRaises(RuleError):
            services.confirm_booking(actor=self.patient_user, token=old_token, require_published_service=True)
        other = self.create_other()
        mini = self.mini_client(other)
        self.assertEqual(mini.get(reverse('mini_report_notices')).json()['data']['rows'], [])
        self.assertEqual(mini.get(reverse('mini_examination', args=[self.v.pk, order.pk])).status_code, 404)
        with self.assertRaises(RuleError):
            services.confirm_booking(actor=other, token=self.scoped_preview(order), require_published_service=True)
        self.assertEqual(Visit.objects.count(), 1)
        self.assertFalse(PlanAppointment.objects.exists())

    def test_frontdesk_can_adopt_existing_appointment_after_instruction_changes(self):
        order = self.release(self.open_order())
        visit = services.confirm_booking(actor=self.patient_user, token=self.scoped_preview(order),
            require_published_service=True)
        old = PlanAppointment.objects.get(visit=visit)
        order = self.release(order, body=BODY2, reason='课程合成：更正报告并追加复诊目标')
        updated = followups.current_decision(order)
        self.assertNotEqual(old.instruction_id, updated.instruction_id)
        blocked = self.report(order)['followup']
        self.assertEqual((blocked['action'], blocked['appointment']['id']), ('CONTACT', visit.pk))
        prepared = next_visits.prepare_link(actor=self.front, instruction_id=updated.instruction_id, visit_id=visit.pk)
        row, replay = next_visits.confirm_link(actor=self.front, proposal_token=prepared['proposal_token'], confirmed=True)
        self.assertFalse(replay)
        self.assertEqual(row.report_followup_id, updated.pk)
        self.assertEqual(PlanAppointment.objects.filter(visit=visit).count(), 2)
        self.assertEqual(Visit.objects.count(), 2)
        self.assertEqual(BookingReceipt.objects.filter(visit=visit).count(), 1)
        self.assertEqual(self.report(order)['followup']['action'], 'VIEW_APPOINTMENT')

    def test_contact_attempts_and_append_decision_preserve_report(self):
        due = (timezone.now()+timedelta(hours=2)).isoformat()
        order = self.release(self.open_order(), kind='CONTACT', contact_due_at=due)
        original = followups.current_decision(order)
        self.v.refresh_from_db()
        complete_visit(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version,
            outcome='NO_TREATMENT', reason='课程合成：核对门店联系待办。')
        def primary():
            return self.mini.get(reverse('mini_overview')).json()['data']['primary_action']
        self.assertEqual(primary()['label'], '复诊待门店协助')
        self.assertEqual(self.report(order)['followup']['action'], 'CONTACT')
        self.assertContains(self.web_client(self.doc).get(reverse('clinical_examinations')+'?queue=contact'), '待联系')
        self.assertNotContains(self.front_web.get(reverse('clinical_examination_progress')), BODY1)
        self.step(order, 'CONTACT_RESULT', contact_outcome='NO_ANSWER',
            contact_due_at=(timezone.now()+timedelta(hours=3)).isoformat(), contact_note='课程合成联系未果')
        self.assertEqual(followups.contact_progress(original)['state'], '联系未果')
        self.assertEqual(primary()['report']['id'], order.pk)
        token = self.prepare_step(order, 'CONTACT_RESULT', contact_outcome='REACHED', contact_note='已与本人核对课程安排')
        for replay in (False, True):
            self.assertEqual(examinations.confirm(actor=self.doc, proposal_token=token, confirmed=True)[1], replay)
        self.assertEqual(followups.contact_progress(original)['state'], '已联系')
        self.assertEqual(primary()['kind'], 'BOOK')
        self.assertEqual(followups.contact_events(original).count(), 2)
        instruction = self.instruction()
        self.step(order, 'FOLLOWUP', followup_kind='BOOK', instruction=instruction.pk)
        self.assertEqual(self.report(order)['followup']['action'], 'BOOK')
        self.assertEqual(primary()['label'], '复诊待安排')
        self.assertEqual(ExaminationFollowup.objects.filter(release=original.release).count(), 2)
        self.assertEqual(ExaminationNotice.objects.count(), 1)

    def test_latest_report_basis_is_rechecked_before_actual_treatment(self):
        order = self.open_order()
        unrelated = self.open_order()
        _, package = self.close_and_archive()
        snapshot = (package.pdf_sha256, package.manifest)
        order = self.release(order)
        self.release(unrelated, kind='NONE', body='课程合成：同一次原就诊的另一个独立报告。')
        instruction = followups.current_decision(order).instruction
        followup = services.confirm_booking(actor=self.patient_user, token=self.scoped_preview(order),
            require_published_service=True)
        self.arrive(followup)
        workspace = self.web_client(self.doc).get(reverse('clinical_examination_visit', args=[followup.pk]))
        self.assertContains(workspace, order.number)
        self.assertNotContains(workspace, unrelated.number)
        self.clinical(followup)
        self.review(followup)
        fields = self.actual_fields()

        def check():
            ready = preflight.prepare(actor=self.doc, visit_id=followup.pk, fields=fields,
                communication='课程合成：核对复诊依据及拟实施范围。')
            return preflight.confirm(actor=self.doc, proposal_token=ready['proposal_token'], confirmed=True)[0]

        old = check()
        self.assertEqual(old.snapshot['examination_basis'][0]['revision'], 1)
        order = self.release(order, body=BODY2, reason='课程合成更新', instruction=instruction.pk)
        with self.assertRaises(RuleError):
            self.actual(visit=followup, preflight=old.pk)
        new = check()
        self.assertEqual(new.snapshot['examination_basis'][0]['revision'], 2)
        execution = self.actual(visit=followup, preflight=new.pk)
        followup.refresh_from_db()
        complete_visit(actor=self.doc, visit_id=followup.pk, expected_version=followup.lock_version, outcome='TREATED')
        self.assertEqual(PerformedProcedure.objects.filter(encounter__visit=followup).count(), 1)
        self.assertEqual(execution.preflight_id, new.pk)
        evidence, = recall.completion_candidates(instruction)
        self.assertEqual(evidence['visit'], followup.pk)
        package.refresh_from_db()
        self.assertEqual((package.pdf_sha256, package.manifest), snapshot)
