"""Preview-first staff HTTP flows; no patient-channel or clinical delegation."""
import hashlib
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from accounts.models import UserAccount, RoleAssignment
from clinical.models import SensitiveReadEvent
from insurance import services, selectors, catalogue_source
from insurance.models import PolicyCatalogue, ClinicArrangement, EligibilityFact, InsuranceEvent
from portal.models import PatientAccess
from tests.test_insurance_preparation import InsuranceFixtureMixin
from workspaces.models import WorkspaceContext
from workspaces.context import SESSION_KEY, token_for


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_READ_ONLY=False)
class InsurancePreparationHTTPTests(InsuranceFixtureMixin, TransactionTestCase):
    def preview(self, url, data):
        response = self.client.post(url, dict(action='preview', **data))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'errorlist')
        token = response.context['form'].initial['proposal_token']
        return token

    def confirm(self, url, token):
        return self.client.post(url, dict(action='confirm', proposal_token=token, confirmed=True))

    def test_finance_import_review_download_and_unknown_filter(self):
        self.client.force_login(self.f1)
        url = reverse('insurance_import'); token = self.preview(url, dict(source_key=catalogue_source.SOURCE_KEY))
        self.assertFalse(PolicyCatalogue.objects.exists())
        self.assertEqual(self.confirm(url, token).status_code, 302)
        row = PolicyCatalogue.objects.get()
        self.assertEqual(self.client.get(reverse('insurance_catalogue', args=[row.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse('insurance_import')).status_code, 200)
        self.client.force_login(self.f2)
        url = reverse('insurance_review', args=['catalogue', row.pk])
        token = self.preview(url, dict(decision='approve', reason='逐项核对官方原件和缺失内容'))
        self.assertEqual(self.confirm(url, token).status_code, 302)
        row.refresh_from_db(); self.assertEqual(row.state, 'CONFIRMED')
        response = self.client.get(reverse('insurance_source', args=[row.pk]))
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), catalogue_source.SOURCE_DIGEST)
        response = self.client.get(reverse('insurance_catalogue', args=[row.pk]), dict(issue='unknown'))
        self.assertContains(response, '013105010310000'); self.assertEqual(len(response.context['page']), 1)
        response = self.client.get(reverse('insurance_catalogue', args=[row.pk]), dict(issue='unit'))
        self.assertEqual(len(response.context['page']), 2)

    def test_manager_then_finance_arrangement_and_mapping_forms(self):
        cat = self.catalogue(); self.client.force_login(self.manager)
        url = reverse('insurance_arrangement_new')
        token = self.preview(url, dict(catalogue_id=cat.pk, starts_on=str(self.today), ends_on=str(self.end), reference='SIM-HTTP-ARRANGEMENT'))
        self.assertEqual(self.confirm(url, token).status_code, 302)
        row = ClinicArrangement.objects.get()
        self.assertEqual(self.client.get(reverse('insurance_detail', args=['arrangement', row.pk])).status_code, 200)
        self.client.force_login(self.f2)
        url = reverse('insurance_review', args=['arrangement', row.pk]); token = self.preview(url, dict(decision='approve', reason='课程安排核对'))
        self.assertEqual(self.confirm(url, token).status_code, 302)
        self.client.force_login(self.manager)
        response = self.client.get(reverse('insurance_mapping_new')); self.assertEqual(response.status_code, 200)
        self.assertContains(response, '每一原收费单位对应的目录单位数量')

    def test_rejected_catalogue_has_explicit_resubmission_with_original_history(self):
        old = self.catalogue(False); self.review(old, 'catalogue', decision='reject')
        self.client.force_login(self.f1)
        self.assertContains(self.client.get(reverse('insurance_catalogue', args=[old.pk])), '重新提交同一来源核对')
        url = reverse('insurance_resubmit', args=[old.pk]); token = self.preview(url, dict(reason='已核对前次事项，重新提交原文'))
        self.assertEqual(self.confirm(url, token).status_code, 302)
        row = PolicyCatalogue.objects.get(previous=old)
        self.assertEqual(row.review_attempt, 2); self.assertEqual(row.state, 'DRAFT')
        self.assertEqual(self.confirm(url, token).status_code, 302); self.assertEqual(PolicyCatalogue.objects.count(), 2)
        self.assertContains(self.client.get(reverse('insurance_catalogue', args=[row.pk])), '查看前次审阅记录')
        self.assertEqual(self.confirm(reverse('insurance_resubmit', args=[row.pk]), token).status_code, 409)

    def test_frontdesk_eligibility_preview_confirmation_and_history(self):
        self.arrangement(); self.client.force_login(self.front)
        url = reverse('insurance_eligibility', args=[self.p1.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        token = self.preview(url, dict(insured_region='CN-43', scheme='EMPLOYEE', state='VERIFIED', starts_on=str(self.today), ends_on=str(self.end), reference='SIM-HTTP-BENEFIT', basis='课程合成待遇'))
        self.assertFalse(EligibilityFact.objects.exists()); self.assertEqual(self.confirm(url, token).status_code, 302)
        self.assertEqual(self.confirm(url, token).status_code, 302); self.assertEqual(EligibilityFact.objects.count(), 1)
        response = self.client.get(url); self.assertContains(response, 'V1'); self.assertContains(response, 'SIM-HTTP-BENEFIT')
        read = SensitiveReadEvent.objects.filter(object_kind='INSURANCE_ELIGIBILITY', outcome='ALLOW').last()
        self.assertEqual(read.object_id, self.p1.pk)

    def test_current_clinic_rejects_other_patient_and_other_arrangement(self):
        row = self.arrangement(publish=False)
        self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse('insurance_eligibility', args=[self.p2.pk])).status_code, 404)
        RoleAssignment.objects.create(user=self.manager, role='MANAGER', scope_kind='CLINIC', clinic=self.b)
        self.client.force_login(self.manager)
        self.client.post(reverse('activate_clinic'), dict(clinic=self.b.pk))
        self.assertEqual(self.client.get(reverse('insurance_detail', args=['arrangement', row.pk])).status_code, 404)

    def test_all_seven_role_entry_boundaries_and_hq_projection(self):
        hq = UserAccount.objects.create_user(username='insurance-hq', password='isolated-test-password-123')
        RoleAssignment.objects.create(user=hq, role='HQ', scope_kind='CHAIN')
        doctor = UserAccount.objects.create_user(username='insurance-doctor', password='isolated-test-password-123', dentist=self.d1)
        RoleAssignment.objects.create(user=doctor, role='DENTIST', scope_kind='SELF_DENTIST')
        patient = UserAccount.objects.create_user(username='insurance-patient', password='isolated-test-password-123')
        PatientAccess.objects.create(user=patient, patient=self.p1)
        for actor, status in [(self.front, 200), (self.manager, 200), (self.f1, 200), (hq, 200), (doctor, 403), (patient, 403), (self.tech, 403)]:
            with self.subTest(actor=actor.username):
                self.client.force_login(actor); response = self.client.get(reverse('insurance_home'))
                self.assertEqual(response.status_code, status)
                if actor == hq:
                    self.assertNotContains(response, self.p1.name); self.assertNotContains(response, self.p1.patient_no)
                    self.assertNotContains(response, '选择患者并核对待遇')

    def test_anonymous_and_non_finance_import_cannot_reach_writes(self):
        self.assertEqual(self.client.get(reverse('insurance_home')).status_code, 302)
        self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse('insurance_import')).status_code, 403)
        self.assertEqual(self.client.get(reverse('insurance_arrangement_new')).status_code, 403)
        self.assertEqual(self.client.get(reverse('insurance_mapping_new')).status_code, 403)

    def test_unknown_detail_kind_is_not_a_server_failure(self):
        self.client.force_login(self.f2)
        for route in ['insurance_detail', 'insurance_review', 'insurance_disable']:
            self.assertEqual(self.client.get(reverse(route, args=['unknown', 1])).status_code, 404)

    def test_manager_has_no_patient_eligibility_projection(self):
        self.create(self.eligibility_preview(), self.front); self.client.force_login(self.manager)
        response = self.client.get(reverse('insurance_home'))
        self.assertNotContains(response, self.p1.name); self.assertNotContains(response, self.p1.patient_no)
        self.assertEqual(self.client.get(reverse('insurance_eligibility', args=[self.p1.pk])).status_code, 403)

    def test_draft_source_is_finance_private_and_unknown_filter_is_bounded(self):
        row = self.catalogue(False); self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('insurance_catalogue', args=[row.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('insurance_source', args=[row.pk])).status_code, 404)
        self.client.force_login(self.f2)
        self.assertEqual(self.client.get(reverse('insurance_catalogue', args=[row.pk]), dict(issue='invalid')).status_code, 400)

    def test_csrf_and_current_workspace_are_both_required(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.f1)
        ctx = WorkspaceContext.objects.create(user=self.f1, role='FINANCE', login_channel='STAFF')
        session = client.session; session[SESSION_KEY] = str(ctx.pk); session.save()
        url = reverse('insurance_import'); client.get(url)
        self.assertEqual(client.post(url, dict(action='preview', source_key=catalogue_source.SOURCE_KEY, workspace_token=token_for(ctx))).status_code, 403)
        csrf = client.cookies['csrftoken'].value
        self.assertEqual(client.post(url, dict(action='preview', source_key=catalogue_source.SOURCE_KEY, csrfmiddlewaretoken=csrf)).status_code, 409)
        self.assertEqual(client.post(url, dict(action='preview', source_key=catalogue_source.SOURCE_KEY, csrfmiddlewaretoken=csrf, workspace_token=token_for(ctx))).status_code, 200)

    def test_revoked_authority_after_http_preview_never_creates_record(self):
        cat = self.catalogue(); self.client.force_login(self.manager)
        url = reverse('insurance_arrangement_new')
        token = self.preview(url, dict(catalogue_id=cat.pk, starts_on=str(self.today), ends_on=str(self.end), reference='SIM-REVOKED'))
        RoleAssignment.objects.filter(user=self.manager, clinic=self.a, role='MANAGER').update(is_active=False)
        self.assertIn(self.confirm(url, token).status_code, (403, 409)); self.assertFalse(ClinicArrangement.objects.exists())

    def test_confirmation_cannot_be_retargeted_to_other_record_page(self):
        cat = self.catalogue(); a = self.arrangement(cat, publish=False); b = self.arrangement(cat, publish=False)
        self.client.force_login(self.f2)
        url = reverse('insurance_review', args=['arrangement', a.pk]); token = self.preview(url, dict(decision='approve', reason='只核对原记录'))
        self.assertEqual(self.confirm(reverse('insurance_review', args=['arrangement', b.pk]), token).status_code, 409)
        self.assertFalse(ClinicArrangement.objects.filter(state='CONFIRMED').exists())
