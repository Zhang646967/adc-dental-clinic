"""Site-mode staff routes, independent release, and retained follow-up bookings."""
from io import StringIO

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.http import Http404
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from adc_core.rules import RuleError
from clinical import examination_followup, examinations, next_visits, recall, return_visits
from clinical.authority_services import confirm_authority, prepare_authority
from clinical.examination_models import ExaminationDuty, ExaminationNotice, ExaminationProject
from portal.policies import patient_access
from tests.test_chairside_return import ChairsideFixture


class SiteExaminationStaffTests(ChairsideFixture, TransactionTestCase):
    def setUp(self):
        with override_settings(ADC_CLINICAL_SYNTHETIC=True):
            self.setup_examinations()
            self.rehearsal = self.open_order()
        self.production = override_settings(ADC_CLINICAL_SYNTHETIC=False)
        self.production.enable()
        self.addCleanup(self.production.disable)
        self.project = ExaminationProject.objects.create(service=self.service, code='TEXT-SITE',
            name='本店文本检查', operating_mode=ExaminationProject.Mode.SITE)
        ExaminationDuty.objects.create(project=self.project, user=self.doc, kind='EXECUTE')
        ExaminationDuty.objects.create(project=self.project, user=self.reviewer, kind='REVIEW')

    def approve_fixture_scopes(self):
        # Documentary-shaped evidence is confined to this database; no credentials
        # or professional qualifications from a real institution are represented.
        for user, independent in ((self.doc, self.reviewer), (self.reviewer, self.doc)):
            self.ctx(independent, 'DENTIST')
            fields = self.fields(user, source_kind='DOCUMENT', source_reference='ISOLATED-STAFF-CHECK',
                issuer='隔离库用例材料')
            proposed = prepare_authority(actor=self.manager, action='PROPOSE', fields=fields)
            scope, _ = confirm_authority(actor=self.manager, proposal_token=proposed['proposal_token'], confirmed=True)
            self.decide(scope, 'APPROVE', actor=independent)
        self.ctx(self.reviewer, 'DENTIST')

    def configure(self, action, *options):
        call_command('configure_site_examination', '--operator', self.tech.username,
            '--service', str(self.service.pk), '--code', self.project.code, action, *options, stdout=StringIO())

    def test_suspend_and_reopen_does_not_revive_unconfirmed_staff_requests(self):
        self.approve_fixture_scopes()
        order = self.execute(self.open_order())
        self.step(order, 'SUBMIT', body='仅存在于隔离测试库的检查结果。')
        self.step(order, 'APPROVE', self.reviewer)
        new_request = self.prepare_order()
        release = self.prepare_step(order, 'PUBLISH')
        self.configure('suspend')
        self.configure('provision', '--name', self.project.name, '--examiner', self.doc.username,
            '--reviewer', self.reviewer.username)
        self.project.refresh_from_db()
        self.assertEqual(self.project.operating_revision, 3)
        for old_proposal in (new_request, release):
            with self.assertRaises(RuleError):
                examinations.confirm(actor=self.doc, proposal_token=old_proposal, confirmed=True)
        self.assertEqual(examinations.orders().count(), 1)
        self.assertFalse(ExaminationNotice.objects.filter(event__order=order).exists())
        self.step(order, 'PUBLISH')
        self.assertEqual(ExaminationNotice.objects.filter(event__order=order).count(), 1)

    def test_direct_queue_and_action_match_site_scope_and_independent_roles(self):
        with self.assertRaises(PermissionDenied):
            self.open_order()
        self.approve_fixture_scopes()
        self.assertEqual(list(examinations.eligible_projects(self.v)), [self.project])
        order = self.execute(self.open_order())
        self.step(order, 'SUBMIT', body='本次报告内容仅供获准查看的人员使用。')
        with self.assertRaises(PermissionDenied):
            self.prepare_step(order, 'APPROVE', self.doc)
        self.assertFalse(ExaminationNotice.objects.filter(event__order=order).exists())
        self.step(order, 'APPROVE', self.reviewer)
        token = self.prepare_step(order, 'PUBLISH')
        order, replay = examinations.confirm(actor=self.doc, proposal_token=token, confirmed=True)
        self.assertFalse(replay)
        self.assertTrue(examinations.confirm(actor=self.doc, proposal_token=token, confirmed=True)[1])
        self.assertEqual(ExaminationNotice.objects.filter(event__order=order).count(), 1)
        doctor = self.web_client(self.doc)
        for page in ('doctor_home', 'clinical_examinations'):
            self.assertEqual(doctor.get(reverse(page)).status_code, 200)
        self.assertContains(doctor.get(reverse('doctor_home')), reverse('clinical_examinations'))
        self.assertContains(doctor.get(reverse('clinical_encounter', args=[self.v.pk])),
            reverse('clinical_examination_visit', args=[self.v.pk]))
        for response in (doctor.get(reverse('clinical_examinations')),
                doctor.get(reverse('clinical_examination_visit', args=[self.v.pk])),
                self.front_web.get(reverse('clinical_examination_progress'))):
            self.assertContains(response, order.number)
            self.assertNotContains(response, self.rehearsal.number)
        front_queue = self.front_web.get(reverse('clinical_examination_progress'))
        self.assertContains(front_queue, self.v.visit_no)
        self.assertNotContains(front_queue, '本次报告内容仅供获准查看的人员使用。')
        self.assertEqual(doctor.get(reverse('clinical_examination', args=[self.rehearsal.pk])).status_code, 404)
        self.assertEqual(self.front_web.get(reverse('clinical_examination', args=[order.pk])).status_code, 403)
        self.front_web.post(reverse('activate_clinic'), {'clinic': self.b.pk})
        self.assertEqual(self.front_web.get(reverse('clinical_examination_progress')).status_code, 404)

    def test_paused_project_retains_visit_without_reusing_previous_release(self):
        self.approve_fixture_scopes()
        order = self.release(self.open_order())
        revisit = self.linked_return(order)
        independent = self.instruction()
        adopted = self.release(self.open_order(), instruction=independent.pk)
        visit_no = revisit.visit_no
        doctor_page = self.web_client(self.doc).get(reverse('clinical_examination', args=[order.pk]))
        front_page = self.front_web.get(reverse('clinical_next_list'))
        for page in (doctor_page, front_page):
            self.assertContains(page, self.v.visit_no)
            self.assertContains(page, visit_no)
        self.ctx(self.doc, 'DENTIST')
        self.assertEqual(return_visits.patient_sources(revisit, patient_access(self.patient_user))[0]['report']['id'],
            order.pk)
        token = self.prepare_step(order, 'WITHDRAW', reason='隔离库操作')
        self.project.operating_mode = ExaminationProject.Mode.SUSPENDED
        self.project.save(update_fields=['operating_mode'])
        with self.assertRaises(Http404):
            examinations.confirm(actor=self.doc, proposal_token=token, confirmed=True)
        with self.assertRaises(RuleError):
            examination_followup.reschedule_window(revisit)
        with self.assertRaises(RuleError):
            examination_followup.treatment_basis(revisit, None)
        source = return_visits.patient_sources(revisit, patient_access(self.patient_user))[0]
        self.assertEqual((source['state'], source['report']), ('CONTACT', None))
        self.assertEqual(list(next_visits.front_instructions(self.front).values_list('pk', flat=True)), [independent.pk])
        self.assertEqual(list(recall.scoped_instructions(self.front).values_list('pk', flat=True)), [independent.pk])
        self.assertTrue(next_visits.instruction_booking_projection(independent)['report_review'])
        revisit.refresh_from_db()
        self.assertEqual((revisit.visit_no, revisit.status), (visit_no, 'SCHEDULED'))
        self.assertEqual(ExaminationNotice.objects.filter(event__order=order).count(), 1)
        self.assertEqual(ExaminationNotice.objects.filter(event__order=adopted).count(), 1)
