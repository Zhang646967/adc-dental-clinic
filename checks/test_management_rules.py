"""Executable pure policies; these do not replace PostgreSQL integration tests."""
import ast
import hashlib
from datetime import date,datetime
from decimal import Decimal
from pathlib import Path
import unittest
from adc_core.rules import RuleError,quarter_bounds
from finance.policies import CostInput,calculate_profit,money,safe_csv_cell
from operations.policies import summarize,percent,period_bounds
from care.correction_rules import correction_values,guard_review
D=Decimal
ROOT=Path(__file__).resolve().parents[1]

class FinancialPolicyTests(unittest.TestCase):
    def result(self,income=None,costs=None,confirmed=True):
        return calculate_profit(income or {1:D('100000'),2:D('20000')},costs if costs is not None else [CostInput(1,'CONFIRMED',D('20000'),D('30000')),CostInput(2,'CONFIRMED',D('15000'),D('15000'))],confirmed)
    def test_case_net_40000_fund_4000(self):
        r=self.result();self.assertTrue(r.ready);self.assertEqual(r.profit,D('40000'));self.assertEqual(r.fund,D('4000'))
    def test_missing_not_zero(self):
        r=self.result(costs=[CostInput(1,'MISSING',None,None)]);self.assertFalse(r.ready);self.assertIsNone(r.profit)
    def test_unconfirmed_roster_blocks(self):self.assertFalse(self.result(confirmed=False).ready)
    def test_empty_roster_blocks(self):self.assertFalse(self.result(costs=[]).ready)
    def test_draft_cost_blocks(self):self.assertFalse(self.result(costs=[CostInput(1,'DRAFT',D(0),D(0))]).ready)
    def test_confirmed_zero_is_valid(self):
        r=self.result(income={1:D('10')},costs=[CostInput(1,'CONFIRMED',D(0),D(0))]);self.assertTrue(r.ready);self.assertEqual(r.fund,D('1'))
    def test_zero_income_cost_is_not_dropped(self):
        r=self.result(income={1:D('100')},costs=[CostInput(1,'CONFIRMED',D('10'),D('10')),CostInput(2,'CONFIRMED',D('30'),D('20'))]);self.assertEqual(r.profit,D('30'))
    def test_earner_missing_from_roster_blocks(self):
        r=self.result(costs=[CostInput(1,'CONFIRMED',D(0),D(0))]);self.assertEqual(r.off_roster_ids,(2,))
    def test_zero_bill_earner_still_requires_roster(self):
        r=self.result(income={1:D(0),2:D(0)},costs=[CostInput(1,'CONFIRMED',D(0),D(0))]);self.assertFalse(r.ready)
    def test_negative_total_fund_none(self):
        r=self.result(income={1:D('1')},costs=[CostInput(1,'CONFIRMED',D('5'),D('5'))]);self.assertEqual(r.profit,D('-9'));self.assertIsNone(r.fund)
    def test_zero_profit_fund_none(self):
        r=self.result(income={1:D('10')},costs=[CostInput(1,'CONFIRMED',D('5'),D('5'))]);self.assertIsNone(r.fund)
    def test_fund_half_up(self):
        r=self.result(income={1:D('0.05')},costs=[CostInput(1,'CONFIRMED',D(0),D(0))]);self.assertEqual(r.fund,D('0.01'))
    def test_duplicate_roster_rejected(self):
        with self.assertRaises(RuleError):self.result(costs=[CostInput(1,'CONFIRMED',D(0),D(0))]*2)
    def test_none_confirmed_not_valid(self):
        r=self.result(costs=[CostInput(1,'CONFIRMED',None,D(0))]);self.assertFalse(r.ready)
    def test_money_finite(self):
        for x in ('NaN','Infinity','-1','1.001',1.5,True):
            with self.subTest(value=x),self.assertRaises(RuleError):money(x)
    def test_money_decimal(self):self.assertEqual(money('0'),D('0.00'))
    def test_csv_formula_neutralized(self):
        for s in ('=1+1','  +CMD','-1+2','@SUM(A1)','\tX','\rX','\nX'):
            self.assertTrue(safe_csv_cell(s).startswith("'"))
    def test_csv_ordinary_text(self):self.assertEqual(safe_csv_cell('牙医A'),'牙医A')
    def test_quarter_utc_offset(self):
        a,b=quarter_bounds(2026,4);self.assertEqual(b.year,2027);self.assertEqual(a.utcoffset().total_seconds(),28800)

