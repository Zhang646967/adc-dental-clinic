"""Distinguish visible facts, closed disclosures, and absent data in rendered HTML."""
from decimal import Decimal

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.test.html import Element, parse_html


def visible_words(node):
    if isinstance(node, str):
        return node
    children = node.children
    if node.name == "details" and "open" not in dict(node.attributes):
        children = [child for child in children if isinstance(child, Element) and child.name == "summary"]
    return " ".join(visible_words(child) for child in children)


class RoleGuiTests(SimpleTestCase):
    def test_payment_state_and_review_stay_visible_while_posted_history_can_be_opened(self):
        for remaining, refund, expected in [("70.00", "0", "尚需支付"), ("0", "15.00", "应退余额"), ("0", "0", "已结清")]:
            with self.subTest(expected=expected):
                bill = dict(invoice_id=1, invoice_no="SYNTHETIC-INVOICE", revision=2, total=Decimal("100"),
                            receipts=Decimal("30"), refunds=Decimal("0"), remaining=Decimal(remaining),
                            refund_due=Decimal(refund), review_pending=True)
                page = render_to_string("care/visit_checkout.html", {
                    "checkout": {"settlement_state": "PUBLISHED", "settlement": bill},
                    "visit": {"pk": 9, "status": "COMPLETED"},
                })
                visible = visible_words(parse_html(page))
                for text in [expected, "本次账单金额", "待复核", "查看本次结算单", "下次安排", "收款和退款明细"]:
                    self.assertIn(text, visible)
                for text in ["SYNTHETIC-INVOICE", "已记账收款", "已记账退款"]:
                    self.assertNotIn(text, visible)
                    self.assertIn(text, page)

    def test_missing_bill_has_no_balance_or_disclosure(self):
        page = render_to_string("care/visit_checkout.html", {
            "checkout": {"settlement_state": "AWAITING_PUBLICATION"},
            "visit": {"pk": 9, "status": "CHECKED_IN"},
        })
        self.assertIn("结算单待发布", visible_words(parse_html(page)))
        for text in ["已结清", "收款和退款明细", "¥"]:
            self.assertNotIn(text, page)

    def test_doctor_can_see_active_safety_work_without_opening_instructions(self):
        page = render_to_string("care/progress.html", {"editable": True, "treated_blockers": ["合成待核事项"]})
        visible = visible_words(parse_html(page))
        for text in ["过敏复核", "待复核", "合成待核事项", "接诊与交接职责"]:
            self.assertIn(text, visible)
        self.assertNotIn("结算交接", visible)
        self.assertIn("结算交接", page)
