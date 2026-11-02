"""Posted financial facts and patient-only projections against PostgreSQL."""
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from django.db import connection
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount
from care.models import Invoice
from finance.cash_models import CashEntry
from finance.patient_cash import invoice_activity
from portal.models import PatientAccess
from tests.test_care_finance_equipment import CFEFixture
from tests.workspace_client import WorkspaceClient


class PatientCashActivityTests(CFEFixture, TransactionTestCase):
    def setUp(self):
        self.setup_cfe()
        self.visit, self.invoice = self.billed()
        self.owner = PatientAccess.objects.get(patient=self.visit.patient).user
        self.client = WorkspaceClient()
        self.client.force_login(self.owner)
        self.url = reverse('mini_invoice', args=[self.invoice.pk])

    def data(self, **query):
        response = self.client.get(self.url, query)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['data']

    def posted_fixture(self, count):
        # Keep database history guards active: request, then independent posting.
        for _ in range(count):
            self.approve(self.cash(self.invoice, amount=D('1.00'), reason='PRIVATE_STAFF_NOTE'))

    def test_empty_history_is_explicit_zero_not_missing(self):
        activity = self.data()['cash_activity']
        self.assertEqual((activity['receipts'], activity['refunds'], activity['entries'], activity['count']),
                         ('0.00', '0.00', [], 0))
        self.assertContains(self.client.get(reverse('portal_invoice', args=[self.invoice.pk])), '暂无已记账收退款')

    def test_totals_and_entries_exclude_pending_and_rejected_requests(self):
        receipt = self.cash(self.invoice, amount=D('50.00'))
        self.approve(receipt)
        refund = self.cash(self.invoice, kind='REFUND', amount=D('10.00'))
        self.approve(refund)
        self.cash(self.invoice, amount=D('5.00'))
        rejected = self.cash(self.invoice, amount=D('7.00'))
        self.approve(rejected, decision='reject')
        data = self.data()
        self.assertEqual((data['cash_activity']['receipts'], data['cash_activity']['refunds'],
                          data['cash_balance']['net_received'], data['cash_balance']['pending']),
                         ('50.00', '10.00', '40.00', 1))
        self.assertEqual([r['id'] for r in data['cash_activity']['entries']], [refund.pk, receipt.pk])

    def test_projection_does_not_disclose_staff_or_channel_evidence(self):
        self.posted_fixture(1)
        row = self.data()['cash_activity']['entries'][0]
        self.assertEqual(set(row), {'id','kind','label','amount','currency','occurred_on','posted_at','state','status'})
        self.assertEqual((row['state'], row['status'], row['currency']), ('POSTED', '已记账', 'CNY'))
        self.assertNotContains(self.client.get(reverse('portal_invoice', args=[self.invoice.pk])), 'PRIVATE_STAFF_NOTE')
        self.assertNotIn('PRIVATE_STAFF_NOTE', self.client.get(self.url).content.decode())

    def test_non_cash_responsibility_remains_visible_and_is_not_counted_as_receipts(self):
        self.posted_fixture(1)
        # Controlled insurance projection; no provider call or insurance settlement acceptance.
        with patch('insurance.settlement_projection.invoice_insurance_facts',return_value=dict(
                personal_account=D('10.00'),fund_amount=D('60.00'),unresolved=1)):
            data=self.data()
            web=self.client.get(reverse('portal_invoice',args=[self.invoice.pk]))
        self.assertEqual(data['cash_activity']['receipts'],'1.00')
        self.assertEqual(data['cash_balance']['insurance_fund'],'60.00')
        self.assertEqual(D(data['cash_balance']['patient_responsibility']),self.invoice.current_record_version.total_amount-D('70.00'))
        self.assertContains(web,'已核对个人账户承担');self.assertContains(web,'基金承担（应收）')
        self.assertContains(web,'有医保原请求待处理');self.assertContains(web,'非现金承担不代表资金到账')

    def test_pagination_is_bounded_and_totals_cover_all_pages(self):
        self.posted_fixture(23)
        first = self.data()['cash_activity']
        second = self.data(cash_page=2)['cash_activity']
        self.assertEqual((len(first['entries']), len(second['entries']), first['count'], first['next'], second['previous']), (20,3,23,2,1))
        self.assertEqual((first['receipts'], second['receipts']), ('23.00', '23.00'))
        self.assertFalse({r['id'] for r in first['entries']} & {r['id'] for r in second['entries']})

    def test_number_of_queries_does_not_grow_per_cash_entry(self):
        self.posted_fixture(1)
        with CaptureQueriesContext(connection) as small:
            invoice_activity(self.invoice)
        self.posted_fixture(40)
        with CaptureQueriesContext(connection) as larger:
            data = invoice_activity(self.invoice, page=2)
        self.assertEqual(len(data['entries']),20)
        self.assertEqual(len(small),len(larger))
        self.assertLessEqual(len(larger),3)

    def test_website_and_native_show_identical_totals_and_dates(self):
        entry = self.cash(self.invoice, amount=D('20.00'), occurred_on=self.today)
        self.approve(entry)
        data=self.data();web=self.client.get(reverse('portal_invoice',args=[self.invoice.pk]))
        self.assertEqual(data['cash_activity']['receipts'],str(web.context['cash_activity']['receipts']))
        self.assertEqual(data['cash_activity']['entries'][0]['occurred_on'], self.today.isoformat())
        self.assertContains(web,'已记账收款合计');self.assertContains(web,'已记账退款合计')
        self.assertContains(web,'业务日期');self.assertContains(web,'记账时间')
        self.assertNotContains(web,'申请模拟收款或退款')

    def test_historical_bill_keeps_current_cash_history_and_labels_it(self):
        from care.corrections import request_line_correction, review_correction
        self.posted_fixture(1)
        self.visit.refresh_from_db()
        case=request_line_correction(actor=self.doctor,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
            line_id=self.invoice.current_record_version.treatment_lines.first().pk,quantity=D('1'),unit_price=D('99.99'),reason='合成金额更正')
        review_correction(actor=self.fin,request_id=case.pk,decision='approve',reason='合成独立核对')
        old=self.data(revision=1);current=self.data()
        self.assertEqual(old['cash_activity'],current['cash_activity'])
        self.assertFalse(old['is_current']);self.assertEqual(old['cash_balance']['current_revision'],2)
        self.assertContains(self.client.get(reverse('portal_invoice',args=[self.invoice.pk]),{'revision':1}), '不是历史时点余额')

    def test_revocation_between_pages_removes_cash_projection(self):
        self.posted_fixture(23)
        self.data()
        PatientAccess.objects.filter(user=self.owner).update(is_active=False)
        response=self.client.get(self.url,{'cash_page':2})
        self.assertEqual(response.status_code,409)
        self.assertNotIn('cash_activity',response.content.decode())

    def test_other_patient_cannot_obtain_paginated_cash_history(self):
        self.posted_fixture(23)
        other=UserAccount.objects.exclude(pk=self.owner.pk).filter(patient_access__is_active=True).first()
        client=WorkspaceClient();client.force_login(other)
        for route in [self.url,reverse('portal_invoice',args=[self.invoice.pk])]:
            response=client.get(route,{'cash_page':2})
            self.assertEqual(response.status_code,404)
            self.assertNotIn('cash_activity',response.content.decode())

    def test_repeated_reads_and_bad_page_values_never_change_money(self):
        self.posted_fixture(1)
        before=list(CashEntry.objects.values())
        for page in ['1','2','0','-1','not-a-page','9999999999999999999999999999999']:
            data=self.data(cash_page=page)
            self.assertLessEqual(len(data['cash_activity']['entries']),20)
        self.assertEqual(before,list(CashEntry.objects.values()))
        self.assertEqual(Invoice.objects.count(),1)
