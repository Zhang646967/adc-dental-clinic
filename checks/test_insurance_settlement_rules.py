import unittest
from decimal import Decimal
from adc_core.rules import RuleError
from insurance.settlement_rules import source_fund_limit, checked_split, patient_balance


class InsuranceSettlementArithmeticTests(unittest.TestCase):
    def test_class_a_is_a_cap_and_does_not_force_full_reimbursement(self):
        cap = source_fund_limit('1000', payment_class='A', pre_self_pay_percent='0', mapping_usable=True)
        split = checked_split('1000', patient_cash='1000', personal_account='0', fund_amount='0', fund_limit=cap, mapping_usable=True)
        self.assertEqual(cap, 1000)
        self.assertEqual(split['patient_cash'], 1000)

    def test_pre_self_pay_limit_is_floored_to_cent_and_kept_separate(self):
        cap = source_fund_limit('100.01', payment_class='B', pre_self_pay_percent='50', mapping_usable=True)
        self.assertEqual(cap, Decimal('50.00'))
        split = checked_split('100.01', patient_cash='80.01', personal_account='0', fund_amount='20', fund_limit=cap, mapping_usable=True)
        self.assertEqual(split['fund_amount'], 20)

    def test_missing_mapping_or_source_rules_never_generate_fund_limit(self):
        for kind, share, usable in [('A', '0', False), ('UNKNOWN', None, True), ('B', None, True), ('NOT_PAYABLE', '0', True)]:
            with self.subTest(kind=kind, share=share, usable=usable):
                self.assertEqual(source_fund_limit('1000', payment_class=kind, pre_self_pay_percent=share, mapping_usable=usable), 0)

    def test_unknown_line_cannot_be_balanced_by_non_cash_sources(self):
        with self.assertRaises(RuleError):
            checked_split('1000', patient_cash='300', personal_account='700', fund_amount='0', fund_limit='0', mapping_usable=False)

    def test_source_split_must_equal_the_original_amount(self):
        with self.assertRaises(RuleError):
            checked_split('1000', patient_cash='300', personal_account='200', fund_amount='400', fund_limit='1000', mapping_usable=True)

    def test_fund_allocation_cannot_cross_the_line_limit(self):
        with self.assertRaises(RuleError):
            checked_split('1000', patient_cash='300', personal_account='0', fund_amount='700', fund_limit='699.99', mapping_usable=True)

    def test_explicit_three_source_result_is_not_cash_received(self):
        value = patient_balance('1000', '0', personal_account='200', fund_amount='500')
        self.assertEqual(value['patient_responsibility'], 300)
        self.assertEqual(value['remaining'], 300)
        self.assertEqual(value['net_received'], 0)
        self.assertEqual(value['billed'], 1000)

    def test_paid_bill_turning_to_insurance_shows_refund_without_posting_it(self):
        value = patient_balance('1000', '1000', personal_account='200', fund_amount='500')
        self.assertEqual(value['remaining'], 0)
        self.assertEqual(value['refund_due'], 700)
        self.assertEqual(value['net_received'], 1000)

    def test_refund_and_credit_withdrawal_leave_distinct_cash_and_liability(self):
        after_refund = patient_balance('1000', '300', personal_account='200', fund_amount='500')
        after_withdrawal = patient_balance('1000', '300')
        self.assertEqual(after_refund['remaining'], 0)
        self.assertEqual(after_refund['refund_due'], 0)
        self.assertEqual(after_withdrawal['remaining'], 700)
        self.assertEqual(after_withdrawal['net_received'], 300)

    def test_excess_non_cash_credit_and_subcent_inputs_are_rejected(self):
        with self.assertRaises(RuleError):patient_balance('1000', '0', personal_account='501', fund_amount='500')
        with self.assertRaises(RuleError):patient_balance('1000', '0.001')

    def test_zero_fee_line_cannot_create_fund_payment(self):
        split = checked_split('0', patient_cash='0', personal_account='0', fund_amount='0', fund_limit='0', mapping_usable=False)
        self.assertEqual(sum(split[k] for k in ('patient_cash', 'personal_account', 'fund_amount')), 0)
