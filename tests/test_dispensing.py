"""C4.2 command, HTTP, money-source and PostgreSQL race acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D
from threading import Barrier
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.http import Http404
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from adc_core.rules import RuleError
from care.corrections import request_medication_correction, review_correction
from care.insurance_facts import insurance_bill
from care.invoice_queries import published_invoice
from care.models import Invoice, MedicationCharge, TreatmentRecord
from care.services import complete_visit
from clinical import dispensing, prescriptions
from clinical.pharmacy_models import DispenseMovement, PharmacyQuote, PharmacyStop
from clinical.prescription_models import PrescriptionDuty
from finance.cash_models import CashEntry
from finance.cash_selectors import invoice_balance
from finance.cash_services import confirm_cash_request, confirm_cash_review, prepare_cash, prepare_review
from finance.reconciliation_models import PaymentAccount
from portal.models import PatientAccess
from registry.models import Allergy
from tests.test_prescription_review import PrescriptionFixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext


class DispensingFixture(PrescriptionFixture):
    def setup_dispensing(self):
        self.setup_prescription_fixture()
        self.configure('dispensing', '--pharmacist', self.rx_user.username, '--price', 'C41-SIM-A=12.50')
        self.version = self.submit(entries=[dict(self.rows()[0], quantity=6)])
        self.case = self.version.prescription
        self.fin = UserAccount.objects.create_user(username='synthetic_finance')
        RoleAssignment.objects.create(user=self.fin, role='FINANCE', scope_kind='CHAIN')
        self.ctx(self.fin, 'FINANCE')
        self.patient = UserAccount.objects.create_user(username='synthetic_rx_patient')
        PatientAccess.objects.create(user=self.patient, patient=self.visit.patient)
        self.ctx(self.patient, 'PATIENT')

    def approve(self):
        _, token = prescriptions.prepare_decision(self.rx_user,self.version,'APPROVED','合成审方核对')
        prescriptions.confirm(self.rx_user,token,True)
        return self.version

    def plan(self, kind, actor=None, **values):
        self.visit.refresh_from_db()
        self.case.visit = self.visit
        return dispensing.prepare(actor or self.rx_user,self.case,kind,'合成办理依据',**values)[1]

    def perform(self,kind,**values):
        return dispensing.confirm(self.rx_user,self.plan(kind,**values),True)[0]

    def priced(self):
        self.approve()
        return self.perform('QUOTE').lines.get()

    def close(self,outcome='PHARMACY_ONLY'):
        self.visit.refresh_from_db()
        return complete_visit(actor=self.doc,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
                              outcome=outcome,reason='课程合成关闭核对')

    def cash(self, invoice, kind, amount):
        operation=uuid4()
        account, _ = PaymentAccount.objects.get_or_create(clinic=self.a, code='SYNTHETIC_RX',
            defaults=dict(method='CASH', created_by=self.fin, operation_id=operation, last_operation_id=operation))
        request = prepare_cash(actor=self.front, source_type='invoice', source_id=invoice.pk,
            kind=kind, amount=amount, occurred_on=timezone.localdate(), reason='合成资金核对',
            payment_account_id=account.pk, reference='SYNTHETIC-'+uuid4().hex)
        entry = confirm_cash_request(actor=self.front, proposal_token=request['proposal_token'], confirmed=True)[0]
        decision = prepare_review(actor=self.fin, entry_id=entry.pk, decision='approve',reason='独立核对原始凭据')
        return confirm_cash_review(actor=self.fin,proposal_token=decision['proposal_token'],confirmed=True)[0]


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_PRESCRIPTION_REHEARSAL=True, ADC_DISPENSING_REHEARSAL=True)
class DispensingTests(DispensingFixture, TransactionTestCase):
    def setUp(self):
        self.setup_dispensing()

    def test_staff_http_prices_partial_dispensing_stop_and_complete(self):
        self.approve()
        pharmacy = WorkspaceClient()
        pharmacy.force_login(self.rx_user)
        self.assertContains(pharmacy.get(reverse('dispensing_queue')), f'处方 #{self.case.pk}')
        path=reverse('dispensing_detail',args=[self.case.pk])
        confirm=reverse('dispensing_confirm',args=[self.case.pk])
        self.assertNotContains(pharmacy.get(path),'PRIVATE_EXAMINATION_NOT_FOR_PHARMACY')

        def act(kind, **fields):
            prefix=kind.lower()
            preview=pharmacy.post(path, {'action':kind, f'{prefix}-reason':'核对本次演练依据',
                                         **{f'{prefix}-{key}':value for key,value in fields.items()}})
            self.assertEqual(preview.status_code, 200)
            data=dict(proposal_token=preview.context['form'].initial['proposal_token'], confirmed='on')
            self.assertRedirects(pharmacy.post(confirm, data),path,fetch_redirect_response=False)
            self.assertRedirects(pharmacy.post(confirm, data),path,fetch_redirect_response=False)

        act('QUOTE')
        line=PharmacyQuote.objects.get().lines.get()
        act('ISSUE',line=line.pk,quantity=4)
        act('STOP')
        self.assertEqual((PharmacyQuote.objects.count(),DispenseMovement.objects.count(),PharmacyStop.objects.count()),
                         (1,1,1))
        self.assertFalse(Invoice.objects.exists() or CashEntry.objects.exists() or TreatmentRecord.objects.exists())
        doctor=WorkspaceClient()
        doctor.force_login(self.doc)
        close=reverse('care_complete',args=[self.visit.pk])
        self.assertContains(doctor.get(close),'50.00')
        self.visit.refresh_from_db()
        closed=doctor.post(close,dict(expected_version=self.visit.lock_version,outcome='PHARMACY_ONLY',confirmed='on'))
        self.assertEqual(closed.status_code,302)
        invoice=Invoice.objects.get()
        self.assertEqual(invoice.current_record_version.total_amount,D('50'))
        self.assertEqual(invoice.current_record_version.outcome,'PHARMACY_ONLY')
        self.assertContains(doctor.get(closed.url),'实际发退药费用')
        self.assertFalse(TreatmentRecord.objects.exists() or CashEntry.objects.exists())

    def test_approved_review_and_complete_disposition_required(self):
        with self.assertRaisesMessage(RuleError,'独立审方通过'):
            self.plan('QUOTE')
        with self.assertRaisesMessage(RuleError,'仍待审方'):
            self.close('NO_TREATMENT')
        self.approve()
        with self.assertRaisesMessage(RuleError,'实际发药或明确取消'):
            self.close()
        self.perform('STOP')
        with self.assertRaisesMessage(RuleError,'已停止'):
            self.plan('QUOTE')
        self.assertEqual(self.close('NO_TREATMENT').current_record_version.total_amount,D('0'))

    def test_prices_rechecked_and_already_quoted_price_retained(self):
        self.approve()
        stale=self.plan('QUOTE')
        self.configure('dispensing','--pharmacist',self.rx_user.username,'--price','C41-SIM-A=15.25')
        with self.assertRaisesMessage(RuleError,'重新预览'):
            dispensing.confirm(self.rx_user,stale,True)
        line=self.perform('QUOTE').lines.get()
        self.configure('dispensing','--pharmacist',self.rx_user.username,'--price','C41-SIM-A=20.00')
        self.perform('ISSUE',line_id=line.pk,quantity=6)
        invoice=self.close()
        self.assertEqual(invoice.current_record_version.total_amount,D('91.50'))
        self.assertEqual(self.close().pk,invoice.pk)
        with self.assertRaisesMessage(RuleError,'其他结果'):
            self.close('TREATED')
        with self.assertRaisesMessage(RuleError,'按自费'):
            insurance_bill(invoice)

    def test_expired_approval_can_stop_but_cannot_create_new_issue(self):
        line=self.priced()
        token=self.plan('ISSUE',line_id=line.pk,quantity=1)
        with override_settings(ADC_DISPENSING_REHEARSAL=False), self.assertRaises(Http404):
            dispensing.confirm(self.rx_user,token,True)
        from unittest.mock import patch
        with patch.object(dispensing,'APPROVAL_LIFETIME',timedelta(seconds=-1)):
            with self.assertRaisesMessage(RuleError,'窗口已到期'):
                self.plan('ISSUE',line_id=line.pk,quantity=1)
            self.perform('STOP')
        self.assertFalse(DispenseMovement.objects.exists())

    def test_confirmed_allergy_change_blocks_issue_and_keeps_stop_and_return(self):
        line = self.priced()
        issue = self.perform('ISSUE', line_id=line.pk, quantity=2)
        stale = self.plan('ISSUE', line_id=line.pk, quantity=1)
        allergy = Allergy.objects.create(code='C42-VERIFIED', name='发药前新核实合成过敏条目')
        self.review_confirmed_allergies('KNOWN', [allergy.pk])

        with self.assertRaisesMessage(RuleError, '请停止剩余调配'):
            dispensing.confirm(self.rx_user, stale, True)
        self.assertEqual(list(DispenseMovement.objects.values_list('pk', flat=True)), [issue.pk])
        self.perform('STOP')
        returned = self.perform('RETURN', line_id=line.pk, issue_id=issue.pk, quantity=1)
        self.assertEqual((returned.original_issue_id, returned.quantity), (issue.pk, 1))

    def test_dispense_only_direct_urls_reject_pending_and_rejected(self):
        user = UserAccount.objects.create_user(username='synthetic_dispense_only')
        RoleAssignment.objects.create(user=user, clinic=self.a, role='PHARMACIST', scope_kind='CLINIC')
        now = timezone.now()
        PrescriptionDuty.objects.create(user=user, clinic=self.a, kind='DISPENSE', reference='C42-SYNTHETIC',
                                        valid_from=now-timedelta(hours=1), valid_until=now+timedelta(hours=1))
        pharmacy = WorkspaceClient()
        pharmacy.force_login(user)
        detail = reverse('dispensing_detail', args=[self.case.pk])
        confirmation = reverse('dispensing_confirm', args=[self.case.pk])
        for state in ('PENDING', 'REJECTED'):
            with self.subTest(state=state):
                if state == 'REJECTED':
                    _, token = prescriptions.prepare_decision(self.rx_user, self.version, 'REJECTED', '合成拒绝')
                    prescriptions.confirm(self.rx_user, token, True)
                queue = pharmacy.get(reverse('dispensing_queue'))
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(list(queue.context['page'].object_list), [])
                self.assertEqual(pharmacy.get(detail).status_code, 404)
                self.assertEqual(pharmacy.post(detail, {'action': 'QUOTE'}).status_code, 404)
                self.assertEqual(pharmacy.post(confirmation, {'confirmed': 'on'}).status_code, 404)

    def test_revoked_duty_and_wrong_store_cannot_issue(self):
        line=self.priced()
        stale=self.plan('ISSUE',line_id=line.pk,quantity=1)
        self.configure('revoke','--user',self.rx_user.username,'--duty','DISPENSE')
        with self.assertRaises(PermissionDenied):
            dispensing.confirm(self.rx_user,stale,True)
        outsider=UserAccount.objects.create_user(username='other_pharmacy')
        RoleAssignment.objects.create(user=outsider,clinic=self.b,role='PHARMACIST',scope_kind='CLINIC')
        PrescriptionDuty.objects.create(user=outsider,clinic=self.b,kind='DISPENSE',reference='C42-SYNTHETIC',
            valid_from=timezone.now()-timedelta(hours=1),valid_until=timezone.now()+timedelta(hours=1))
        other=WorkspaceClient()
        other.force_login(outsider)
        self.assertEqual(other.get(reverse('dispensing_detail',args=[self.case.pk])).status_code,404)
        self.assertFalse(DispenseMovement.objects.exists())

    def test_post_close_return_needs_independent_version_and_cash_refund(self):
        line=self.priced()
        issued=self.perform('ISSUE',line_id=line.pk,quantity=6)
        invoice=self.close()
        original=invoice.current_record_version
        self.cash(invoice,'RECEIPT',D('75.00'))
        self.perform('RETURN',line_id=line.pk,issue_id=issued.pk,quantity=2)
        invoice.refresh_from_db()
        self.assertEqual(invoice.current_record_version_id,original.pk)
        self.assertEqual(invoice_balance(invoice)['net_received'],D('75'))
        self.visit.refresh_from_db()
        correction=request_medication_correction(actor=self.doc,visit_id=self.visit.pk,
            expected_version=self.visit.lock_version,reason='核对退回两单位')
        with self.assertRaises(PermissionDenied):
            review_correction(actor=self.rx_user,request_id=correction.pk,decision='approve',reason='未经授权')
        review_correction(actor=self.fin,request_id=correction.pk,decision='approve',reason='独立核对退药费用')
        invoice.refresh_from_db()
        self.assertEqual(invoice.current_record_version.total_amount,D('50'))
        self.assertEqual(original.total_amount,D('75'))
        self.assertEqual(invoice_balance(invoice)['refund_due'],D('25'))
        self.cash(invoice,'REFUND',D('25'))
        self.assertEqual(invoice_balance(invoice)['net_received'],D('50'))
        self.assertEqual(invoice_balance(invoice)['refund_due'],D('0'))
        self.assertEqual((Invoice.objects.count(),CashEntry.objects.count(),TreatmentRecord.objects.count()),(1,2,0))
        historical=published_invoice(invoice,revision=1)
        self.assertEqual((historical['medication_lines'][0]['quantity'],historical['total']), (6,D('75')))
        self.assertFalse(historical['is_current'])
        self.assertEqual(published_invoice(invoice)['medication_lines'][0]['quantity'],4)
        patient=WorkspaceClient()
        patient.force_login(self.patient)
        url=reverse('portal_invoice',args=[invoice.pk])
        self.assertContains(patient.get(url),'实际发退药费用')
        native=reverse('mini_invoice',args=[invoice.pk])
        current=patient.get(native).json()['data']
        self.assertEqual(current['treatment_lines'],[])
        self.assertEqual(current['medication_lines'][0]['quantity'],4)
        self.assertEqual(current['lines'][0]['line_amount'],'50.00')
        self.assertTrue(current['lines'][0]['name_snapshot'].startswith('药费 · '))
        self.assertEqual(patient.get(native,{'revision':1}).json()['data']['medication_lines'][0]['quantity'],6)
        other=UserAccount.objects.create_user(username='other_rx_patient')
        PatientAccess.objects.create(user=other,patient=self.p2)
        patient.force_login(other)
        self.assertEqual(patient.get(url).status_code,404)
        self.assertEqual(patient.get(native).status_code,404)

    def test_stale_correction_does_not_hide_another_return(self):
        line=self.priced()
        issue=self.perform('ISSUE',line_id=line.pk,quantity=6)
        invoice=self.close()
        self.perform('RETURN',line_id=line.pk,issue_id=issue.pk,quantity=1)
        self.visit.refresh_from_db()
        req=request_medication_correction(actor=self.doc,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
                                          reason='核对一单位')
        self.perform('RETURN',line_id=line.pk,issue_id=issue.pk,quantity=5)
        with self.assertRaisesMessage(RuleError,'版本已经变化'):
            review_correction(actor=self.fin,request_id=req.pk,decision='approve',reason='须重核')
        review_correction(actor=self.fin,request_id=req.pk,decision='reject',reason='已有新的实际退药')
        self.visit.refresh_from_db()
        second=request_medication_correction(actor=self.doc,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
                                             reason='核对全量退回')
        result=review_correction(actor=self.fin,request_id=second.pk,decision='approve',reason='独立核对')
        self.assertEqual(result.pk,invoice.pk)
        self.assertEqual(result.current_record_version.total_amount,D('0'))
        self.assertEqual(result.current_record_version.medication_lines.get().quantity,0)
        self.assertEqual(DispenseMovement.objects.count(),3)
        with self.assertRaisesMessage(RuleError,'可退数量'):
            self.plan('RETURN',line_id=line.pk,issue_id=issue.pk,quantity=1)

    def test_two_connections_cannot_issue_over_the_approved_quantity(self):
        line=self.priced()
        tokens=[self.plan('ISSUE',line_id=line.pk,quantity=4) for _ in range(2)]
        barrier=Barrier(2,timeout=10)

        def issue(token):
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.rx_user.pk)
                actor._adc_workspace=WorkspaceContext.objects.get(pk=self.rx_user._adc_workspace.pk)
                barrier.wait()
                return dispensing.confirm(actor,token,True)[0].pk
            except RuleError as exc:
                return str(exc)
            finally:
                connections['default'].close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(issue,tokens))
        self.assertEqual(sum(isinstance(result,int) for result in outcomes),1)
        self.assertTrue(any('剩余授权' in str(result) for result in outcomes))
        self.assertEqual(DispenseMovement.objects.get().quantity,4)

    def test_database_protects_movement_and_charge_sources(self):
        line=self.priced()
        issue=self.perform('ISSUE',line_id=line.pk,quantity=6)
        with self.assertRaises(DatabaseError),transaction.atomic():
            DispenseMovement.objects.create(line=line,kind='RETURN',quantity=1,actor=issue.actor,duty=issue.duty,
                                             reason='跨来源负例',operation_id=uuid4())
        with self.assertRaises(DatabaseError),transaction.atomic():
            DispenseMovement.objects.filter(pk=issue.pk).update(quantity=5)
        self.close()
        with self.assertRaises(DatabaseError),transaction.atomic():
            MedicationCharge.objects.update(quantity=5,line_amount=D('62.50'))
        connection=connections['default']
        executor=MigrationExecutor(connection)
        applied=set(executor.loader.applied_migrations)
        # A failed downgrade must leave dependent migrations applied for the next test.
        with self.assertRaisesMessage(RuntimeError,'Medication billing history exists'),transaction.atomic():
            executor.migrate([('care','0004_c42_medication_charges')])
        self.assertEqual(set(MigrationExecutor(connection).loader.applied_migrations),applied)
        self.assertEqual(MedicationCharge.objects.get().quantity,6)
