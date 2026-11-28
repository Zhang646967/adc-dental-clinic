"""Isolated PostgreSQL coverage of the patient channel with site rules enabled."""
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.http import Http404
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from adc_core.rules import RuleError
from care.services import complete_visit
from clinical.authority_services import confirm_authority, prepare_authority
from clinical.examination_models import ExaminationNotice, ExaminationProject
from clinical.plan_models import PlanAppointment
from portal import report_followup, report_notices, rescheduling, services
from portal.models import BookingReceipt
from portal.policies import patient_access
from scheduling.models import Visit
from tests.test_examination_followup import ReportFollowupFixture


@override_settings(ADC_CLINICAL_SYNTHETIC=False)
class SiteReportPatientTests(ReportFollowupFixture, TransactionTestCase):
    def fields(self, *args, **kwargs):
        # Fictional documentary evidence belongs only to this transient test database.
        return super().fields(*args, **kwargs, source_kind='DOCUMENT',
            source_reference='FIXTURE-ONLY-SITE-REPORT', issuer='隔离测试资料')

    def setUp(self):
        self.setup_visit_review()
        self.appoint(self.doc, self.a)
        self.ctx(self.doc, 'DENTIST')
        proposal = prepare_authority(actor=self.manager, action='PROPOSE', fields=self.fields(self.reviewer))
        scope, _ = confirm_authority(actor=self.manager, proposal_token=proposal['proposal_token'], confirmed=True)
        self.decide(scope, 'APPROVE', actor=self.doc)
        self.ctx(self.reviewer, 'DENTIST')
        self.book_and_arrive()
        self.clinical(self.v)
        self.provision('SITE-FIRST')

    def configure(self, code, action, *options):
        call_command('configure_site_examination', '--operator', self.tech.username, '--service',
            str(self.service.pk), '--code', code, action, *options, stdout=StringIO())

    def provision(self, code):
        self.configure(code, 'provision', '--name', '检查项目 ' + code, '--examiner', self.doc.username,
            '--reviewer', self.reviewer.username)
        self.project = ExaminationProject.objects.get(service=self.service, code=code)

    def test_project_visibility_is_identical_for_web_mobile_counts_and_booking(self):
        suspended = self.release(self.open_order(), body='已暂停项目正文')
        suspended_token = self.scoped_preview(suspended)
        confirm_url = reverse('portal_confirm')
        preview = self.web.get(confirm_url, self.bound_fields(suspended) | dict(service=self.service.pk,
            slot=self.slot1.pk, start=(self.t + timedelta(hours=2)).isoformat()))
        web_token = preview.context['form'].initial['token']
        hidden_notice = ExaminationNotice.objects.get(event__order=suspended)
        self.configure('SITE-FIRST', 'suspend')
        self.provision('SITE-SECOND')
        current = self.release(self.open_order(), body='现行项目正文')

        inbox = self.mini.get(reverse('mini_report_notices')).json()['data']
        self.assertEqual(inbox['unread_count'], 1)
        row, = inbox['rows']
        self.assertEqual((row['examination_id'], row['visit_id'], row['revision']), (current.pk, self.v.pk, 1))
        self.assertIsNone(row['read_at'])
        web = self.web.get(reverse('portal_report_notices'))
        self.assertContains(web, current.project_name)
        self.assertNotContains(web, suspended.project_name)
        summaries = self.mini.get(reverse('mini_visit', args=[self.v.pk])).json()['data']['examinations']
        self.assertEqual([item['id'] for item in summaries], [current.pk])
        access = patient_access(self.patient_user)
        self.assertEqual(report_followup.next_pending(self.patient_user, access)['report']['id'], current.pk)
        self.assertEqual(self.report(current)['followup']['action'], 'BOOK')
        self.assertEqual(self.mini.get(reverse('mini_examination', args=[self.v.pk, suspended.pk])).status_code, 404)
        self.assertEqual(self.web.get(reverse('portal_examination', args=[self.v.pk, suspended.pk])).status_code, 404)
        with self.assertRaisesMessage(RuleError, '本次没有预约'):
            services.confirm_booking(actor=self.patient_user, token=suspended_token, require_published_service=True)
        refused = self.web.post(confirm_url, {'token': web_token, 'confirmed': 'on'}, HTTP_ACCEPT='application/json')
        self.assertEqual((refused.status_code, refused.json()['state']), (409, 'REJECTED'))
        self.assertIn('本次没有预约', refused.json()['message'])
        with self.assertRaises(Http404):
            report_notices.mark_read(self.patient_user, hidden_notice.pk)
        hidden_notice.refresh_from_db()
        self.assertIsNone(hidden_notice.read_at)
        self.assertEqual(Visit.objects.count(), 1)
        self.assertFalse(PlanAppointment.objects.exists())
        self.assertEqual(report_notices.mark_read(self.patient_user, row['id'])['unread_count'], 0)
        self.assertContains(self.web.get(reverse('portal_report_notices')), '0 条未读')
        self.provision('SITE-FIRST')
        with self.assertRaises(RuleError):
            services.confirm_booking(actor=self.patient_user, token=suspended_token, require_published_service=True)
        self.assertEqual(Visit.objects.count(), 1)
        current_token = self.scoped_preview(suspended)
        saved = services.confirm_booking(actor=self.patient_user, token=current_token, require_published_service=True)
        self.assertEqual(self.report(suspended)['followup']['appointment']['id'], saved.pk)

    def test_suspension_preserves_saved_appointment_but_closes_report_entries(self):
        order = self.release(self.open_order())
        token = self.scoped_preview(order)
        saved = services.confirm_booking(actor=self.patient_user, token=token, require_published_service=True)
        self.assertEqual(self.report(order)['followup']['appointment']['visit_no'], saved.visit_no)
        move = rescheduling.prepare(actor=self.patient_user, visit_id=saved.pk, expected_version=saved.lock_version,
            slot_id=self.slot1.pk, start=self.t + timedelta(hours=3), reason='调整到诊时间')
        before = (Visit.objects.count(), BookingReceipt.objects.count(), PlanAppointment.objects.count())
        stranger = self.mini_client(self.create_other())
        self.assertIsNone(stranger.get(reverse('mini_overview')).json()['data']['report_unread_count'])
        self.assertEqual(stranger.get(reverse('mini_examination', args=[self.v.pk, order.pk])).status_code, 404)
        self.configure('SITE-FIRST', 'suspend')
        self.assertIsNone(self.mini.get(reverse('mini_overview')).json()['data']['report_unread_count'])
        self.assertEqual(self.mini.get(reverse('mini_report_notices')).status_code, 404)
        self.assertEqual(self.web.get(reverse('portal_report_notices')).status_code, 404)
        self.assertEqual(self.mini.get(reverse('mini_examination', args=[self.v.pk, order.pk])).status_code, 404)
        self.assertIsNone(report_followup.next_pending(self.patient_user, patient_access(self.patient_user)))
        replay = services.confirm_booking(actor=self.patient_user, token=token, require_published_service=True)
        self.assertEqual(replay.pk, saved.pk)
        self.assertContains(self.web.get(reverse('portal_visit', args=[saved.pk])), saved.visit_no)
        self.provision('SITE-FIRST')
        with self.assertRaises(RuleError):
            rescheduling.confirm(actor=self.patient_user, visit_id=saved.pk,
                proposal_token=move['proposal_token'], confirmed=True)
        saved.refresh_from_db()
        self.assertEqual(saved.status, 'SCHEDULED')
        self.assertEqual(before, (Visit.objects.count(), BookingReceipt.objects.count(), PlanAppointment.objects.count()))

    def test_site_inbox_excludes_rehearsal_history_for_the_same_patient_and_clinic(self):
        site_order = self.release(self.open_order(), kind='NONE')
        ordinary = self.instruction()
        with override_settings(ADC_CLINICAL_SYNTHETIC=True):
            self.project_config('provision', '--name', '历史项目', '--examiner', self.doc.username,
                '--reviewer', self.reviewer.username)
            self.project = ExaminationProject.objects.get(service=self.service, code='COURSE-TEXT')
            rehearsal_order = self.release(self.open_order(), body='历史演练报告')
            hidden = ExaminationNotice.objects.get(event__order=rehearsal_order)
        notices = self.mini.get(reverse('mini_report_notices')).json()['data']
        self.assertEqual(([item['examination_id'] for item in notices['rows']], notices['unread_count']),
            ([site_order.pk], 1))
        self.assertEqual(self.mini.get(reverse('mini_examination', args=[self.v.pk, rehearsal_order.pk])).status_code, 404)
        self.assertIsNone(report_followup.next_pending(self.patient_user, patient_access(self.patient_user)))
        with self.assertRaises(Http404):
            report_notices.mark_read(self.patient_user, hidden.pk)
        self.v.refresh_from_db()
        complete_visit(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version,
            outcome='NO_TREATMENT', reason='本次完成检查评估。')
        visit = self.mini.get(reverse('mini_visit', args=[self.v.pk])).json()['data']
        self.assertEqual([row['id'] for row in visit['review']['followups']], [ordinary.pk])