class OperationalPolicyTests(unittest.TestCase):
    def groups(self):return [('COMPLETED','',80),('CANCELLED','PATIENT',10),('NO_SHOW','',5),('CANCELLED','CLINIC',3),('SCHEDULED','',2)]
    def test_documented_example(self):
        m=summarize(self.groups());self.assertEqual(m.denominator,95);self.assertEqual(m.cancel_rate,D('10.53'));self.assertEqual(m.completeness,D('98'))
    def test_empty_denominator_none(self):self.assertIsNone(summarize([]).cancel_rate)
    def test_empty_completeness_none(self):self.assertIsNone(summarize([]).completeness)
    def test_no_treatment_is_arrival(self):self.assertEqual(summarize([('CLOSED_NO_TREATMENT','',1)]).arrived,1)
    def test_clinic_cancel_not_patient(self):
        m=summarize([('CANCELLED','CLINIC',10)]);self.assertEqual(m.patient_cancel,0);self.assertIsNone(m.cancel_rate);self.assertEqual(m.completeness,D('100'))
    def test_replaced_excluded(self):self.assertEqual(summarize(self.groups()+[('RESCHEDULED','',50)]),summarize(self.groups()))
    def test_unknown_is_pending(self):self.assertEqual(summarize([('UNKNOWN','',3)]).pending,3)
    def test_aggregate_not_mean_percent(self):
        m=summarize([('CANCELLED','PATIENT',1),('COMPLETED','',99)]);self.assertEqual(m.cancel_rate,D('1'))
    def test_negative_count_rejected(self):
        with self.assertRaises(RuleError):summarize([('COMPLETED','',-1)])
    def test_bad_percent(self):
        for pair in [(2,1),(-1,1),(1,-2)]:
            with self.subTest(pair=pair),self.assertRaises(RuleError):percent(*pair)
    def test_end_date_inclusive(self):
        a,b=period_bounds(date(2026,9,1),date(2026,9,30));self.assertEqual(b.day,1);self.assertEqual(b.month,10)
    def test_excessive_range_rejected(self):
        with self.assertRaises(RuleError):period_bounds(date(2024,1,1),date(2026,1,1))
    def test_reverse_dates_rejected(self):
        with self.assertRaises(RuleError):period_bounds(date(2026,1,2),date(2026,1,1))

class CorrectionPolicyTests(unittest.TestCase):
    def test_rounding(self):self.assertEqual(correction_values('1.125','99.99','误录')[2],D('112.49'))
    def test_zero_price_with_reason(self):self.assertEqual(correction_values('1','0','公益演示')[2],D('0'))
    def test_zero_quantity_not_no_treatment(self):
        with self.assertRaises(RuleError):correction_values('0','10','不能改成无治疗')
    def test_reason_required(self):
        with self.assertRaises(RuleError):correction_values('1','10','  ')
    def test_separate_actors_required(self):
        with self.assertRaises(RuleError):guard_review(1,1,'OPEN',2,2,3,3)
    def test_old_invoice_rejected(self):
        with self.assertRaises(RuleError):guard_review(1,2,'OPEN',2,4,3,3)
    def test_stale_visit_rejected(self):
        with self.assertRaises(RuleError):guard_review(1,2,'OPEN',2,2,3,4)
    def test_closed_request_rejected(self):
        with self.assertRaises(RuleError):guard_review(1,2,'APPLIED',2,2,3,3)
    def test_approved_preconditions(self):self.assertIsNone(guard_review(1,2,'OPEN',2,2,3,3))

class ArchitectureContractTests(unittest.TestCase):
    def test_finance_hides_version_storage(self):
        for rel in ('finance/services.py','finance/selectors.py'):
            self.assertNotIn('current_record_version',(ROOT/rel).read_text())
    def test_no_cross_app_private_scheduling_import(self):
        self.assertNotIn("from finance.", (ROOT/"care/corrections.py").read_text())
        for rel in ('care/services.py','portal/services.py'):
            tree=ast.parse((ROOT/rel).read_text())
            for n in ast.walk(tree):
                if isinstance(n,ast.ImportFrom) and (n.module or '').startswith('scheduling'):
                    self.assertTrue(all(not a.name.startswith('_') for a in n.names))
    def test_financial_policy_no_framework_dependency(self):
        for rel in ('finance/policies.py','operations/policies.py','care/correction_rules.py'):
            text=(ROOT/rel).read_text();self.assertNotIn('from django',text);self.assertNotIn('import django',text)
    def test_new_migrations_additive(self):
        self.assertIn('AddField',(ROOT/'finance/migrations/0002_quarter_lock_version.py').read_text())
        self.assertNotIn('RemoveField',(ROOT/'finance/migrations/0002_quarter_lock_version.py').read_text())
    def test_ai_has_no_financial_write_dependency(self):
        for p in (ROOT/'assistants').glob('*.py'):
            self.assertNotIn('from finance.services',p.read_text());self.assertNotIn('from care.corrections',p.read_text())
