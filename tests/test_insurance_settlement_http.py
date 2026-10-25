"""Actual Django routes, workspace/CSRF boundary and retained result pages."""
from django.test import TransactionTestCase, override_settings, Client
from django.urls import reverse
from django.db import DatabaseError
from unittest.mock import patch
from clinical.models import SensitiveReadEvent
from insurance.settlement_models import SettlementRequest, SettlementReview
from tests.test_insurance_settlement import SettlementFixture
from workspaces.context import SESSION_KEY, token_for
from workspaces.models import WorkspaceContext


@override_settings(ADC_CLINICAL_SYNTHETIC=True,ADC_READ_ONLY=False)
class InsuranceSettlementHTTPTests(SettlementFixture,TransactionTestCase):
    def setUp(self): self.setup_settlement()

    def allocations(self):
        pk=self.invoice.current_record_version.treatment_lines.get().pk
        return dict(action='preview',simulation_mode='ACCEPT',reason='合成分担核对依据',
            **{f'patient_cash_{pk}':'300',f'personal_account_{pk}':'200',f'fund_amount_{pk}':'500'})

    def token(self,response):
        return response.context['form'].initial['proposal_token']

    def test_complete_front_submission_and_independent_finance_review(self):
        self.client.force_login(self.front)
        url=reverse('insurance_settlement_new',args=[self.invoice.pk])
        self.assertContains(self.client.get(url),'核对逐项费用分担')
        preview=self.client.post(url,self.allocations()); self.assertContains(preview,'确认医保模拟分担')
        self.assertFalse(SettlementRequest.objects.exists())
        response=self.client.post(url,dict(action='confirm',proposal_token=self.token(preview),confirmed='on',fund_amount='99999'))
        row=SettlementRequest.objects.get(); self.assertEqual(row.fund_amount,500)
        self.assertRedirects(response,reverse('insurance_settlement_detail',args=[row.pk]))
        detail=self.client.get(response.url); self.assertContains(detail,'结果已取得，待独立核对')
        self.assertContains(detail,'待缴现金'); self.assertNotContains(detail,self.p1.name)
        self.client.force_login(self.fin); review=reverse('insurance_settlement_review',args=[row.pk])
        self.assertContains(self.client.get(review),'独立复核模拟分担')
        p=self.client.post(review,dict(action='preview',decision='APPROVE',reason='逐项独立核对'))
        self.assertEqual(p.status_code,200)
        response=self.client.post(review,dict(action='confirm',proposal_token=self.token(p),confirmed='on'))
        self.assertEqual(response.status_code,302); self.assertEqual(SettlementReview.objects.count(),1)
        self.assertContains(self.client.get(response.url),'分担已独立核对')

    def test_unknown_query_requires_confirmation_and_preserves_original_identifier(self):
        row=self.settlement(simulation_mode='LOST_SUCCESS'); self.client.force_login(self.front)
        url=reverse('insurance_settlement_query',args=[row.pk]); preview=self.client.get(url)
        row.refresh_from_db(); self.assertEqual(row.state,'UNKNOWN')
        self.assertContains(preview,str(row.request_id))
        response=self.client.post(url,dict(action='confirm',proposal_token=self.token(preview),confirmed='on'))
        self.assertEqual(response.status_code,302); row.refresh_from_db(); self.assertEqual(row.state,'AWAITING_REVIEW')
        self.assertEqual(SettlementRequest.objects.count(),1)

    def test_exact_seven_roles_and_other_clinic_boundary(self):
        row=self.settlement()
        for actor,code in [(self.front,200),(self.fin,200),(self.manager,403),(self.hq,403),(self.doctor,403),(self.pa,403),(self.tech,403),(self.front2,404)]:
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                if actor==self.front2:
                    self.assertEqual(self.client.post(reverse('activate_clinic'),dict(clinic=self.b.pk)).status_code,302)
                response=self.client.get(reverse('insurance_settlement_detail',args=[row.pk]))
                self.assertEqual(response.status_code,code)
                if code!=200: self.assertNotContains(response,str(row.request_id),status_code=code)

    def test_invalid_or_other_clinic_list_filter_rejected(self):
        self.settlement(); self.client.force_login(self.front2)
        self.assertEqual(self.client.post(reverse('activate_clinic'),dict(clinic=self.b.pk)).status_code,302)
        url=reverse('insurance_settlements')
        self.assertEqual(self.client.get(url,dict(invoice=self.invoice.pk)).status_code,404)
        for value in ('bad','-1','9999999999999999999999999','１２'):
            self.assertEqual(self.client.get(url,dict(invoice=value)).status_code,404)
        self.assertEqual(self.client.get(url,dict(state='invalid')).status_code,400)

    def test_read_pages_do_not_create_financial_effects(self):
        self.client.force_login(self.front)
        for name,args in [('insurance_home',[]),('insurance_settlements',[]),('insurance_settlement_new',[self.invoice.pk])]:
            self.assertEqual(self.client.get(reverse(name,args=args)).status_code,200)
        self.assertFalse(SettlementRequest.objects.exists())
        self.assertTrue(SensitiveReadEvent.objects.filter(object_kind='INVOICE',purpose='BILLING').exists())

    def test_patient_has_no_mini_or_website_insurance_write_route(self):
        self.client.force_login(self.pa)
        url=reverse('insurance_settlement_new',args=[self.invoice.pk])
        self.assertEqual(self.client.post(url,self.allocations()).status_code,403)
        self.assertFalse(SettlementRequest.objects.exists())

    def test_missing_mapping_and_stale_confirmation_show_business_guidance(self):
        self.client.force_login(self.front); url=reverse('insurance_settlement_new',args=[self.invoice.pk])
        preview=self.client.post(url,self.allocations()); self.disable_source(self.mapping,'mapping')
        response=self.client.post(url,dict(action='confirm',proposal_token=self.token(preview),confirmed='on'))
        self.assertEqual(response.status_code,409); self.assertContains(response,'重新预览',status_code=409)
        form=self.client.get(url); self.assertContains(form,'本行保留自付')

    def test_database_outcome_uncertainty_guides_to_original_query(self):
        self.client.force_login(self.front); url=reverse('insurance_settlement_new',args=[self.invoice.pk])
        preview=self.client.post(url,self.allocations())
        with patch('insurance.settlement_services.confirm_settlement',side_effect=DatabaseError('private-db-internal')):
            response=self.client.post(url,dict(action='confirm',proposal_token=self.token(preview),confirmed='on'))
        self.assertContains(response,'查询原请求',status_code=503); self.assertNotContains(response,'private-db-internal',status_code=503)

    def test_csrf_and_workspace_signature_required(self):
        client=Client(enforce_csrf_checks=True); client.force_login(self.front)
        ctx=WorkspaceContext.objects.create(user=self.front,role='FRONT_DESK',clinic=self.a,login_channel='STAFF')
        session=client.session; session[SESSION_KEY]=str(ctx.pk); session.save()
        url=reverse('insurance_settlement_new',args=[self.invoice.pk]); client.get(url)
        self.assertEqual(client.post(url,dict(self.allocations(),workspace_token=token_for(ctx))).status_code,403)
        csrf=client.cookies['csrftoken'].value
        self.assertEqual(client.post(url,dict(self.allocations(),csrfmiddlewaretoken=csrf)).status_code,409)
        response=client.post(url,dict(self.allocations(),csrfmiddlewaretoken=csrf,workspace_token=token_for(ctx)))
        self.assertEqual(response.status_code,200)
        self.assertFalse(SettlementRequest.objects.exists())

    def test_invoice_and_receivables_show_separate_non_cash_amounts(self):
        self.review_settlement(self.settlement()); self.client.force_login(self.front)
        response=self.client.get(reverse('invoice_detail',args=[self.invoice.pk]))
        self.assertContains(response,'基金承担（应收）'); self.assertContains(response,'患者现金责任')
        response=self.client.get(reverse('cash_receivables')); self.assertEqual(response.status_code,200)
