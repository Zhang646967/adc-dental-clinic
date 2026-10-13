"""Actually runnable with Python alone. Does NOT emulate Django or PostgreSQL."""
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from adc_core.rules import (
    RuleError, overlaps, validate_slot, validate_state, validate_transition,
    validate_allergies, validate_birth, line_amount, total_amount, quarter_bounds,
    validate_role_scope, validate_interval, STATUS_LABELS, ATTENDED_STATUSES, CLOSED_STATUSES,
)

T = datetime(2026, 9, 22, 9, tzinfo=timezone.utc)
H = timedelta(hours=1)

class IntervalTests(unittest.TestCase):
    def test_same_start_overlaps(self):
        self.assertTrue(overlaps(T, T+H, T, T+H))
    def test_different_start_overlaps(self):
        self.assertTrue(overlaps(T, T+H, T+H/2, T+2*H))
    def test_containment_overlaps(self):
        self.assertTrue(overlaps(T, T+2*H, T+H/2, T+H))
    def test_adjacent_does_not_overlap(self):
        self.assertFalse(overlaps(T, T+H, T+H, T+2*H))
    def test_disjoint_does_not_overlap(self):
        self.assertFalse(overlaps(T, T+H, T+2*H, T+3*H))
    def test_reversed_interval_rejected(self):
        with self.assertRaises(RuleError): validate_interval(T+H, T)
    def test_zero_interval_rejected(self):
        with self.assertRaises(RuleError): validate_interval(T, T)
    def test_naive_time_rejected(self):
        with self.assertRaises(RuleError): validate_interval(T.replace(tzinfo=None), T+H)
    def test_offset_equivalence(self):
        local = T.astimezone(timezone(timedelta(hours=8)))
        self.assertTrue(overlaps(T, T+H, local, local+H))
    def test_slot_containment(self):
        validate_slot(T, T+H, T-H, T+2*H, T-H)
    def test_outside_slot_rejected(self):
        with self.assertRaises(RuleError): validate_slot(T, T+2*H, T-H, T+H, T-H)
    def test_past_booking_rejected(self):
        with self.assertRaises(RuleError): validate_slot(T, T+H, T-H, T+2*H, T+H)

class StateTests(unittest.TestCase):
    def test_all_seven_consistent_states(self):
        for s in STATUS_LABELS:
            with self.subTest(status=s):
                at=T if s in ATTENDED_STATUSES else None
                closed=T+H if s in CLOSED_STATUSES else None
                validate_state(s, s in ATTENDED_STATUSES, at, closed)
    def test_false_attendance_in_checked_in_rejected(self):
        with self.assertRaises(RuleError): validate_state("CHECKED_IN", False, T, None)
    def test_unknown_state_rejected(self):
        with self.assertRaises(RuleError): validate_state("PAID", False, None, None)
    def test_completion_without_time_rejected(self):
        with self.assertRaises(RuleError): validate_state("COMPLETED", True, T, None)
    def test_completion_before_arrival_rejected(self):
        with self.assertRaises(RuleError): validate_state("COMPLETED", True, T, T-H)
    def test_no_treatment_is_attended(self):
        validate_state("CLOSED_NO_TREATMENT", True, T, T+H)
    def test_cancelled_is_not_attended(self):
        with self.assertRaises(RuleError): validate_state("CANCELLED", True, T, None)
    def test_ordinary_transitions(self):
        for target in ("CHECKED_IN", "CANCELLED", "NO_SHOW", "RESCHEDULED"):
            validate_transition("SCHEDULED", target)
        for target in ("COMPLETED", "CLOSED_NO_TREATMENT"):
            validate_transition("CHECKED_IN", target)
    def test_terminal_cannot_silently_reopen(self):
        for old in ("COMPLETED", "CANCELLED", "NO_SHOW", "RESCHEDULED", "CLOSED_NO_TREATMENT"):
            with self.subTest(old=old), self.assertRaises(RuleError): validate_transition(old, "SCHEDULED")
    def test_cannot_skip_arrival(self):
        with self.assertRaises(RuleError): validate_transition("SCHEDULED", "COMPLETED")

