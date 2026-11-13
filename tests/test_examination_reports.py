"""PostgreSQL and HTTP coverage for exam release after ordinary clinical closure."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
from io import StringIO
from threading import Barrier

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.db import DatabaseError, close_old_connections, transaction
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from adc_core.rules import RuleError
from care.services import complete_visit
from clinical import archive_generation, examinations as cmd, preflight
from clinical.archive_models import ArchivePackage
from clinical.authority_services import confirm_authority, prepare_authority
from clinical.examination_models import ExaminationDuty, ExaminationProject
from clinical.models import SensitiveReadEvent
from registry.models import TreatmentType
from scheduling.resource_models import BookingService, Department
from tests import test_medical_archives as archives
from tests import test_patient_visit_review as reviews

BODY1 = '课程合成报告第一版：记录原观察结果。'
BODY2 = '课程合成报告第二版：复核后更正观察结果。'
SOURCE = 'PRIVATE_EXAM_SOURCE_REFERENCE'


class ExaminationFixture(reviews.VisitReviewFixture, archives.ArchiveFixture):
    """Used by isolated browser fixtures as well as the tests below."""

    def setup_examinations(self):
        self.setup_visit_review()
        self.appoint(self.doc, self.a)
        self.ctx(self.doc, 'DENTIST')
        request = prepare_authority(actor=self.manager, action='PROPOSE', fields=self.fields(self.reviewer))
        self.review_scope, _ = confirm_authority(actor=self.manager, proposal_token=request['proposal_token'], confirmed=True)
        self.decide(self.review_scope, 'APPROVE', actor=self.doc)
        self.archive_duty(True)
        self.project_config('provision', '--name', '课程文本检查', '--examiner', self.doc.username,
            '--reviewer', self.reviewer.username)
        self.project = ExaminationProject.objects.get(service=self.service, code='COURSE-TEXT')
        self.book_and_arrive()
        self.clinical(self.v)

    def project_config(self, action, *args):
        call_command('configure_examination_rehearsal', '--synthetic-only', '--operator', self.tech.username,
            '--service', str(self.service.pk), '--code', 'COURSE-TEXT', action, *args, stdout=StringIO())

    def prepare_order(self, purpose='课程合成检查申请'):
        return cmd.prepare_order(self.doc, self.v, self.project.pk, purpose)[1]

    def open_order(self, purpose='课程合成检查申请'):
        return cmd.confirm(actor=self.doc, proposal_token=self.prepare_order(purpose), confirmed=True)[0]

    def prepare_step(self, order, action, actor=None, **fields):
        actor = actor or self.doc
        order.refresh_from_db()
        if action == 'PUBLISH':
            fields.setdefault('followup_kind', 'NONE')
        return cmd.prepare_action(actor, order, action, fields)[1]

    def step(self, order, action, actor=None, **fields):
        actor = actor or self.doc
        token = self.prepare_step(order, action, actor, **fields)
        return cmd.confirm(actor=actor, proposal_token=token, confirmed=True)[0]

    def execute(self, order):
        return self.step(order, 'EXECUTE', performed_at=self.v.attended_at.isoformat(), source_reference=SOURCE)

    def publish(self, order, body=BODY1, reason=''):
        self.step(order, 'SUBMIT', body=body, reason=reason)
        self.step(order, 'APPROVE', self.reviewer)
        return self.step(order, 'PUBLISH')

    def close_and_archive(self):
        self.review()
        for item in TreatmentType.objects.filter(is_active=True):
            rule = preflight.prepare_rule(actor=self.reviewer, clinic_id=self.a.pk, treatment_id=item.pk,
                mode='COMMUNICATION', reference='SYNTHETIC-EXAM-ARCHIVE',
                explanation='课程合成：确认本次实际处置范围。')
            preflight.confirm_rule(actor=self.reviewer, proposal_token=rule['proposal_token'], confirmed=True)
        activation = preflight.prepare_rule(actor=self.reviewer, clinic_id=self.a.pk, activate=True,
            reference='SYNTHETIC-EXAM-ARCHIVE-ACTIVATE')
        preflight.confirm_rule(actor=self.reviewer, proposal_token=activation['proposal_token'], confirmed=True)
        prepared = preflight.prepare(actor=self.doc, visit_id=self.v.pk, fields=self.actual_fields(),
            communication='课程合成：已核对本人、牙位和本次实际处置范围。')
        check, _ = preflight.confirm(actor=self.doc, proposal_token=prepared['proposal_token'], confirmed=True)
        self.actual(preflight=check.pk)
        self.v.refresh_from_db()
        invoice = complete_visit(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version, outcome='TREATED')
        self.v.refresh_from_db()
        self.record_cash(invoice)
        self.save(ancillary_results='课程合成：检查报告待登记。')
        self.confirm_doc()
        submission = self.submit_archive()
        self.approve(submission)
        self.assertTrue(archive_generation.generate(submission.pk)['published'])
        return invoice, ArchivePackage.objects.get(submission=submission)


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ExaminationReportsTests(ExaminationFixture, TransactionTestCase):
    def setUp(self):
        self.setup_examinations()

    def native_report(self, order, revision=None, *, client=None, visit=None):
        case = self
        args = [(visit or case.v).pk, order.pk]
        return (client or case.mini).get(reverse('mini_examination', args=args),
            {'revision': revision} if revision is not None else {})

    def test_normal_web_controls_preview_confirm_and_publish(self):
        case = self
        client = case.web_client(case.doc)
        source = reverse('clinical_examination_visit', args=[case.v.pk])
        form = client.get(source).context['form']
        preview = client.post(source, dict(form.initial, project=case.project.pk, purpose='课程合成：核对申请来源'))
        self.assertContains(preview, '核对开具检查申请')
        self.assertContains(preview, case.v.visit_no)
        confirm_order = reverse('clinical_examination_order_confirm', args=[case.v.pk])
        payload = dict(preview.context['form'].initial, confirmed='on')
        response = client.post(confirm_order, payload)
        self.assertEqual(response.status_code, 302)
        order = cmd.orders().get()
        self.assertRedirects(response, reverse('clinical_examination', args=[order.pk]), fetch_redirect_response=False)
        self.assertEqual(client.post(confirm_order, payload).status_code, 302)
        self.assertEqual(cmd.orders().count(), 1)

        detail = reverse('clinical_examination', args=[order.pk])
        confirm = reverse('clinical_examination_confirm', args=[case.v.pk, order.pk])
        for action, actor, fields in [
            ('EXECUTE', case.doc, dict(performed_at=case.v.attended_at.isoformat(), source_reference=SOURCE)),
            ('SUBMIT', case.doc, dict(body=BODY1)),
            ('APPROVE', case.reviewer, {}),
            ('PUBLISH', case.doc, dict(followup_kind='NONE')),
        ]:
            if action == 'PUBLISH':
                self.assertEqual(self.native_report(order).status_code, 404)
            client = case.web_client(actor)
            selected = next(item['form'] for item in client.get(detail).context['action_forms'] if item['action'] == action)
            response = client.post(detail, dict(selected.initial, action=action, **fields))
            self.assertEqual(response.status_code, 200, response.content[:1000])
            self.assertRedirects(client.post(confirm, dict(response.context['form'].initial, confirmed='on')),
                detail, fetch_redirect_response=False)
        self.assertEqual(self.native_report(order).json()['data']['body'], BODY1)

    def test_return_correction_withdrawal_and_patient_projection(self):
        case = self
        order = case.open_order('PRIVATE_EXAM_PURPOSE')
        self.assertEqual(self.native_report(order).status_code, 404)
        case.execute(order)
        case.publish(order)
        url = reverse('portal_visit', args=[case.v.pk])
        detail = reverse('portal_examination', args=[case.v.pk, order.pk])
        native = self.native_report(order, 1).json()['data']
        web = case.web.get(detail, {'revision': 1})
        self.assertContains(web, BODY1)
        self.assertEqual(web['Cache-Control'], 'no-store')
        self.assertEqual(native, json.loads(json.dumps(web.context['report'], cls=DjangoJSONEncoder)))
        self.assertEqual(native['visit_no'], case.v.visit_no)
        for forbidden in (SOURCE, 'PRIVATE_EXAM_PURPOSE', 'reviewed_by', 'correction_reason'):
            self.assertNotIn(forbidden, json.dumps(native))
        case.step(order, 'SUBMIT', body='课程合成：待审核内容', reason='复核发现差异')
        case.step(order, 'RETURN', case.reviewer, reason='请逐项核对检查依据')
        self.assertEqual(self.native_report(order).json()['data']['revision'], 1)
        case.publish(order, BODY2, reason='按退回意见完成复核')
        self.assertEqual(self.native_report(order).json()['data']['body'], BODY2)
        self.assertEqual(self.native_report(order, 1).status_code, 404)
        self.assertEqual(case.web.get(detail, {'revision': 1}).status_code, 404)
        self.assertEqual(list(order.reports.order_by('number').values_list('number', 'body')),
            [(1, BODY1), (2, '课程合成：待审核内容'), (3, BODY2)])
        case.step(order, 'WITHDRAW', reason='课程核对：原报告待重新确认')
        self.assertEqual(self.native_report(order).status_code, 404)
        self.assertEqual(self.native_report(order, 3).status_code, 404)
        self.assertContains(case.web.get(url), '报告已撤回，请联系门店')
        self.assertNotContains(case.web.get(url), '查看检查报告')
        with self.assertRaises(RuleError):
            case.prepare_step(order, 'PUBLISH')
        self.assertEqual(order.events.filter(action='PUBLISH').count(), 2)
        with self.assertRaises(DatabaseError), transaction.atomic():
            order.reports.filter(number=1).update(body='覆盖历史')
        with self.assertRaises(DatabaseError), transaction.atomic():
            order.events.filter(action='WITHDRAW').delete()

    def test_permissions_and_reviewer_recheck(self):
        case = self
        order = case.open_order()
        case.execute(order)
        case.step(order, 'SUBMIT', body=BODY1)
        with self.assertRaises(PermissionDenied):
            case.prepare_step(order, 'APPROVE')
        token = case.prepare_step(order, 'APPROVE', case.reviewer)
        case.project_config('revoke', '--user', case.reviewer.username, '--duty', 'REVIEW')
        with self.assertRaises(PermissionDenied):
            cmd.confirm(actor=case.reviewer, proposal_token=token, confirmed=True)
        case.project_config('provision', '--name', '课程文本检查', '--examiner', case.doc.username,
            '--reviewer', case.reviewer.username)
        case.step(order, 'APPROVE', case.reviewer)
        pending = case.mini.get(reverse('mini_visit', args=[case.v.pk])).json()['data']['examinations'][0]
        self.assertEqual((pending['state'], pending['revision']), ('PROCESSING', None))
        self.assertEqual(self.native_report(order).status_code, 404)
        case.step(order, 'PUBLISH')
        queue = reverse('clinical_examinations')
        self.assertContains(case.web_client(case.doc).get(queue), order.number)
        self.assertContains(case.web_client(case.reviewer).get(queue), order.number)
        other = case.mini_client(case.create_other())
        self.assertEqual(self.native_report(order, client=other).status_code, 404)
        anon = Client()
        self.assertEqual(self.native_report(order, client=anon).status_code, 401)

        delegate, _, grant = case.create_delegate()
        mini = case.mini_client(delegate)
        session = mini.get(reverse('mini_session')).json()['data']
        response = mini.post(reverse('mini_subject_select'), {'subject': f'grant:{grant.pk}'},
            HTTP_X_CSRFTOKEN=session['csrf_token'], HTTP_X_ADC_WORKSPACE=session['workspace_token'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mini.get(reverse('mini_visit', args=[case.v.pk])).json()['data']['examinations'], [])
        self.assertEqual(self.native_report(order, client=mini).status_code, 403)
        delegated_web = case.web_client(delegate)
        self.assertEqual(delegated_web.post(reverse('portal_subjects'), {'subject': f'grant:{grant.pk}'}).status_code, 302)
        self.assertNotContains(delegated_web.get(reverse('portal_visit', args=[case.v.pk])), order.number)
        self.assertEqual(delegated_web.get(reverse('portal_examination', args=[case.v.pk, order.pk])).status_code, 403)
        self.assertTrue(SensitiveReadEvent.objects.filter(actor=delegate, object_kind='EXAMINATION',
            object_id=order.pk, outcome='DENY').exists())

        progress = reverse('clinical_examination_progress')
        front = case.front_web
        self.assertContains(front.get(progress), order.number)
        self.assertNotContains(front.get(progress), BODY1)
        self.assertNotContains(front.get(progress), SOURCE)
        self.assertEqual(front.get(reverse('clinical_examination', args=[order.pk])).status_code, 403)
        self.assertEqual(front.post(reverse('activate_clinic'), {'clinic': case.b.pk}).status_code, 302)
        self.assertNotContains(front.get(progress), order.number)
        outside = BookingService.objects.create(department=Department.objects.create(
            clinic=case.b, code='EXAM-B', name='异店科室'), code='EXAM-B', name='异店服务')
        project = ExaminationProject.objects.create(service=outside, code='OUTSIDE', name='异店检查')
        with self.assertRaises(RuleError):
            cmd.prepare_order(case.doc, case.v, project.pk, '不能使用其他门店项目')
        with override_settings(ADC_CLINICAL_SYNTHETIC=False):
            self.assertEqual(self.native_report(order).status_code, 404)
            self.assertEqual(case.mini.get(reverse('mini_visit', args=[case.v.pk])).json()['data']['examinations'], [])

        execution = case.open_order()
        ExaminationDuty.objects.create(project=case.project, user=case.reviewer, kind=cmd.Kind.EXECUTE)
        case.step(execution, 'EXECUTE', case.reviewer,
            performed_at=case.v.attended_at.isoformat(), source_reference=SOURCE)
        case.step(execution, 'SUBMIT', body=BODY1)
        with self.assertRaises(PermissionDenied):
            case.prepare_step(execution, 'APPROVE', case.reviewer)

    def test_late_release_retains_invoice_archive_and_exact_followup_link(self):
        case = self
        order = case.open_order()
        instruction = case.instruction()
        _, package = case.close_and_archive()
        archive_facts = (package.pdf_sha256, sha256(bytes(package.pdf)).hexdigest(), package.manifest)
        money = case.money()
        case.execute(order)
        case.publish(order)
        self.assertEqual(self.native_report(order).json()['data']['body'], BODY1)
        package.refresh_from_db()
        self.assertEqual((package.pdf_sha256, sha256(bytes(package.pdf)).hexdigest(), package.manifest), archive_facts)
        self.assertEqual(ArchivePackage.objects.count(), 1)
        self.assertEqual(case.money(), money)

        followup = case.book_followup(instruction, slot=case.slot2)
        reviewer = case.web_client(case.reviewer)
        self.assertContains(reviewer.get(reverse('clinical_examination_visit', args=[followup.pk])), BODY1)
        unrelated = case.booking(slot=case.slot2, start=case.t + timedelta(hours=3))
        self.assertNotContains(reviewer.get(reverse('clinical_examination_visit', args=[unrelated.pk])), BODY1)
        self.assertEqual(self.native_report(order, visit=followup).status_code, 404)

    def test_same_or_competing_confirmations_leave_one_effect(self):
        case = self
        order = case.open_order()
        case.execute(order)
        case.step(order, 'SUBMIT', body=BODY1)
        accept = case.prepare_step(order, 'APPROVE', case.reviewer)
        reject = case.prepare_step(order, 'RETURN', case.reviewer, reason='课程复核退回')
        gate = Barrier(2)

        def decide(token):
            close_old_connections()
            try:
                gate.wait(timeout=10)
                try:
                    _, replay = cmd.confirm(actor=case.reviewer, proposal_token=token, confirmed=True)
                    return replay
                except RuleError:
                    return 'STALE'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(list(workers.map(decide, [accept, reject])), [False, 'STALE'])
        saved = order.events.get(action__in=cmd.REVIEW)
        case.step(order, 'SUBMIT', body=BODY2, reason='课程复核后追加更正')
        token = case.prepare_step(order, 'APPROVE', case.reviewer)
        gate = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(list(workers.map(decide, [token, token])), [False, True])
        self.assertEqual(order.events.filter(action__in=cmd.REVIEW).count(), 2)
        self.assertIn(saved.action, cmd.REVIEW)
        self.assertFalse(order.events.filter(action='PUBLISH').exists())
