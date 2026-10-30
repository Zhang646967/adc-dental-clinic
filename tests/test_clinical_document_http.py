"""Actual Django HTTP entry, patient binding, retained work and read audit."""
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from accounts.models import UserAccount, RoleAssignment
from clinical.document_models import ClinicalDocumentDraft, ClinicalDocumentVersion
from clinical.models import SensitiveReadEvent
from patients.models import Patient
from tests.test_clinical_documents import DocumentFixture
from tests.workspace_client import WorkspaceClient


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ClinicalDocumentHTTPTests(DocumentFixture, TransactionTestCase):
    def setUp(self):
        self.setup_document(); self.close_care()

    def client_for(self, user):
        client = WorkspaceClient(); client.force_login(user); return client

    def form_values(self, form):
        return {field.name: field.value() if field.value() is not None else '' for field in form}

    def save_values(self, client, visit=None, **extra):
        response = client.get(reverse('clinical_document', args=[(visit or self.v).pk]))
        values = self.form_values(response.context['document_form'])
        values.update({key: value if value is not None else '' for key, value in self.values().items()}, action='SAVE'); values.update(extra)
        return values

    def test_complete_http_document_confirmation_and_private_print(self):
        client = self.client_for(self.doc)
        self.assertEqual(client.post(reverse('clinical_document', args=[self.v.pk]), self.save_values(client)).status_code, 302)
        preview = client.get(reverse('clinical_document_preview', args=[self.v.pk]))
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, 'PRIVATE_DOCUMENT_DIAGNOSIS')
        self.assertFalse(ClinicalDocumentVersion.objects.exists())
        data = self.form_values(preview.context['form']); data['confirmed'] = 'on'
        self.assertEqual(client.post(reverse('clinical_document_confirm'), data).status_code, 302)
        printed = client.get(reverse('clinical_document_print', args=[self.v.pk]))
        self.assertContains(printed, 'PRIVATE_DOCUMENT_ADVICE')
        self.assertContains(printed, '不含机构印章')
        self.assertTrue(SensitiveReadEvent.objects.filter(actor=self.doc, purpose='DOCUMENT', outcome='ALLOW').exists())

    def test_seven_roles_do_not_gain_document_full_text(self):
        self.save(); self.confirm_doc()
        finance = UserAccount.objects.create_user(username='document_finance')
        hq = UserAccount.objects.create_user(username='document_hq')
        for user, role in ((finance, 'FINANCE'), (hq, 'HQ')):
            RoleAssignment.objects.create(user=user, role=role, scope_kind='CHAIN')
        for actor in (self.doc, self.front, self.manager, self.tech, self.patient_user, finance, hq):
            client = self.client_for(actor)
            for name in ('clinical_documents', 'clinical_document', 'clinical_document_print'):
                url = reverse(name, args=[] if name == 'clinical_documents' else [self.v.pk])
                with self.subTest(actor=actor.username, route=name):
                    response = client.get(url)
                    self.assertEqual(response.status_code, 200 if actor == self.doc else 403)
                    if actor != self.doc:
                        self.assertNotIn(b'PRIVATE_DOCUMENT_DIAGNOSIS', response.content)

    def test_stale_form_keeps_entered_work_and_requires_explicit_resume(self):
        client = self.client_for(self.doc)
        first = self.save_values(client); second = self.save_values(client, diagnosis='UNSAVED_DOCUMENT_CHANGE')
        self.assertEqual(client.post(reverse('clinical_document', args=[self.v.pk]), first).status_code, 302)
        response = client.post(reverse('clinical_document', args=[self.v.pk]), second)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'UNSAVED_DOCUMENT_CHANGE', status_code=409)
        self.assertContains(response, 'PRIVATE_DOCUMENT_DIAGNOSIS', status_code=409)
        response = client.post(reverse('clinical_document', args=[self.v.pk]), dict(second, review_current='yes'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ClinicalDocumentDraft.objects.get().payload['diagnosis'], 'PRIVATE_DOCUMENT_DIAGNOSIS')
        continued = self.form_values(response.context['document_form']); continued['action'] = 'SAVE'
        self.assertEqual(client.post(reverse('clinical_document', args=[self.v.pk]), continued).status_code, 302)
        self.assertEqual(ClinicalDocumentDraft.objects.get().payload['diagnosis'], 'UNSAVED_DOCUMENT_CHANGE')

    def test_old_patient_binding_cannot_submit_to_another_visit(self):
        client = self.client_for(self.doc); data = self.save_values(client)
        visit = self.another()
        response = client.post(reverse('clinical_document', args=[visit.pk]), data)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ClinicalDocumentDraft.objects.exists())

    def test_history_is_read_only_and_comparison_retains_original(self):
        self.save(); self.confirm_doc(); self.act('AMEND', {'reason': '复核本次牙位判断，追加表述依据。'})
        self.save(diagnosis='CORRECTED_WEB_DOCUMENT'); self.confirm_doc()
        client = self.client_for(self.doc)
        compare = client.get(reverse('clinical_document_compare', args=[self.v.pk])+'?left=1&right=2')
        self.assertContains(compare, 'PRIVATE_DOCUMENT_DIAGNOSIS')
        self.assertContains(compare, 'CORRECTED_WEB_DOCUMENT')
        response = client.post(reverse('clinical_document', args=[self.v.pk])+'?revision=1', {'action': 'SAVE'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ClinicalDocumentVersion.objects.count(), 2)

    def test_print_uses_frozen_identity_not_current_directory(self):
        self.save(); row = self.confirm_doc()
        Patient.objects.filter(pk=self.v.patient_id).update(name='CURRENT_DIRECTORY_NAME_ONLY')
        client = self.client_for(self.doc)
        response = client.get(reverse('clinical_document_print', args=[self.v.pk])+'?revision=1')
        self.assertContains(response, row.source_snapshot['header']['patient_name'])
        self.assertNotContains(response, 'CURRENT_DIRECTORY_NAME_ONLY')

    def test_no_document_write_on_get_or_unconfirmed_post(self):
        self.save(); client = self.client_for(self.doc)
        preview = client.get(reverse('clinical_document_preview', args=[self.v.pk]))
        self.assertEqual(preview.status_code, 200)
        data = self.form_values(preview.context['form'])
        self.assertEqual(client.post(reverse('clinical_document_confirm'), data).status_code, 409)
        self.assertFalse(ClinicalDocumentVersion.objects.exists())

    def test_guessed_other_document_versions_are_not_comparable(self):
        self.save(); self.confirm_doc(); client = self.client_for(self.doc)
        self.assertEqual(client.get(reverse('clinical_document_compare', args=[self.v.pk])+'?left=1&right=999').status_code, 404)

    def test_queue_pages_render_without_publication_or_signature_side_effects(self):
        client = self.client_for(self.doc)
        for queue in ('pending', 'overdue', 'confirmed', 'all'):
            self.assertEqual(client.get(reverse('clinical_documents')+'?queue='+queue).status_code, 200)
        self.assertFalse(ClinicalDocumentVersion.objects.exists())
