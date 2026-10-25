"""Real PostgreSQL tests for retained local results and financial ownership."""
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import DatabaseError, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice, TreatmentRecord, VisitRecordVersion
from care.corrections import request_line_correction, review_correction
from finance.cash_models import CashEntry
from finance.cash_services import confirm_cash_request
from finance.cash_selectors import receivables
from insurance import services as prep
from insurance import settlement_services as svc
from insurance.settlement_source import quote_source
from insurance.settlement_models import SettlementRequest, SettlementLine, SimulationOutcome, SettlementReview, SettlementEvent
from tests.test_care_finance_equipment import CFEFixture, activate


class SettlementFixture(CFEFixture):
    def setup_settlement(self):
        self.setup_cfe()
        self.service.standard_unit_price=D('500.00'); self.service.save(update_fields=['standard_unit_price'])
        from accounts.models import UserAccount
        self.second_fin=UserAccount.objects.create_user(username='independent_source_finance',password='synthetic-only')
        RoleAssignment.objects.create(user=self.second_fin,role='FINANCE',scope_kind='CHAIN')
        activate(self.second_fin,'FINANCE')
        self.cat=self.prepare_insurance(prep.prepare_catalogue(actor=self.fin),self.fin)
        self.review_preparation(self.cat,'catalogue',self.second_fin)
        self.arrangement=self.prepare_insurance(prep.prepare_arrangement(actor=self.manager,catalogue_id=self.cat.pk,
            starts_on=self.today,ends_on=self.today+timedelta(days=30),reference='SIM-COURSE-ARRANGEMENT'),self.manager)
        self.review_preparation(self.arrangement,'arrangement',self.fin)
        self.mapping=self.prepare_insurance(prep.prepare_mapping(actor=self.manager,treatment_type_id=self.service.pk,
            policy_item_id=self.cat.items.filter(payment_class='A',unit__isnull=False).first().pk,
            policy_units_per_fee='1',compatibility_basis='合成场景逐项核对收费和目录含义及单位，不代表真实资格'),self.manager)
        self.review_preparation(self.mapping,'mapping',self.fin)
        self.eligibility=self.eligibility_fact()
        self.visit,self.invoice=self.billed()

    def prepare_insurance(self,preview,actor):
        return prep.confirm_preparation(actor=actor,proposal_token=preview['proposal_token'],confirmed=True)[0]

    def review_preparation(self,row,kind,actor):
        p=prep.prepare_review(actor=actor,kind=kind,pk=row.pk,decision='approve',reason='逐项核对合成资料')
        return prep.confirm_review(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]

    def eligibility_fact(self,state='VERIFIED'):
        return self.prepare_insurance(prep.prepare_eligibility(actor=self.front,patient_id=self.p1.pk,
            insured_region='CN-43',scheme='EMPLOYEE',state=state,starts_on=self.today,
            ends_on=self.today+timedelta(days=30),reference='SIM-ELIGIBILITY-COURSE',basis='明确本地合成核对结果'),self.front)

    def request_preview(self,**kw):
        data=dict(actor=self.front,invoice_id=self.invoice.pk,simulation_mode='ACCEPT',reason='合成分担结果逐项确认',
            allocations=[dict(treatment_record=self.invoice.current_record_version.treatment_lines.get().pk,
                patient_cash='300.00',personal_account='200.00',fund_amount='500.00')])
        data.update(kw); return svc.prepare_settlement(**data)

    def settlement(self,**kw):
        p=self.request_preview(**kw)
        return svc.confirm_settlement(actor=kw.get('actor',self.front),proposal_token=p['proposal_token'],confirmed=True)[0]

    def query(self,row,actor=None):
        actor=actor or self.front
        p=svc.prepare_query(actor=actor,request_id=row.pk)
        return svc.confirm_query(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]

    def review_settlement(self,row,actor=None,decision='APPROVE'):
        actor=actor or self.fin
        p=svc.prepare_settlement_review(actor=actor,request_id=row.pk,decision=decision,reason='逐项核对原账单及模拟结果')
        return svc.confirm_settlement_review(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]

    def disable_source(self,row,kind):
        p=prep.prepare_disable(actor=self.fin,kind=kind,pk=row.pk,reason='停用原资料，历史保留')
        prep.confirm_disable(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)


