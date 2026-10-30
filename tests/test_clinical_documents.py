"""C3.1 PostgreSQL workflows, retained history and adverse confirmations."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
import uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction, DatabaseError, close_old_connections
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from adc_core.rules import RuleError
from accounts.models import UserAccount, RoleAssignment
from care.models import Invoice, VisitRecordVersion, TreatmentRecord
from care.services import complete_visit
from clinical import documents as cmd, encounters
from clinical.document_models import ClinicalDocument, ClinicalDocumentDraft, ClinicalDocumentVersion, ClinicalDocumentEvent
from clinical.document_selectors import document_details, document_worklist, compare_versions
from clinical.models import ClinicalEncounter
from finance.cash_models import CashEntry
from patients.models import Patient
from tests.test_treatment_continuity import PlanFixture


class DocumentFixture(PlanFixture):
    def setup_document(self):
        self.setup_plan()

    def close_care(self, visit=None, treated=False):
        visit = visit or self.v
        if treated:
            self.actual(visit=visit); self.review(visit)
        visit.refresh_from_db()
        return complete_visit(actor=self.doc, visit_id=visit.pk, expected_version=visit.lock_version,
                              outcome='TREATED' if treated else 'NO_TREATMENT', reason='' if treated else '检查后无需治疗，已说明观察与复诊安排。')

    def values(self, **extra):
        data = dict(kind='INITIAL', diagnosis='PRIVATE_DOCUMENT_DIAGNOSIS', ancillary_results='本次无辅助检查结果。',
                    instructions='PRIVATE_DOCUMENT_ADVICE', follow_up='按需复诊；出现不适及时联系本店。',
                    prior_context='', prior_visit_version=None, evidence_kind='ACCOUNT_CONFIRMATION',
                    evidence_reference='', late_reason='')
        data.update(extra); return data

    def save(self, visit=None, actor=None, **fields):
        visit = visit or self.v
        head = ClinicalDocument.objects.get(encounter__visit=visit)
        return cmd.save_document(actor=actor or self.doc, visit_id=visit.pk, expected_revision=head.revision,
                                 operation_id=uuid.uuid4(), fields=self.values(**fields))[0]

    def act(self, action, fields, visit=None):
        visit = visit or self.v; head = ClinicalDocument.objects.get(encounter__visit=visit)
        return cmd.save_document(actor=self.doc, visit_id=visit.pk, expected_revision=head.revision,
                                 operation_id=uuid.uuid4(), fields=fields, action=action)[0]

    def confirm_doc(self, visit=None):
        prepared = cmd.prepare_document(actor=self.doc, visit_id=(visit or self.v).pk)
        return cmd.confirm_document(actor=self.doc, proposal_token=prepared['proposal_token'], confirmed=True)[0]

    def money(self):
        return [list(m.objects.order_by('pk').values()) for m in (Invoice, VisitRecordVersion, TreatmentRecord, CashEntry)]


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ClinicalDocumentTests(DocumentFixture, TransactionTestCase):
    def setUp(self):
        self.setup_document()

    def test_new_encounter_has_owned_pending_document_without_invented_signature(self):
        head = ClinicalDocument.objects.get(encounter__visit=self.v)
        self.assertEqual(head.responsible, self.doc)
        self.assertGreater(head.due_at, head.opened_at)
        self.assertFalse(ClinicalDocumentVersion.objects.exists())
        self.assertEqual(document_worklist(self.doc).count(), 1)

    def test_no_treatment_document_is_complete_without_new_money_or_procedures(self):
        self.close_care(); before = self.money(); self.save(); row = self.confirm_doc()
        self.assertEqual(row.source_snapshot['care']['outcome'], 'NO_TREATMENT')
        self.assertIn('PRIVATE_PLAN_CHIEF', row.source_snapshot['record']['chief_complaint'])
        self.assertEqual(row.content['instructions'], 'PRIVATE_DOCUMENT_ADVICE')
        self.assertEqual(before, self.money()); self.assertFalse(row.source_snapshot['actual'])
        self.assertIsNone(row.source_snapshot['history'])

    def test_actual_work_and_financial_sources_are_referenced_without_recharging(self):
        invoice = self.close_care(treated=True); before = self.money(); self.save(); row = self.confirm_doc()
        self.assertEqual(len(row.source_snapshot['actual']), 1)
        self.assertEqual(row.care_record_id, invoice.current_record_version_id)
        self.assertEqual(row.source_snapshot['actual'][0]['name'], '合成实际处置')
        self.assertEqual(before, self.money())

    def test_followup_references_exact_prior_version_without_copying_normal_findings(self):
        self.close_care(); self.save(); prior = self.confirm_doc(); visit = self.another()
        self.close_care(visit); self.save(visit, kind='FOLLOWUP', prior_visit_version=prior.pk,
                                          prior_context='复核上次检查，本次仍未取得新自述。')
        row = self.confirm_doc(visit)
        self.assertEqual(row.prior_visit_version_id, prior.pk)
        self.assertIsNone(row.source_snapshot['history'])
        self.assertEqual(ClinicalDocumentVersion.objects.count(), 2)

    def test_external_followup_needs_attributable_context(self):
        self.close_care(); self.save(kind='FOLLOWUP')
        with self.assertRaises(RuleError): self.confirm_doc()
        self.assertTrue(ClinicalDocumentDraft.objects.exists())
        self.save(kind='FOLLOWUP', prior_context='患者携带院外纸质记录，已逐项复核本次变化。')
        self.assertEqual(self.confirm_doc().kind, 'FOLLOWUP')

    def test_initial_document_cannot_claim_a_prior_visit_reference(self):
        self.close_care(); self.save(); prior = self.confirm_doc(); visit = self.another(); self.close_care(visit)
        self.save(visit, prior_visit_version=prior.pk)
        with self.assertRaises(RuleError): self.confirm_doc(visit)

    def test_missing_fields_preserve_draft_and_do_not_confirm(self):
        self.close_care(); self.save(diagnosis='')
        with self.assertRaises(RuleError): self.confirm_doc()
        self.assertEqual(ClinicalDocumentDraft.objects.get().payload['diagnosis'], '')
        self.assertFalse(ClinicalDocumentVersion.objects.exists())

    def test_complete_document_waits_for_actual_care_close_but_does_not_block_it(self):
        self.save()
        with self.assertRaises(RuleError): self.confirm_doc()
        self.close_care(); self.v.refresh_from_db()
        self.assertEqual(self.v.status, 'CLOSED_NO_TREATMENT')
        self.assertTrue(ClinicalDocumentDraft.objects.exists()); self.confirm_doc()

    def test_confirmed_content_requires_reasoned_append_amendment(self):
        self.close_care(); self.save(); first = self.confirm_doc(); before = self.money()
        with self.assertRaises(RuleError): self.save(diagnosis='cannot overwrite')
        self.act('AMEND', {'reason': '复核后补充诊断表述，保留原判断依据。'})
        self.save(diagnosis='PRIVATE_CORRECTED_DIAGNOSIS'); second = self.confirm_doc()
        first.refresh_from_db()
        self.assertEqual(first.content['diagnosis'], 'PRIVATE_DOCUMENT_DIAGNOSIS')
        self.assertEqual(second.previous_id, first.pk); self.assertEqual(second.revision, 2)
        self.assertEqual(before, self.money())
        comparison = compare_versions(second.document, 1, 2)
        self.assertTrue(next(x for x in comparison['comparison_rows'] if x['label'] == '诊断／判断')['changed'])

    def test_discard_keeps_previous_confirmed_version_and_reason(self):
        self.close_care(); self.save(); first = self.confirm_doc()
        self.act('AMEND', {'reason': '核对原说明后准备追加补充内容。'})
        self.act('DISCARD', {'reason': '已复核原文准确，本次不再追加更正。'})
        self.assertFalse(ClinicalDocumentDraft.objects.exists())
        self.assertEqual(cmd.latest_version(first.document).pk, first.pk)
        self.assertTrue(ClinicalDocumentEvent.objects.filter(action='DISCARD').exists())

    def test_preview_is_invalid_after_draft_changes(self):
        self.close_care(); self.save(); p = cmd.prepare_document(actor=self.doc, visit_id=self.v.pk)
        self.save(diagnosis='new current')
        with self.assertRaises(RuleError): cmd.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertFalse(ClinicalDocumentVersion.objects.exists())

    def test_preview_is_invalid_after_clinical_source_amendment(self):
        self.close_care(); self.save(); p = cmd.prepare_document(actor=self.doc, visit_id=self.v.pk)
        head = ClinicalEncounter.objects.get(visit=self.v)
        encounters.change_draft(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision,
                                operation_id=uuid.uuid4(), action='BEGIN_AMEND', fields={'reason': '补充检查后确认的观察依据。'})
        encounters.confirm_record(actor=self.doc, proposal_token=encounters.prepare_record(actor=self.doc, visit_id=self.v.pk)['proposal_token'], confirmed=True)
        with self.assertRaises(RuleError): cmd.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertTrue(ClinicalDocumentDraft.objects.exists())

    def test_source_change_returns_confirmed_document_to_review_queue(self):
        self.close_care(); self.save(); self.confirm_doc()
        head = ClinicalEncounter.objects.get(visit=self.v)
        encounters.change_draft(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision,
                                operation_id=uuid.uuid4(), action='BEGIN_AMEND', fields={'reason': '复核后补充原检查版本的说明。'})
        encounters.confirm_record(actor=self.doc, proposal_token=encounters.prepare_record(actor=self.doc, visit_id=self.v.pk)['proposal_token'], confirmed=True)
        self.assertTrue(document_worklist(self.doc).get().needs_source_review)
        self.assertTrue(document_details(self.doc, self.v.pk)['source_changed'])

    def test_successful_confirmation_retry_has_one_effect(self):
        self.close_care(); self.save(); p = cmd.prepare_document(actor=self.doc, visit_id=self.v.pk)
        first, _ = cmd.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        second, replay = cmd.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertEqual(first.pk, second.pk); self.assertTrue(replay)
        self.assertEqual(ClinicalDocumentVersion.objects.count(), 1)

    def test_same_operation_with_new_content_is_not_misreported_as_success(self):
        head = ClinicalDocument.objects.get(); op = uuid.uuid4()
        args = dict(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision, operation_id=op)
        cmd.save_document(**args, fields=self.values())
        with self.assertRaises(RuleError): cmd.save_document(**args, fields=self.values(diagnosis='changed retry'))

    def test_revoked_authority_blocks_stale_confirmation_and_retry(self):
        self.close_care(); self.save(); p = cmd.prepare_document(actor=self.doc, visit_id=self.v.pk)
        self.decide(self.authority, 'REVOKE')
        with self.assertRaises(PermissionDenied): cmd.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertFalse(ClinicalDocumentVersion.objects.exists())

    def test_inactive_role_does_not_write(self):
        RoleAssignment.objects.filter(user=self.doc, role='DENTIST').update(is_active=False)
        with self.assertRaises(PermissionDenied): self.save()

    def test_other_doctor_and_patient_cannot_read_or_write_document(self):
        for actor in (self.reviewer, self.patient_user, self.front, self.manager, self.tech):
            with self.subTest(actor=actor.username):
                with self.assertRaises(PermissionDenied): document_details(actor, self.v.pk)
                with self.assertRaises(PermissionDenied): self.save(actor=actor)

    def test_prior_document_cannot_cross_patient(self):
        self.close_care(); self.save(); prior = self.confirm_doc()
        visit = self.booking(patient=self.p2, start=self.t+timedelta(minutes=30))
        from scheduling.models import Visit
        Visit.objects.filter(pk=visit.pk).update(status='CHECKED_IN', attended=True, attended_at=timezone.now()-timedelta(minutes=1))
        visit.refresh_from_db(); self.clinical(visit)
        with self.assertRaises(PermissionDenied): self.save(visit, kind='FOLLOWUP', prior_visit_version=prior.pk)
        self.assertFalse(ClinicalDocumentDraft.objects.filter(document__encounter__visit=visit).exists())

    def test_paper_reference_requires_actual_original_location(self):
        self.close_care(); self.save(evidence_kind='PAPER_REFERENCE')
        with self.assertRaises(RuleError): self.confirm_doc()
        self.save(evidence_kind='PAPER_REFERENCE', evidence_reference='课程纸质原件柜A／本次就诊编号，人工核验登记。')
        self.assertEqual(self.confirm_doc().evidence_kind, 'PAPER_REFERENCE')

    @override_settings(ADC_CLINICAL_DOCUMENT_DUE_HOURS=-1)
    def test_late_confirmation_requires_reason_and_preserves_actual_times(self):
        visit = self.another(); self.close_care(visit); self.save(visit)
        with self.assertRaises(RuleError): self.confirm_doc(visit)
        self.save(visit, late_reason='当日材料补充后由负责医师完成文书。'); row = self.confirm_doc(visit)
        self.assertGreater(row.confirmed_at, row.document.due_at)
        self.assertLessEqual(row.source_record.observed_at, row.confirmed_at)

    def test_followup_does_not_clear_original_due_or_forge_completion(self):
        head = ClinicalDocument.objects.get(); deadline = head.due_at
        self.act('FOLLOWUP', {'note': '等待核对资料，已明确下一次办理时间。', 'due_at': timezone.now()+timedelta(days=2)})
        head.refresh_from_db(); self.assertEqual(head.due_at, deadline)
        self.assertIsNotNone(head.next_action_at); self.assertFalse(ClinicalDocumentVersion.objects.exists())

    def test_old_header_and_digest_do_not_follow_directory_changes(self):
        self.close_care(); self.save(); row = self.confirm_doc(); original = row.source_snapshot; digest = row.content_digest
        Patient.objects.filter(pk=self.v.patient_id).update(name='后续更正的显示姓名')
        row.refresh_from_db(); self.assertEqual(row.source_snapshot, original); self.assertEqual(row.content_digest, digest)

    def test_database_rejects_confirmed_history_and_event_rewrite(self):
        self.close_care(); self.save(); row = self.confirm_doc()
        for model, pk, changes in [(ClinicalDocumentVersion, row.pk, {'content': {'diagnosis': 'overwrite'}}),
                                   (ClinicalDocumentEvent, ClinicalDocumentEvent.objects.latest('pk').pk, {'note': 'overwrite'})]:
            with self.subTest(model=model):
                with self.assertRaises(DatabaseError), transaction.atomic(): model.objects.filter(pk=pk).update(**changes)
        row.refresh_from_db(); self.assertEqual(row.content['diagnosis'], 'PRIVATE_DOCUMENT_DIAGNOSIS')

    def test_concurrent_confirmations_commit_exactly_one_version(self):
        self.close_care(); self.save()
        tokens = [cmd.prepare_document(actor=self.doc, visit_id=self.v.pk)['proposal_token'] for _ in range(2)]
        barrier = Barrier(2); ctx = self.doc._adc_workspace
        def worker(token):
            close_old_connections()
            actor = UserAccount.objects.get(pk=self.doc.pk); actor._adc_workspace = ctx
            barrier.wait()
            try:
                cmd.confirm_document(actor=actor, proposal_token=token, confirmed=True); return 'saved'
            except RuleError: return 'stale'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(worker, tokens))
        self.assertCountEqual(results, ['saved', 'stale']); self.assertEqual(ClinicalDocumentVersion.objects.count(), 1)
