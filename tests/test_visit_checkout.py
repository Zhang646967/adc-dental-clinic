"""Real PostgreSQL departure projections at the authorized front desk and patient entries."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from unittest.mock import patch

from django.db import connections
from django.test import TransactionTestCase
from django.urls import reverse

from care.checkout import settlement_summary
from care.corrections import request_line_correction, review_correction
from care.models import Invoice
from finance.cash_models import CashEntry
from scheduling.models import Visit
from tests.test_patient_visit_review import VisitReviewFixture


class CheckoutTests(VisitReviewFixture, TransactionTestCase):
    def setUp(self):
        self.setup_visit_review()
        self.book_and_arrive()

    def test_current_bill_and_linked_return_are_scoped_and_read_only(self):
        _, active = self.review_responses()
        self.assertIsNone(active['review']['settlement'])
        self.assertEqual(active['review']['settlement_state'], 'AWAITING_PUBLICATION')
        invoice, instruction = self.complete_case()
        self.record_cash(invoice, amount='100')
        successor = self.book_followup(instruction)
        counts = [m.objects.count() for m in (Visit, Invoice, CashEntry)]
        owner, native = self.review_responses()
        front = self.front_web.get(reverse('visit_detail', args=[self.v.pk]))
        self.assertContains(front, '离店核对')
        self.assertEqual(front.context['checkout']['settlement'], owner.context['review']['settlement'])
        cash = native['review']['settlement']
        self.assertEqual((cash['receipts'], cash['refunds'], cash['remaining']), ('100.00', '0.00', '0.00'))
        self.assertContains(front, '已结清')
        self.assertNotContains(front, 'PRIVATE_NEXT_PURPOSE')
        self.assertEqual(native['review']['followups'][0]['active_appointment']['id'], successor.pk)
        self.assertIsNone(native['review']['followups'][0]['historical_appointment'])
        for client, route in ((self.front_web, 'visit_detail'), (self.web, 'portal_visit')):
            checker = client.get(reverse(route, args=[successor.pk]), {'checkout_from': self.v.pk})
            self.assertContains(checker, reverse(route, args=[self.v.pk]) + '#checkout-money-heading')
            invalid = client.get(reverse(route, args=[successor.pk]), {'checkout_from': successor.pk})
            self.assertNotContains(invalid, '#checkout-money-heading">← 返回原就诊')
        self.assertEqual([m.objects.count() for m in (Visit, Invoice, CashEntry)], counts)

    def test_patient_bill_return_and_cash_paging_preserve_the_entry(self):
        invoice, _ = self.complete_case()
        url = reverse('portal_invoice', args=[invoice.pk])
        billing = reverse('portal_billing')
        page = self.web.get(billing)
        self.assertContains(page, f'id="bill-{invoice.pk}-open" href="{url}?billing_page=1"')
        detail = self.web.get(url, {'billing_page': 1, 'cash_page': 1, 'revision': 1})
        self.assertContains(detail, f'href="{billing}?page=1#bill-{invoice.pk}-open"')
        self.assertContains(detail, 'id="cash-activity" open')
        self.assertContains(detail, '¥100.00')
        for params in ({}, {'billing_page': 'bad'}):
            direct = self.web.get(url, params)
            self.assertContains(direct, reverse('portal_visit', args=[self.v.pk]) + '#checkout-money-heading')
            self.assertNotContains(direct, 'id="cash-activity" open')

    def test_concurrent_correction_yields_one_bill_version_and_its_actual_balance(self):
        invoice, _ = self.complete_case()
        self.record_cash(invoice, amount='100')
        self.v.refresh_from_db()
        change = request_line_correction(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version,
            line_id=invoice.current_record_version.treatment_lines.get().pk, quantity=Decimal('1'),
            unit_price=Decimal('80.00'), reason='独立合成单价更正')
        read_version, committed = Event(), Event()

        def complete_correction():
            try:
                if not read_version.wait(15):
                    raise AssertionError('checkout did not load the original bill')
                review_correction(actor=self.finance, request_id=change.pk, decision='approve', reason='独立复核')
            finally:
                committed.set()
                connections.close_all()

        def pause_after_loading_invoice(bill):
            read_version.set()
            self.assertTrue(committed.wait(15))
            return settlement_summary(bill)

        with ThreadPoolExecutor(1) as workers:
            future = workers.submit(complete_correction)
            with patch('care.checkout.settlement_summary', side_effect=pause_after_loading_invoice):
                old = self.mini.get(reverse('mini_visit', args=[self.v.pk])).json()['data']['review']['settlement']
            future.result()
        self.assertEqual((old['revision'], old['total'], old['receipts'], old['refund_due']), (1, '100.00', '100.00', '0.00'))
        current = self.review_responses()[1]['review']['settlement']
        self.assertEqual((current['revision'], current['total'], current['refund_due']), (2, '80.00', '20.00'))
        for client, route in ((self.front_web, 'invoice_detail'), (self.web, 'portal_invoice')):
            history = client.get(reverse(route, args=[invoice.pk]), {'revision': 1})
            self.assertEqual(history.context['total'], Decimal('100.00'))
            self.assertEqual(history.context['cash_balance']['current_revision'], 2)
            self.assertEqual(history.context['cash_balance']['refund_due'], Decimal('20.00'))
