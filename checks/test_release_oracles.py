"""Fixed external-to-production expected literals. No database pass implied."""
import json
from pathlib import Path
from decimal import Decimal
from datetime import datetime
import unittest
from adc_core.rules import line_amount,total_amount,quarter_bounds,RuleError
from finance.policies import calculate_profit,CostInput
from operations.policies import summarize
DATA=json.loads((Path(__file__).resolve().parents[1]/'tests/data/release_oracles.json').read_text())
def normalize(x):
    if isinstance(x,Decimal):return format(x,'.2f')
    if isinstance(x,tuple):return list(x)
    return x
class ReleaseOracles(unittest.TestCase):
    def test_expected_lines_against_integer_reference(self):
        # q is integer thousandths, p integer cents: no production arithmetic.
        for row in DATA['lines']:
            q=int(Decimal(row['quantity'])*1000);p=int(Decimal(row['price'])*100)
            cents=(q*p+500)//1000
            self.assertEqual(f'{cents//100}.{cents%100:02d}',row['expected'],row['id'])
    def test_actual_line_rounding(self):
        for r in DATA['lines']:
            with self.subTest(r['id']):self.assertEqual(str(line_amount(r['quantity'],r['price'],r.get('reason',''))),r['expected'])
    def test_sum_rounded_rows_not_round_sum(self):
        c=DATA['row_rounding'];actual=total_amount(line_amount(x['quantity'],x['price']) for x in c['lines'])
        self.assertEqual(str(actual),c['expected_total']);self.assertNotEqual(str(actual),c['incorrect_round_after_sum'])
    def test_financial_fixed_scenarios(self):
        for c in DATA['finance']:
            with self.subTest(c['id']):
                costs=[CostInput(i,s,None if a is None else Decimal(a),None if b is None else Decimal(b)) for i,s,a,b in c['costs']]
                result=calculate_profit({int(k):Decimal(v) for k,v in c['income'].items()},costs,c['roster'])
                for k,v in c['expected'].items():self.assertEqual(normalize(getattr(result,k)),v,k)
    def test_financial_literal_independent_integer_identity(self):
        c=DATA['finance'][0];e=c['expected']
        self.assertEqual(19998-1000-2000-5000-5000,6998)
        self.assertEqual(e['profit'],'69.98');self.assertEqual(e['fund'],'7.00')
    def test_operations_fixed_scenarios(self):
        for c in DATA['operations']:
            with self.subTest(c['id']):
                actual=summarize(c['groups'])
                for k,v in c['expected'].items():self.assertEqual(normalize(getattr(actual,k)),v,k)
    def test_expected_denominator_not_all_rows(self):
        e=DATA['operations'][0]['expected'];self.assertEqual(e['denominator'],6+2+1)
        self.assertNotEqual(e['denominator'],sum(r[2] for r in DATA['operations'][0]['groups']))
    def test_quarter_half_open_beijing_boundaries(self):
        for c in DATA['boundaries']:
            instant=datetime.fromisoformat(c['instant']);a,b=quarter_bounds(c.get('year',2026),c['quarter'])
            self.assertTrue(a<=instant<b,c)
    def test_zero_price_needs_reason(self):
        with self.assertRaises(RuleError):line_amount('1','0')
    def test_floating_input_is_not_silently_rounded(self):
        with self.assertRaises(RuleError):line_amount(1.125,'99.99')
    def test_duplicate_dentist_cost_rejected(self):
        c=CostInput(1,'CONFIRMED',Decimal('0'),Decimal('0'))
        with self.assertRaises(RuleError):calculate_profit({},[c,c],True)
    def test_oracle_ids_unique(self):
        ids=[r['id'] for group in ('lines','finance','operations') for r in DATA[group]]
        self.assertEqual(len(ids),len(set(ids)))