@override_settings(ADC_CLINICAL_SYNTHETIC=True,ADC_READ_ONLY=False)
class InsuranceSettlementTests(SettlementFixture,TransactionTestCase):
    def setUp(self): self.setup_settlement()

    def test_preview_does_not_create_claim_money_or_treatment(self):
        counts=(Invoice.objects.count(),TreatmentRecord.objects.count(),CashEntry.objects.count())
        p=self.request_preview()
        self.assertEqual(p['source']['total'],'1000.00')
        self.assertEqual(p['source']['record_version'],self.invoice.current_record_version_id)
        self.assertFalse(SettlementRequest.objects.exists())
        self.assertEqual(counts,(Invoice.objects.count(),TreatmentRecord.objects.count(),CashEntry.objects.count()))
        self.assertNotIn('clinical_note',p['source']); self.assertNotIn(self.p1.name,str(p['source']))

    def test_only_independently_reviewed_non_cash_changes_patient_responsibility(self):
        row=self.settlement()
        self.assertEqual(row.state,'AWAITING_REVIEW'); self.assertEqual(self.balance(self.invoice)['remaining'],D('1000'))
        self.review_settlement(row)
        b=self.balance(self.invoice)
        self.assertEqual([b[k] for k in ('billed','net_received','insurance_personal_account','insurance_fund','remaining')],
            [D('1000'),D('0'),D('200'),D('500'),D('300')])
        self.assertFalse(CashEntry.objects.exists()); self.assertEqual(TreatmentRecord.objects.count(),1)
        self.approve(self.cash(self.invoice,amount='300'))
        self.assertEqual(self.balance(self.invoice)['remaining'],D('0'))
        self.assertEqual(self.balance(self.invoice)['net_received'],D('300'))
        with self.assertRaises(RuleError): self.cash_preview(self.invoice,amount='0.01')

    def test_full_self_payment_then_review_requires_explicit_refund(self):
        self.approve(self.cash(self.invoice,amount='1000'))
        self.review_settlement(self.settlement())
        b=self.balance(self.invoice); self.assertEqual(b['refund_due'],D('700')); self.assertEqual(b['net_received'],D('1000'))
        self.assertEqual(CashEntry.objects.count(),1)
        self.approve(self.cash(self.invoice,kind='REFUND',amount='700'))
        b=self.balance(self.invoice); self.assertEqual((b['net_received'],b['refund_due'],b['remaining']),(D('300'),D('0'),D('0')))

    def test_partial_payment_and_review_keep_billed_revenue(self):
        self.approve(self.cash(self.invoice,amount='100'))
        self.review_settlement(self.settlement())
        b=self.balance(self.invoice); self.assertEqual((b['billed'],b['remaining'],b['net_received']),(D('1000'),D('200'),D('100')))

    def test_lost_success_queries_same_request_without_resubmission(self):
        row=self.settlement(simulation_mode='LOST_SUCCESS'); original_id=row.request_id
        self.assertEqual(row.state,'UNKNOWN'); self.assertEqual(row.simulation_outcome.result,'ACCEPTED')
        with self.assertRaisesMessage(RuleError,'原医保请求'): self.request_preview()
        with self.assertRaisesMessage(RuleError,'医保请求'): self.cash_preview(self.invoice)
        with self.assertRaises(RuleError): self.review_settlement(row)
        row=self.query(row); self.assertEqual(row.state,'AWAITING_REVIEW'); self.assertEqual(row.request_id,original_id)
        self.review_settlement(row)
        self.assertEqual(SettlementRequest.objects.count(),1); self.assertEqual(SimulationOutcome.objects.count(),1)
        self.assertEqual(list(row.events.order_by('sequence').values_list('action',flat=True)),['SUBMIT','QUERY','REVIEW'])

    def test_processing_result_can_be_queried_by_finance(self):
        row=self.settlement(simulation_mode='PROCESSING')
        self.assertEqual(row.state,'PROCESSING'); self.query(row,self.fin)
        row.refresh_from_db(); self.assertEqual(row.state,'AWAITING_REVIEW')

    def test_declined_result_has_no_credit_and_allows_explicit_new_request(self):
        first=self.settlement(simulation_mode='DECLINE')
        self.assertEqual(first.state,'DECLINED'); self.assertEqual(self.balance(self.invoice)['remaining'],D('1000'))
        second=self.settlement(); self.assertNotEqual(first.request_id,second.request_id)
        first.refresh_from_db(); self.assertEqual(first.state,'DECLINED')

    def test_replay_returns_original_current_result_after_review(self):
        p=self.request_preview()
        row,_=svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.review_settlement(row)
        replay,again=svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(again); self.assertEqual((replay.pk,replay.state),(row.pk,'CONFIRMED'))
        self.assertEqual(row.events.count(),2)

    def test_query_and_review_replays_do_not_append_second_decision(self):
        row=self.settlement(simulation_mode='LOST_SUCCESS')
        p=svc.prepare_query(actor=self.front,request_id=row.pk)
        for _ in range(2): svc.confirm_query(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        p=svc.prepare_settlement_review(actor=self.fin,request_id=row.pk,decision='APPROVE',reason='独立确认')
        for _ in range(2): svc.confirm_settlement_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(SettlementReview.objects.count(),1); self.assertEqual(SettlementEvent.objects.count(),3)

    def test_rejected_review_keeps_external_result_and_blocks_duplicate_claim(self):
        row=self.review_settlement(self.settlement(),decision='REJECT')
        self.assertEqual(row.state,'REVIEW_REJECTED'); self.assertEqual(row.simulation_outcome.result,'ACCEPTED')
        self.assertEqual(self.balance(self.invoice)['remaining'],D('1000'))
        with self.assertRaises(RuleError): self.request_preview()
        with self.assertRaises(RuleError): self.cash_preview(self.invoice)

    def test_pending_cash_blocks_claim_but_rejection_releases_it(self):
        entry=self.cash(self.invoice)
        with self.assertRaisesMessage(RuleError,'收退款待审'): self.request_preview()
        self.approve(entry,decision='reject'); self.settlement()

    def test_cash_change_after_claim_preview_is_stale(self):
        p=self.request_preview(); self.approve(self.cash(self.invoice))
        with self.assertRaisesMessage(RuleError,'已变化'):
            svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(SettlementRequest.objects.exists())

    def test_cash_preview_before_declined_claim_cannot_revive(self):
        p=self.cash_preview(self.invoice); self.settlement(simulation_mode='DECLINE')
        with self.assertRaisesMessage(RuleError,'医保结算进度已变化'):
            confirm_cash_request(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(CashEntry.objects.exists())

    def test_old_claim_preview_cannot_revive_after_another_declined_attempt(self):
        p=self.request_preview(); self.settlement(simulation_mode='DECLINE')
        with self.assertRaisesMessage(RuleError,'新的医保办理历史'):
            svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(SettlementRequest.objects.count(),1)

    def test_latest_unknown_eligibility_invalidates_confirmation_and_review(self):
        p=self.request_preview(); self.eligibility_fact('UNKNOWN')
        with self.assertRaises(RuleError): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.eligibility_fact(); row=self.settlement(); self.eligibility_fact('UNKNOWN')
        with self.assertRaises(RuleError): self.review_settlement(row)
        self.review_settlement(row,decision='REJECT')

    def test_disabled_mapping_invalidates_unreviewed_result_but_retains_confirmed_credit(self):
        row=self.settlement(); self.disable_source(self.mapping,'mapping')
        with self.assertRaises(RuleError): self.review_settlement(row)
        self.review_settlement(row,decision='REJECT')

    def test_later_source_disable_does_not_rewrite_confirmed_amounts(self):
        row=self.review_settlement(self.settlement()); old=row.source_snapshot
        self.disable_source(self.cat,'catalogue')
        row.refresh_from_db(); self.assertEqual(row.source_snapshot,old)
        self.assertEqual(self.balance(self.invoice)['remaining'],D('300'))

    def test_missing_mapping_keeps_explicit_cash_exception(self):
        self.disable_source(self.mapping,'mapping')
        with self.assertRaisesMessage(RuleError,'缺少可核对适配'): self.request_preview()
        allocations=[dict(treatment_record=self.invoice.current_record_version.treatment_lines.get().pk,
            patient_cash='1000',personal_account='0',fund_amount='0')]
        row=self.review_settlement(self.settlement(allocations=allocations))
        self.assertIsNone(row.lines.get().mapping_id); self.assertTrue(row.lines.get().exception)
        self.assertEqual(self.balance(self.invoice)['remaining'],D('1000'))

    def test_cross_clinic_and_non_financial_roles_cannot_quote_or_query(self):
        row=self.settlement()
        for actor in (self.front2,self.manager,self.hq,self.doctor,self.pa,self.tech):
            with self.subTest(role=actor._adc_workspace.role):
                with self.assertRaises((PermissionDenied,ObjectDoesNotExist)): quote_source(actor,self.invoice.pk)
                with self.assertRaises((PermissionDenied,ObjectDoesNotExist)): svc.prepare_query(actor=actor,request_id=row.pk)

    def test_preparer_cannot_review_by_switching_role(self):
        row=self.settlement(); RoleAssignment.objects.create(user=self.front,role='FINANCE',scope_kind='CHAIN')
        activate(self.front,'FINANCE')
        with self.assertRaises(PermissionDenied): self.review_settlement(row,actor=self.front)

    def test_revoked_front_grant_blocks_confirmation_and_later_approval(self):
        p=self.request_preview()
        grant=RoleAssignment.objects.get(user=self.front,clinic=self.a,role='FRONT_DESK')
        grant.is_active=False; grant.save(update_fields=['is_active'])
        with self.assertRaises(PermissionDenied): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        grant.is_active=True; grant.save(update_fields=['is_active']); row=self.settlement()
        grant.is_active=False; grant.save(update_fields=['is_active'])
        with self.assertRaises(RuleError): self.review_settlement(row)
        self.review_settlement(row,decision='REJECT')

    def test_revoked_reviewer_after_preview_cannot_confirm(self):
        row=self.settlement(); p=svc.prepare_settlement_review(actor=self.fin,request_id=row.pk,decision='APPROVE',reason='独立核对')
        RoleAssignment.objects.filter(user=self.fin,role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied): svc.confirm_settlement_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        row.refresh_from_db(); self.assertEqual(row.state,'AWAITING_REVIEW')

    def test_preview_tamper_wrong_page_and_expiry_do_not_create_effect(self):
        p=self.request_preview()
        with self.assertRaises(RuleError): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token']+'x',confirmed=True)
        with self.assertRaises(RuleError): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True,expected_invoice_id=self.invoice.pk+1)
        with patch('django.core.signing.time.time',return_value=signing.time.time()+1000):
            with self.assertRaises(RuleError): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(SettlementRequest.objects.exists())

    def test_audit_failure_rolls_back_all_new_tables(self):
        p=self.request_preview()
        with patch('insurance.settlement_services.emit',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        for model in (SettlementRequest,SettlementLine,SimulationOutcome,SettlementReview,SettlementEvent):
            self.assertEqual(model.objects.count(),0)

    def test_immutable_money_result_lines_and_review(self):
        row=self.review_settlement(self.settlement())
        for qs,changes in [(SettlementRequest.objects.filter(pk=row.pk),dict(patient_cash=D('500'),fund_amount=D('300'))),
            (row.lines.all(),dict(patient_cash=D('500'),fund_amount=D('300'))),
            (SimulationOutcome.objects.filter(request=row),dict(result='DECLINED')),
            (SettlementReview.objects.filter(request=row),dict(reason='覆盖原决定')),
            (row.events.all(),dict(reason='覆盖历史'))]:
            with self.subTest(table=qs.model._meta.db_table):
                with self.assertRaises(DatabaseError),transaction.atomic(): qs.update(**changes)

    def test_database_requires_distinct_reviewer_and_exact_source_lines(self):
        row=self.settlement()
        from uuid import uuid4
        with self.assertRaises(DatabaseError),transaction.atomic():
            SettlementReview.objects.create(request=row,operation_id=uuid4(),reviewed_by=self.front,
                decision='APPROVE',reason='试图自行复核',source_digest=row.source_digest)
        line=dict(row.lines.values().get()); line.pop('id'); line['line_no']=2
        with self.assertRaises(DatabaseError),transaction.atomic(): SettlementLine.objects.create(**line)

    def test_correction_waits_for_claim_resolution_and_pending_correction_blocks_claim(self):
        self.settlement(); self.visit.refresh_from_db()
        with self.assertRaisesMessage(RuleError,'未终结医保请求'):
            request_line_correction(actor=self.doctor,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
                line_id=self.invoice.current_record_version.treatment_lines.get().pk,quantity=D('1'),unit_price=D('500'),reason='误录更正')
        self.assertEqual(VisitRecordVersion.objects.count(),1)

    def test_pending_correction_can_be_rejected_then_original_bill_claimed(self):
        self.visit.refresh_from_db()
        req=request_line_correction(actor=self.doctor,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
            line_id=self.invoice.current_record_version.treatment_lines.get().pk,quantity=D('1'),unit_price=D('500'),reason='误录更正')
        with self.assertRaisesMessage(RuleError,'费用更正'): self.request_preview()
        review_correction(actor=self.fin,request_id=req.pk,decision='reject',reason='核对后原账单正确')
        self.settlement()

    def test_list_uses_same_independent_amounts_without_clinical_notes(self):
        self.review_settlement(self.settlement())
        with CaptureQueriesContext(connection) as queries: data=receivables(self.fin)
        self.assertLess(len(queries),30)
        self.assertEqual(data['totals']['billed'],D('1000')); self.assertEqual(data['totals']['remaining'],D('300'))
        self.assertEqual(data['totals']['insurance_fund'],D('500')); self.assertEqual(data['rows'][0].net_received,D('0'))

    def test_concurrent_two_front_desks_create_one_request(self):
        activate(self.front2,'FRONT_DESK',self.a)
        previews=[self.request_preview(actor=actor) for actor in (self.front,self.front2)]
        def call(index):
            actor=self.actor_copy((self.front,self.front2)[index])
            try: return ('ok',svc.confirm_settlement(actor=actor,proposal_token=previews[index]['proposal_token'],confirmed=True)[0].pk)
            except RuleError: return ('conflict',None)
        result=self.race(call)
        self.assertEqual(sorted(x[0] for x in result),['conflict','ok']); self.assertEqual(SettlementRequest.objects.count(),1)

    def test_concurrent_same_operation_replays_one_result(self):
        p=self.request_preview()
        def call(index):
            return svc.confirm_settlement(actor=self.actor_copy(self.front),proposal_token=p['proposal_token'],confirmed=True)
        result=self.race(call)
        self.assertEqual(result[0][0].pk,result[1][0].pk); self.assertEqual(sorted(x[1] for x in result),[False,True])
        self.assertEqual(SettlementEvent.objects.count(),1)

    def test_concurrent_receipt_and_settlement_cannot_both_take_effect(self):
        activate(self.front2,'FRONT_DESK',self.a)
        p=self.request_preview(); cash=self.cash_preview(self.invoice,actor=self.front2)
        def call(index):
            try:
                if index==0: svc.confirm_settlement(actor=self.actor_copy(self.front),proposal_token=p['proposal_token'],confirmed=True)
                else: confirm_cash_request(actor=self.actor_copy(self.front2),proposal_token=cash['proposal_token'],confirmed=True)
                return 'ok'
            except RuleError: return 'conflict'
        self.assertEqual(sorted(self.race(call)),['conflict','ok'])
        self.assertEqual(SettlementRequest.objects.count()+CashEntry.objects.count(),1)

    def test_concurrent_reviewers_apply_one_decision(self):
        row=self.settlement()
        previews=[svc.prepare_settlement_review(actor=actor,request_id=row.pk,decision='APPROVE',reason='独立核对') for actor in (self.fin,self.second_fin)]
        def call(index):
            try: svc.confirm_settlement_review(actor=self.actor_copy((self.fin,self.second_fin)[index]),proposal_token=previews[index]['proposal_token'],confirmed=True); return 'ok'
            except RuleError: return 'conflict'
        self.assertEqual(sorted(self.race(call)),['conflict','ok']); self.assertEqual(SettlementReview.objects.count(),1)

    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_non_synthetic_write_cannot_activate_local_adapter(self):
        p=self.request_preview()
        with self.assertRaises(PermissionDenied): svc.confirm_settlement(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
