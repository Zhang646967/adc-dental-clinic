"""Native query/form contracts; browser behavior is verified separately."""
from urllib.parse import parse_qs, urlsplit
from django.test import SimpleTestCase, TransactionTestCase
from django.urls import reverse
from care.models import Invoice, AuditEvent, VisitRecordVersion
from finance.cash_models import CashEntry
from scheduling.worklists import visit_filter_navigation
from tests.test_care_finance_equipment import CFEFixture
from tests.workspace_client import WorkspaceClient


class QueueNavigationTests(SimpleTestCase):
    def test_query_navigation_keeps_search_and_removes_only_explicit_conditions(self):
        data = dict(queue='outcome', day='2026-10-18', status='SCHEDULED', q='A & 患者+?', clinic='999')
        shortcuts, chips = visit_filter_navigation(data)
        today = next(v for v in shortcuts if v['label'] == '今日全部安排')
        self.assertEqual(parse_qs(urlsplit(today['url']).query), {'queue': ['today'], 'q': [data['q']]})
        remove_date = next(v for v in chips if v['label'] == '日期')
        self.assertEqual(parse_qs(urlsplit(remove_date['url']).query),
                         {'queue': ['outcome'], 'status': ['SCHEDULED'], 'q': [data['q']]})
        self.assertEqual(data['day'], '2026-10-18')
        self.assertFalse(any('clinic=' in v['url'] for v in shortcuts + chips))


class NativeFormFailureTests(CFEFixture, TransactionTestCase):
    def setUp(self):
        self.setup_cfe()
        self.client = WorkspaceClient()

    def test_invalid_note_retains_text_and_versions_without_creating_business_facts(self):
        visit = self.arrived()
        self.client.force_login(self.doctor)
        before = AuditEvent.objects.count()
        response = self.client.post(reverse('care_workspace', args=[visit.pk]),
            dict(action='note', expected_version=visit.lock_version, clinical_note='保留的合成草稿 & 核对'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-error-summary')
        self.assertContains(response, 'href="#id_note_confirmed"')
        self.assertEqual(response.context['note_form']['clinical_note'].value(), '保留的合成草稿 & 核对')
        visit.refresh_from_db()
        self.assertEqual(visit.lock_version, 1)
        self.assertFalse(VisitRecordVersion.objects.exists())
        self.assertFalse(Invoice.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before)

    def test_invalid_cash_amount_retains_evidence_and_date_without_creating_entry(self):
        _, invoice = self.billed()
        evidence = self.evidence(self.a.pk)
        self.client.force_login(self.front)
        response = self.client.post(reverse('cash_invoice_request', args=[invoice.pk]),
            dict(action='preview', kind='RECEIPT', amount='0', occurred_on=self.today.isoformat(),
                 reason='保留的合成申请依据', **evidence))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="#id_amount"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertEqual(response.context['form']['reference'].value(), evidence['reference'])
        self.assertEqual(response.context['form']['occurred_on'].value(), self.today.isoformat())
        self.assertFalse(CashEntry.objects.exists())