class DataRulesTests(unittest.TestCase):
    def test_allergy_unknown_preserved(self):
        self.assertEqual(validate_allergies("UNKNOWN", []), ())
    def test_known_allergy_requires_item(self):
        with self.assertRaises(RuleError): validate_allergies("KNOWN", [])
    def test_no_known_allergy_rejects_item(self):
        with self.assertRaises(RuleError): validate_allergies("NO_KNOWN", [1])
    def test_allergy_items_deduplicated(self):
        self.assertEqual(validate_allergies("KNOWN", [2, 1, 2]), (1, 2))
    def test_future_birth_rejected(self):
        with self.assertRaises(RuleError): validate_birth(date(2027,1,1), date(2026,1,1))
    def test_same_day_birth_allowed(self):
        validate_birth(date(2026,1,1), date(2026,1,1))
    def test_role_scope_valid(self):
        validate_role_scope("FRONT_DESK", "CLINIC", 1, None)
        validate_role_scope("DENTIST", "SELF_DENTIST", None, 3)
    def test_role_scope_cartesian_product_rejected(self):
        with self.assertRaises(RuleError): validate_role_scope("MANAGER", "CHAIN", None, None)
    def test_dentist_role_without_profile_rejected(self):
        with self.assertRaises(RuleError): validate_role_scope("DENTIST", "SELF_DENTIST", None, None)
    def test_technical_role_is_not_clinic_role(self):
        with self.assertRaises(RuleError): validate_role_scope("SYSADMIN", "CLINIC", 1, None)

class MoneyAndQuarterTests(unittest.TestCase):
    def test_baseline_rounding_example(self):
        self.assertEqual(line_amount("1.125", "99.99"), Decimal("112.49"))
    def test_half_up_not_bankers_rounding(self):
        self.assertEqual(line_amount("1.005", "1.00"), Decimal("1.01"))
    def test_total_is_sum_of_rounded_lines(self):
        self.assertEqual(total_amount([line_amount("1.125", "99.99"), line_amount("1", "200")]), Decimal("312.49"))
    def test_negative_values_rejected(self):
        for q,p in (("-1","1"),("1","-1")):
            with self.subTest(q=q,p=p), self.assertRaises(RuleError): line_amount(q,p)
    def test_zero_quantity_rejected(self):
        with self.assertRaises(RuleError): line_amount("0", "200")
    def test_zero_price_requires_reason(self):
        with self.assertRaises(RuleError): line_amount("1", "0")
        self.assertEqual(line_amount("1", "0", "演示授权原因"), Decimal("0.00"))
    def test_non_finite_rejected(self):
        for v in ("NaN", "Infinity", "-Infinity", "bad"):
            with self.subTest(v=v), self.assertRaises(RuleError): line_amount(v, "1")
    def test_float_rejected(self):
        with self.assertRaises(RuleError): line_amount(1.2, "20")
    def test_excess_precision_rejected(self):
        with self.assertRaises(RuleError): line_amount("1.0001", "20")
        with self.assertRaises(RuleError): line_amount("1", "20.001")
    def test_line_storage_overflow_rejected(self):
        with self.assertRaises(RuleError): line_amount("999999999", "9999999999")
    def test_empty_total_is_zero(self):
        self.assertEqual(total_amount([]), Decimal("0.00"))
    def test_quarter_four_crosses_year(self):
        start,end=quarter_bounds(2026,4)
        self.assertEqual((start.year,start.month,end.year,end.month),(2026,10,2027,1))
    def test_quarter_uses_shanghai_boundary(self):
        start,_=quarter_bounds(2026,1)
        self.assertEqual(start.astimezone(timezone.utc), datetime(2025,12,31,16,tzinfo=timezone.utc))
    def test_invalid_quarter_rejected(self):
        with self.assertRaises(RuleError): quarter_bounds(2026,5)
