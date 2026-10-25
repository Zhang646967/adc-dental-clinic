"""Staff forms use real workspace checks and retained proposals."""
from datetime import timedelta
from decimal import Decimal as D
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from finance.allocation_models import FundAllocation, FundIssue
from finance.allocation_projection import claim_funds
from insurance.cancellation_models import CancellationRequest
from tests.test_insurance_fund_closure import FundClosureFixture


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_READ_ONLY=False)
class InsuranceFundHTTPTests(FundClosureFixture, TransactionTestCase):
    def setUp(self): self.setup_closure()

    def confirm_response(self, path, preview, **extra):
        self.assertEqual(preview.status_code, 200)
        self.assertIn('proposal_token', preview.context['form'].initial)
        response = self.client.post(path, dict(action='confirm', confirmed='on',
            proposal_token=preview.context['form'].initial['proposal_token'], **extra))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(response.url).status_code, 200)
        return response

    def test_full_bank_allocation_form_and_independent_review(self):
        transfer = self.bank_transfer(); self.client.force_login(self.fin)
        path = reverse('fund_allocation_new', args=[transfer.pk])
        self.assertContains(self.client.get(path), '逐笔分配')
        p = self.client.post(path, dict(action='preview', basis='合成分配核对', **{'claim_'+str(self.claim.pk): '300'}))
        self.assertFalse(FundAllocation.objects.exists())
        self.confirm_response(path, p, **{'claim_'+str(self.claim.pk): '500'})
        row = FundAllocation.objects.get(); self.assertEqual(row.total, D('300'))
        self.client.force_login(self.second_fin); path = reverse('fund_allocation_review', args=[row.pk])
        self.confirm_response(path, self.client.post(path, dict(action='preview', decision='approve', reason='独立核对分配')))
        self.assertEqual(claim_funds(self.claim.pk)['net_received'], D('300'))

    def test_empty_or_invalid_selection_returns_useful_form_error(self):
        transfer = self.bank_transfer(); self.client.force_login(self.fin)
        path = reverse('fund_allocation_new', args=[transfer.pk])
        response = self.client.post(path, dict(action='preview', basis='无分配'))
        self.assertContains(response, '每批请选择')
        self.assertFalse(FundAllocation.objects.exists())
        self.assertContains(self.client.get(path+'?q=not-a-claim'), '查找申报')

    def test_issue_form_owner_deadline_and_closure(self):
        self.client.force_login(self.fin)
        path = reverse('fund_issue_new', args=[self.claim.pk])
        self.assertContains(self.client.get(path), '跟进责任人')
        due = timezone.localtime(timezone.now()+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        p = self.client.post(path, dict(action='preview', kind='UNKNOWN', amount='', owner_id=self.fin.pk,
            due_at=due, basis='等待核对本地银行用途'))
        self.confirm_response(path, p)
        row = FundIssue.objects.get(); self.assertIsNone(row.amount)
        self.assertContains(self.client.get(reverse('fund_issues')), self.fin.username)
        path = reverse('fund_issue_followup', args=[row.pk])
        p = self.client.post(path, dict(action='preview', state='CLOSED', owner_id=self.fin.pk, due_at='', basis='已记录核对结论，不改原金额'))
        self.confirm_response(path, p)
        self.assertContains(self.client.get(reverse('fund_issue_detail', args=[row.pk])), '跟进已结束')
        self.assertContains(self.client.get(reverse('fund_issues')+'?closed=1'), self.invoice.invoice_no)

    def test_followup_open_requires_explicit_deadline(self):
        row = self.new_issue(); self.client.force_login(self.fin)
        path = reverse('fund_issue_followup', args=[row.pk])
        p = self.client.post(path, dict(action='preview', state='OPEN', owner_id=self.fin.pk, due_at='', basis='继续联系'))
        self.assertContains(p, '请填写下次联系期限')
        self.assertEqual(row.events.count(), 1)

    def test_cancellation_unknown_query_and_finance_review_form(self):
        self.client.force_login(self.front)
        path = reverse('insurance_cancellation_new', args=[self.claim.pk])
        p = self.client.post(path, dict(action='preview', simulation_mode='LOST_SUCCESS', reason='合成撤销原分担'))
        self.confirm_response(path, p)
        self.assertEqual(CancellationRequest.objects.get().state, 'UNKNOWN')
        path = reverse('insurance_cancellation_query', args=[self.claim.pk])
        self.confirm_response(path, self.client.get(path))
        self.client.force_login(self.fin)
        path = reverse('insurance_cancellation_review', args=[self.claim.pk])
        self.confirm_response(path, self.client.post(path, dict(action='preview', decision='APPROVE', reason='独立核对原结果及零到账')))
        self.claim.refresh_from_db(); self.assertEqual(self.claim.state, 'CANCELLED')

    def test_front_desk_sees_progress_but_not_fund_management_and_seven_role_boundary(self):
        transfer = self.bank_transfer(); allocation = self.allocate(transfer); issue = self.new_issue()
        routes = [('fund_claims', []), ('fund_claim_detail', [self.claim.pk]), ('fund_allocation_new', [transfer.pk]),
            ('fund_allocation_detail', [allocation.pk]), ('fund_allocation_review', [allocation.pk]),
            ('fund_issues', []), ('fund_issue_new', [self.claim.pk]), ('fund_issue_detail', [issue.pk]), ('fund_issue_followup', [issue.pk])]
        for actor in (self.front, self.manager, self.hq, self.doctor, self.pa, self.tech):
            self.client.force_login(actor)
            for name, args in routes:
                with self.subTest(role=actor.username, route=name):
                    self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 403)
        self.client.force_login(self.front)
        r = self.client.get(reverse('insurance_settlement_detail', args=[self.claim.pk]))
        self.assertContains(r, '基金到账与退回')
        self.assertNotContains(r, '逐笔分配与差额跟进')

    def test_finance_pages_keep_patient_identity_out_of_projection_and_log(self):
        from clinical.models import SensitiveReadEvent
        row = self.new_issue(); transfer = self.bank_transfer(); allocation = self.allocate(transfer)
        self.client.force_login(self.fin)
        for name, args in [('fund_claims', []), ('fund_claim_detail', [self.claim.pk]), ('fund_issues', []),
            ('fund_issue_detail', [row.pk]), ('fund_transfer_detail', [transfer.pk]), ('fund_allocation_detail', [allocation.pk])]:
            r = self.client.get(reverse(name, args=args)); self.assertEqual(r.status_code, 200)
            self.assertNotContains(r, self.p1.name)
        audit = list(SensitiveReadEvent.objects.filter(actor=self.fin, object_kind__in=['FUND_CLAIM_LIST', 'FUND_ISSUE', 'FUND_ALLOCATION']).values())
        self.assertTrue(audit); self.assertNotIn(self.p1.name, str(audit))

    def test_rejected_settlement_cancellation_projection_never_creates_fund_receivable(self):
        self.start_cancel(); self.cancellation_review()
        claim = self.review_settlement(self.settlement(), decision='REJECT')
        self.start_cancel(claim)
        self.client.force_login(self.fin)
        response = self.client.get(reverse('fund_claim_detail', args=[claim.pk]))
        self.assertEqual(response.context['funds']['receivable'], 0)
        self.assertEqual(response.context['funds']['net_received'], 0)
