"""One synthetic appointment carried through the existing clinical and financial commands."""
import json
from datetime import timedelta
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from care.corrections import request_line_correction, review_correction
from care.models import Invoice, TreatmentRecord
from clinical import recall
from clinical.encounters import current_record
from clinical.plan_models import PlanAppointment
from finance.cash_models import CashEntry
from finance.cash_selectors import invoice_balance
from finance.cash_services import confirm_cash_request, confirm_cash_review, prepare_cash, prepare_review
from finance.payment_account_services import confirm_account, prepare_account
from portal import relationships, rescheduling
from portal.models import PatientAccess, PatientAppointmentGrant
from registry.models import TreatmentType
from scheduling.models import Visit
from scheduling.resource_models import ServicePresentation
from scheduling.service_content import draft_from_guide
from scheduling.services import change_appointment
from tests.test_treatment_continuity import PlanFixture
from tests.workspace_client import WorkspaceClient


class VisitReviewWorkflowTests(PlanFixture, TransactionTestCase):
    password = 'synthetic-visit-review-only'

    def setUp(self):
        self.setup_authority()
        self.authorize()
        self.item = TreatmentType.objects.create(code='VISIT-REVIEW', name='课程实际处置',
            unit_definition='次', standard_unit_price=Decimal('100.00'))
        self.patient_user = UserAccount.objects.create_user(username='visit_review_owner', password=self.password)
        PatientAccess.objects.create(user=self.patient_user, patient=self.p1)
        self.ctx(self.patient_user, 'PATIENT')
        ServicePresentation.objects.create(service=self.service, **dict(
            draft_from_guide('CHECKUP'), title='课程初诊检查', is_published=True))
        self.web = self.web_client(self.patient_user)
        self.mini = self.mini_client(self.patient_user)
        self.front_web = self.web_client(self.front)

    def web_client(self, actor):
        client = WorkspaceClient()
        client.force_login(actor)
        return client

    def mini_client(self, actor):
        client = Client(enforce_csrf_checks=True)
        csrf = client.get(reverse('mini_session')).json()['data']['csrf_token']
        login = client.post(reverse('mini_login'), {'username': actor.username, 'password': self.password},
            HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(login.status_code, 200, login.content)
        return client

    def book_and_arrive(self):
        confirm = reverse('portal_confirm')
        preview = self.web.get(confirm, {'slot': self.slot1.pk, 'start': self.t.isoformat(), 'service': self.service.pk})
        self.assertEqual(preview.status_code, 200, preview.content)
        response = self.web.post(confirm, {'token': preview.context['form'].initial['token'], 'confirmed': 'on'})
        self.v = Visit.objects.get(patient=self.p1)
        self.assertRedirects(response, reverse('portal_visit', args=[self.v.pk]), fetch_redirect_response=False)
        self.arrive(self.v)

    def arrive(self, visit):
        checked = self.front_web.post(reverse('visit_detail', args=[visit.pk]),
            {'action': 'check_in', 'expected_version': visit.lock_version})
        self.assertEqual(checked.status_code, 302, checked.content)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'CHECKED_IN')

    def complete_case(self, *, progress='COMPLETE', charge_mode='CHARGE'):
        self.clinical(self.v)
        plan = self.new_plan(charge_basis='ON_COMPLETION' if progress == 'PARTIAL' else 'PER_EXECUTION')
        step = self.publish_plan(plan).steps.get()
        self.decision(step)
        self.actual(step, progress=progress, charge_mode=charge_mode,
            reason='课程阶段处置，按完成节点计费' if charge_mode == 'NO_CHARGE' else '')
        self.review()
        instruction = self.instruction()
        closed = self.web_client(self.doc).post(reverse('care_complete', args=[self.v.pk]),
            {'expected_version': self.v.lock_version, 'outcome': 'TREATED', 'confirmed': 'on'})
        self.assertEqual(closed.status_code, 302, closed.content)
        self.v.refresh_from_db()
        return Invoice.objects.get(visit=self.v), instruction

    def record_cash(self, invoice, *, kind='RECEIPT', amount='40.00'):
        if not hasattr(self, 'finance'):
            self.finance = UserAccount.objects.create_user(username='visit_review_finance')
            RoleAssignment.objects.create(user=self.finance, role='FINANCE', scope_kind='CHAIN')
            self.ctx(self.finance, 'FINANCE')
            account = prepare_account(actor=self.finance, clinic_id=self.a.pk, code='VISIT-REVIEW', method='CASH')
            self.payment_account, _ = confirm_account(actor=self.finance,
                proposal_token=account['proposal_token'], confirmed=True)
        request = prepare_cash(actor=self.front, source_type='invoice', source_id=invoice.pk,
            kind=kind, amount=Decimal(amount), occurred_on=timezone.localdate(), reason='课程合成现金核对',
            payment_account_id=self.payment_account.pk, reference='SYNTHETIC-VISIT-' + kind)
        entry, _ = confirm_cash_request(actor=self.front, proposal_token=request['proposal_token'], confirmed=True)
        reviewed = prepare_review(actor=self.finance, entry_id=entry.pk, decision='approve', reason='独立核对合成凭据')
        confirm_cash_review(actor=self.finance, proposal_token=reviewed['proposal_token'], confirmed=True)

    def book_followup(self, instruction, *, hours=2):
        followup = self.booking(start=self.t + timedelta(hours=hours))
        url = reverse('clinical_next_link', args=[instruction.pk])
        preview = self.front_web.post(url, {'phase': 'preview', 'visit': followup.pk})
        self.assertEqual(preview.status_code, 200, preview.content)
        form = preview.context['form']
        values = {field.name: field.value() for field in form}
        response = self.front_web.post(url, dict(values, phase='confirm', confirmed='on'))
        self.assertEqual(response.status_code, 302, response.content)
        self.assertTrue(PlanAppointment.objects.filter(instruction=instruction, visit=followup).exists())
        return followup

    def review_responses(self, web_client=None, mini_client=None):
        web = (web_client or self.web).get(reverse('portal_visit', args=[self.v.pk]))
        native = (mini_client or self.mini).get(reverse('mini_visit', args=[self.v.pk]))
        self.assertContains(web, self.v.visit_no)
        self.assertEqual(native.status_code, 200, native.content)
        data = native.json()['data']
        self.assertEqual((data['id'], data['visit_no']), (self.v.pk, self.v.visit_no))
        self.assertEqual(data['review'], json.loads(json.dumps(web.context['review'], cls=DjangoJSONEncoder)))
        self.assertEqual((web['Cache-Control'], native['Cache-Control']), ('no-store', 'no-store'))
        return web, data

    def create_delegate(self):
        delegate = UserAccount.objects.create_user(username='visit_review_delegate', password=self.password)
        RoleAssignment.objects.filter(user=self.front, role='FRONT_DESK', clinic=self.a).update(
            can_verify_patient_relationships=True)
        token = relationships.prepare_create(actor=self.front, patient_no=self.p1.patient_no,
            related_name='课程合成代约人', kind='DELEGATE', username=delegate.username, note='课程合成预约代办')
        case, _ = relationships.confirm(actor=self.front, token=token, confirmed=True)
        token = relationships.prepare_action(actor=self.front, case_id=case.pk, action='VERIFY',
            basis='IN_PERSON', reference='VISIT-REVIEW-SYNTHETIC', note='已核对课程合成代约关系',
            valid_until=timezone.now()+timedelta(days=14))
        relationships.confirm(actor=self.front, token=token, confirmed=True)
        return delegate, case, PatientAppointmentGrant.objects.get(relationship=case)

    def create_other(self):
        other = UserAccount.objects.create_user(username='visit_review_other', password=self.password)
        PatientAccess.objects.create(user=other, patient=self.p2)
        self.ctx(other, 'PATIENT')
        return other

    def test_one_visit_from_booking_to_financial_and_followup_facts(self):
        self.book_and_arrive()
        _, active = self.review_responses()
        self.assertEqual(active['status'], 'CHECKED_IN')
        self.assertTrue(active['review']['attended_at'])
        self.assertIsNone(active['review']['completed_at'])
        self.assertIsNone(active['review']['care'])
        self.assertIsNone(active['review']['settlement'])

        invoice, instruction = self.complete_case()
        self.record_cash(invoice)
        self.assertEqual(self.review_responses()[1]['review']['followups'][0]['status'], 'WAITING')
        followup = self.book_followup(instruction)
        models = (Visit, Invoice, TreatmentRecord, PlanAppointment, CashEntry)
        counts = [model.objects.count() for model in models]
        web, data = self.review_responses()
        self.review_responses()
        self.assertEqual([model.objects.count() for model in models], counts)
        self.assertContains(web, reverse('portal_invoice', args=[invoice.pk]))
        self.assertContains(web, followup.visit_no)
        self.assertNotContains(web, 'PRIVATE_')
        self.assertNotIn('PRIVATE_', json.dumps(data['review']))
        self.assertEqual(data['invoice_id'], invoice.pk)
        self.assertEqual(invoice_balance(invoice)['remaining'], Decimal('60.00'))
        review = data['review']
        self.assertEqual(data['status'], 'COMPLETED')
        self.assertTrue(review['completed_at'])
        self.assertEqual(review['care']['outcome'], 'TREATED')
        self.assertEqual(review['care']['treatments'], [dict(name=self.item.name, unit='次', quantity='1.000', kind='CHARGED')])
        self.assertEqual(review['settlement']['total'], '100.00')
        self.assertEqual(review['settlement']['remaining'], '60.00')
        self.assertEqual(review['followups'][0]['status'], 'BOOKED')
        self.assertEqual(review['followups'][0]['appointment']['id'], followup.pk)

        proposal = rescheduling.prepare(actor=self.patient_user, visit_id=followup.pk,
            expected_version=followup.lock_version, slot_id=self.slot1.pk, start=self.t+timedelta(hours=3),
            reason='课程合成：调整复诊时间')
        rescheduling.confirm(actor=self.patient_user, visit_id=followup.pk,
            proposal_token=proposal['proposal_token'], confirmed=True)
        replacement = Visit.objects.get(replaces_visit=followup)
        self.assertEqual(self.review_responses()[1]['review']['followups'][0]['appointment']['id'], replacement.pk)

        change_appointment(actor=self.front, visit_id=replacement.pk, expected_version=replacement.lock_version,
            action='cancel', party='PATIENT', reason='课程合成：患者稍后重新安排复诊')
        self.record_cash(invoice, kind='REFUND', amount='10.00')
        _, data = self.review_responses()
        review = data['review']
        self.assertEqual(review['settlement']['remaining'], '70.00')
        self.assertEqual(review['followups'][0]['status'], 'WAITING')
        self.assertEqual(review['followups'][0]['appointment']['status'], 'CANCELLED')

        self.v.refresh_from_db()
        correction = request_line_correction(actor=self.doc, visit_id=self.v.pk,
            expected_version=self.v.lock_version, line_id=invoice.current_record_version.treatment_lines.get().pk,
            quantity=Decimal('2'), unit_price=Decimal('100.00'), reason='课程合成：核对账单数量更正')
        review_correction(actor=self.finance, request_id=correction.pk, decision='approve', reason='独立核对更正')
        _, data = self.review_responses()
        self.assertEqual(data['review']['care']['treatments'], review['care']['treatments'])
        self.assertEqual(data['review']['settlement']['revision'], 2)
        self.assertEqual(data['review']['settlement']['total'], '200.00')
        self.assertEqual(data['review']['settlement']['remaining'], '170.00')

        attended_followup = self.book_followup(instruction, hours=4)
        self.arrive(attended_followup)
        record = current_record(self.clinical(attended_followup))
        attended_followup.refresh_from_db()
        closed = self.web_client(self.doc).post(reverse('care_complete', args=[attended_followup.pk]),
            {'expected_version': attended_followup.lock_version, 'outcome': 'NO_TREATMENT',
             'reason': '课程合成：完成复诊检查', 'confirmed': 'on'})
        followup_invoice = Invoice.objects.get(visit=attended_followup)
        self.assertRedirects(closed, reverse('invoice_detail', args=[followup_invoice.pk]), fetch_redirect_response=False)
        self.assertEqual(followup_invoice.current_record_version.outcome, 'NO_TREATMENT')
        self.assertEqual(self.review_responses()[1]['review']['followups'][0]['status'], 'REVIEW')
        opened = recall.prepare_recall(actor=self.front, action='OPEN', instruction_id=instruction.pk,
            fields={'followup_due_at': (timezone.now()+timedelta(hours=2)).isoformat()})
        episode, _ = recall.confirm_recall(actor=self.front, proposal_token=opened['proposal_token'], confirmed=True)
        verified = recall.prepare_recall(actor=self.front, action='COMPLETE', episode_id=episode.pk,
            fields={'evidence_kind': 'RECORD', 'evidence_id': record.pk})
        recall.confirm_recall(actor=self.front, proposal_token=verified['proposal_token'], confirmed=True)
        _, data = self.review_responses()
        completed = data['review']['followups'][0]
        self.assertEqual((completed['status'], completed['appointment']['id']), ('COMPLETED', attended_followup.pk))

    def test_non_billable_stage_still_reports_treatment(self):
        self.book_and_arrive()
        self.complete_case(progress='PARTIAL', charge_mode='NO_CHARGE')
        web, data = self.review_responses()
        self.assertEqual(data['review']['care']['outcome'], 'TREATED')
        self.assertEqual(data['review']['care']['treatments'][0]['kind'], 'NO_CHARGE_STAGE')
        self.assertEqual(data['review']['settlement']['total'], '0.00')
        self.assertContains(web, '本次不另计费')

    def test_other_patient_and_revoked_delegate_cannot_read_results(self):
        self.book_and_arrive()
        invoice, instruction = self.complete_case()
        self.book_followup(instruction)
        visit_url = reverse('portal_visit', args=[self.v.pk])
        mini_url = reverse('mini_visit', args=[self.v.pk])
        other = self.create_other()
        self.assertEqual(self.web_client(other).get(visit_url).status_code, 404)
        self.assertEqual(self.mini_client(other).get(mini_url).status_code, 404)

        delegate, case, grant = self.create_delegate()
        subject = {'subject': f'grant:{grant.pk}'}
        web_client, mini_client = self.web_client(delegate), self.mini_client(delegate)
        self.assertEqual(web_client.post(reverse('portal_subjects'), subject).status_code, 302)
        session = mini_client.get(reverse('mini_session')).json()['data']
        selected = mini_client.post(reverse('mini_subject_select'), subject,
            HTTP_X_CSRFTOKEN=session['csrf_token'], HTTP_X_ADC_WORKSPACE=session['workspace_token'])
        self.assertEqual(selected.status_code, 200, selected.content)
        web, data = self.review_responses(web_client, mini_client)
        self.assertIsNone(data['invoice_id'])
        self.assertIsNone(data['review']['care'])
        self.assertIsNone(data['review']['settlement'])
        self.assertEqual(data['review']['followups'], [])
        self.assertNotContains(web, '本次就诊结果')
        self.assertNotContains(web, invoice.invoice_no)
        self.assertEqual(web_client.get(reverse('portal_invoice', args=[invoice.pk])).status_code, 403)
        self.assertEqual(mini_client.get(reverse('mini_invoice', args=[invoice.pk])).status_code, 403)

        token = relationships.prepare_action(actor=self.front, case_id=case.pk, action='REVOKE', note='课程合成撤销代约授权')
        relationships.confirm(actor=self.front, token=token, confirmed=True)
        self.assertEqual(web_client.get(visit_url).status_code, 302)
        rejected = mini_client.get(mini_url)
        self.assertEqual(rejected.status_code, 409)
        self.assertNotIn(self.v.visit_no, rejected.content.decode())
