"""C3.3A PostgreSQL archive, independent review and exact-content amendment contracts."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import BytesIO
from threading import Barrier
from unittest.mock import patch
import hashlib, uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction, DatabaseError, close_old_connections
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.governance import change_account, target_token
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from clinical import archives, archive_corrections as corrections, archive_generation as generation
from clinical import archive_selectors as queries, documents, encounters, preflight
from clinical.archive_models import ClinicalArchive, ArchiveSubmission, ArchivePackage, ArchiveAmendment, ArchiveEvent
from clinical.archive_sources import capture
from clinical.document_models import ClinicalDocument, ClinicalDocumentVersion
from clinical.encounter_models import ClinicalEncounter, ClinicalRecordVersion
from clinical.models import ClinicalReviewerAppointment
from clinical.authority_services import prepare_authority, confirm_authority
from registry.models import TreatmentType
from tests.test_clinical_documents import DocumentFixture
from tests.workspace_client import WorkspaceClient


class ArchiveFixture(DocumentFixture):
    def setup_archive(self):
        self.setup_document()
        self.appoint(self.doc, self.a); self.ctx(self.doc, 'DENTIST')
        p = prepare_authority(actor=self.manager, action='PROPOSE', fields=self.fields(self.reviewer, can_record=False, can_refer=False))
        auth, _ = confirm_authority(actor=self.manager, proposal_token=p['proposal_token'], confirmed=True)
        self.decide(auth, 'APPROVE', actor=self.doc); self.review_scope = auth
        self.archive_duty(True)
        self.ctx(self.doc, 'DENTIST'); self.ctx(self.reviewer, 'DENTIST')

    def archive_duty(self, enabled):
        change_account(actor=self.tech, target_id=self.reviewer.pk, token=target_token(self.tech, self.reviewer),
            action='archive_reviewer', operator_password='test-only-pass-abc', reason='课程合成：登记独立病历审核职责',
            clinic_id=self.a.pk, reviewer_enabled=enabled)
        self.ctx(self.reviewer, 'DENTIST')

    def ready(self):
        self.close_care(); self.save(); return self.confirm_doc()

    def submit_archive(self, **kw):
        p = archives.prepare_submit(actor=self.doc, visit_id=self.v.pk, reason='本次就诊已结束，核对准确版本申请留存。', **kw)
        return archives.confirm_submit(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)[0]

    def approve(self, row, decision='APPROVE'):
        p = archives.prepare_review(actor=self.reviewer, submission_id=row.pk, decision=decision, note='独立核对本次文书、来源及缺项分类。')
        return archives.confirm_review(actor=self.reviewer, proposal_token=p['proposal_token'], confirmed=True)[0]

    def fixed(self):
        self.ready(); row = self.submit_archive(); self.approve(row)
        self.assertTrue(generation.generate(row.pk)['published'])
        return ArchivePackage.objects.get(submission=row)

    def amendment(self, target='DOCUMENT'):
        p = corrections.prepare_submit(actor=self.doc, visit_id=self.v.pk, target=target, reason='追加核实后得到的准确补正内容，原文保留。')
        return corrections.confirm_submit(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)[0]

    def approve_amendment(self, row):
        p = corrections.prepare_review(actor=self.reviewer, amendment_id=row.pk, decision='APPROVE', note='已独立比较更正前后及实际来源。')
        return corrections.confirm_review(actor=self.reviewer, proposal_token=p['proposal_token'], confirmed=True)[0]

    def amend_draft(self):
        self.act('AMEND', {'reason': '复核后补充判断依据，保留原确认版本。'})
        self.save(diagnosis='PRIVATE_ARCHIVE_CORRECTED')


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalArchiveTests(ArchiveFixture, TransactionTestCase):
    def setUp(self): self.setup_archive()

    def test_new_confirmation_creates_owned_deadline_without_historical_backfill(self):
        self.assertFalse(ClinicalArchive.objects.exists())
        self.ready(); head = ClinicalArchive.objects.get()
        self.assertEqual(head.responsible_id, self.doc.pk)
        self.assertGreater(head.due_at, head.created_at)
        self.assertFalse(ArchiveSubmission.objects.exists())

    def test_complete_archive_is_independently_reviewed_and_has_fixed_embedded_pdf(self):
        self.ready(); before = self.money(); row = self.submit_archive()
        self.assertEqual(row.state, 'PENDING'); self.assertFalse(ArchivePackage.objects.exists())
        self.approve(row); self.assertFalse(ArchivePackage.objects.exists())
        result = generation.generate(row.pk); package = ArchivePackage.objects.get()
        self.assertTrue(result['published']); self.assertTrue(bytes(package.pdf).startswith(b'%PDF-'))
        self.assertEqual(package.pdf_sha256, hashlib.sha256(bytes(package.pdf)).hexdigest())
        self.assertIn(b'/FontFile2', bytes(package.pdf))
        self.assertIsNone(package.manifest['source_snapshot']['clinical_source']['history'])
        self.assertEqual(package.manifest['review']['account'], self.reviewer.pk)
        self.assertEqual(before, self.money())
        self.assertEqual(generation.generate(row.pk)['state'], 'PUBLISHED')
        self.assertEqual(ArchivePackage.objects.count(), 1)

    def test_missing_document_and_open_care_do_not_become_complete_archive(self):
        with self.assertRaises(RuleError): self.submit_archive()
        self.close_care()
        with self.assertRaises(RuleError): self.submit_archive()
        self.assertFalse(ArchiveSubmission.objects.exists())

    def test_explicit_materials_preservation_keeps_draft_and_missing_status(self):
        self.close_care(); self.save(diagnosis='')
        row = self.submit_archive(kind='MATERIALS'); self.approve(row); generation.generate(row.pk)
        package = ArchivePackage.objects.get()
        self.assertEqual(package.submission.kind, 'MATERIALS')
        self.assertTrue(package.manifest['source_snapshot']['issues'])
        self.assertEqual(package.manifest['source_snapshot']['drafts']['documents'][0]['payload']['diagnosis'], '')
        self.assertFalse(queries.worklist(self.doc)['owned'].get().archived)
        self.save(); self.confirm_doc()  # Materials alone must not block the normal completion path.

    def test_legacy_actual_without_preflight_stays_explicitly_incomplete(self):
        self.close_care(treated=True); self.save(); self.confirm_doc()
        with self.assertRaises(RuleError): self.submit_archive()
        row = self.submit_archive(kind='MATERIALS')
        self.assertIn('PREFLIGHT_MISSING', [r['code'] for r in row.snapshot['issues']])
        self.assertFalse(ArchivePackage.objects.exists())

    def test_unpaid_valid_treatment_can_archive_without_financial_side_effects(self):
        self.review()
        for item in TreatmentType.objects.filter(is_active=True):
            p = preflight.prepare_rule(actor=self.reviewer, clinic_id=self.a.pk, treatment_id=item.pk, mode='COMMUNICATION',
                reference='SYNTHETIC-ARCHIVE-RULE', explanation='课程合成：逐项沟通与开治核对。')
            preflight.confirm_rule(actor=self.reviewer, proposal_token=p['proposal_token'], confirmed=True)
        p = preflight.prepare_rule(actor=self.reviewer, clinic_id=self.a.pk, activate=True, reference='SYNTHETIC-ARCHIVE-ACTIVATE')
        preflight.confirm_rule(actor=self.reviewer, proposal_token=p['proposal_token'], confirmed=True)
        p = preflight.prepare(actor=self.doc, visit_id=self.v.pk, fields=self.actual_fields(), communication='核对本人、牙位和本次实际处置范围。')
        check, _ = preflight.confirm(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.actual(preflight=check.pk)
        from care.services import complete_visit
        self.v.refresh_from_db(); complete_visit(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version, outcome='TREATED')
        self.save(); self.confirm_doc(); before = self.money()
        row = self.submit_archive(); self.approve(row); generation.generate(row.pk)
        self.assertEqual(before, self.money()); self.assertEqual(ArchivePackage.objects.count(), 1)
        self.assertEqual(row.snapshot['fee']['amount'], '100.00')

    def test_generic_review_appointment_does_not_grant_archive_duty(self):
        self.ready(); self.archive_duty(False)
        with self.assertRaises(RuleError): self.submit_archive()
        self.assertFalse(ArchiveSubmission.objects.exists())

    def test_author_and_non_medical_roles_cannot_independently_approve(self):
        self.ready(); row = self.submit_archive()
        for actor in (self.doc, self.front, self.manager, self.tech, self.patient_user):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                archives.prepare_review(actor=actor, submission_id=row.pk, decision='APPROVE', note='不能替代独立审核')
        row.refresh_from_db(); self.assertEqual(row.state, 'PENDING')

    def test_stale_preview_leaves_no_partial_request(self):
        self.ready(); p = archives.prepare_submit(actor=self.doc, visit_id=self.v.pk, reason='初次预览准确清单。')
        self.act('AMEND', {'reason': '准备补充检查后确认的准确内容。'})
        with self.assertRaises(RuleError): archives.confirm_submit(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertFalse(ArchiveSubmission.objects.exists())

    def test_submit_retry_returns_original_request_once(self):
        self.ready(); p = archives.prepare_submit(actor=self.doc, visit_id=self.v.pk, reason='确认本次完成的归档清单。')
        a, _ = archives.confirm_submit(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        b, replay = archives.confirm_submit(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertTrue(replay); self.assertEqual(a.pk, b.pk); self.assertEqual(ArchiveSubmission.objects.count(), 1)

    def test_return_preserves_history_and_allows_new_exact_request(self):
        self.ready(); first = self.submit_archive(); self.approve(first, 'RETURN')
        second = self.submit_archive(); first.refresh_from_db()
        self.assertEqual(first.state, 'RETURNED'); self.assertEqual(second.number, 2)
        self.assertEqual(ArchiveSubmission.objects.count(), 2)

    def test_revoked_duty_invalidates_old_review_and_generation(self):
        self.ready(); row = self.submit_archive(); self.approve(row); self.archive_duty(False)
        self.assertEqual(generation.generate(row.pk)['state'], 'STALE')
        self.assertFalse(ArchivePackage.objects.exists())

    def test_source_change_after_approval_does_not_publish_old_file(self):
        self.ready(); row = self.submit_archive(); self.approve(row)
        self.act('AMEND', {'reason': '负责医师发现仍需完善本次说明。'})
        self.assertEqual(generation.generate(row.pk)['state'], 'STALE')
        self.assertFalse(ArchivePackage.objects.exists())

    def test_generation_failure_is_visible_and_requires_explicit_retry(self):
        self.ready(); row = self.submit_archive(); self.approve(row)
        with patch('clinical.archive_generation.render', side_effect=RuntimeError('PRIVATE_CLINICAL_TEXT')):
            self.assertEqual(generation.generate(row.pk)['state'], 'FAILED')
        row.refresh_from_db(); self.assertEqual(row.generation_error, 'PDF_RENDER_FAILED')
        self.assertEqual(generation.generate(row.pk)['state'], 'FAILED')
        p = archives.prepare_action(actor=self.doc, submission_id=row.pk, action='RETRY', reason='已排除生成故障，核对资料未变化。')
        archives.confirm_action(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertTrue(generation.generate(row.pk)['published']); self.assertEqual(ArchivePackage.objects.count(), 1)

    def test_package_and_source_and_event_cannot_be_overwritten(self):
        package = self.fixed()
        objects = [(ArchivePackage, package.pk, {'pdf': b'%PDF-overwrite'}),
            (ArchiveSubmission, package.submission_id, {'reason': 'overwrite'}),
            (ArchiveEvent, ArchiveEvent.objects.last().pk, {'note': 'overwrite'})]
        for model, pk, values in objects:
            with self.subTest(model=model), self.assertRaises(DatabaseError), transaction.atomic():
                model.objects.filter(pk=pk).update(**values)
        self.assertEqual(bytes(ArchivePackage.objects.get().pdf), bytes(package.pdf))

    def test_archived_document_requires_approved_exact_amendment(self):
        package = self.fixed(); old_pdf = bytes(package.pdf); before = self.money(); self.amend_draft()
        with self.assertRaises(RuleError): self.confirm_doc()
        client=WorkspaceClient();client.force_login(self.doc)
        response=client.get(reverse('clinical_document_preview',args=[self.v.pk]))
        self.assertEqual(response.status_code,409);self.assertContains(response,'先取得独立医务批准',status_code=409)
        row = self.amendment(); self.approve_amendment(row)
        version = self.confirm_doc(); row.refresh_from_db()
        self.assertEqual(row.state, 'APPLIED'); self.assertEqual(row.result_document_id, version.pk)
        self.assertEqual(version.content['diagnosis'], 'PRIVATE_ARCHIVE_CORRECTED')
        next_request = self.submit_archive(); self.approve(next_request); generation.generate(next_request.pk)
        newer = ArchivePackage.objects.latest('pk')
        self.assertEqual(newer.previous_id, package.pk); self.assertEqual(newer.number, 2)
        package.refresh_from_db(); self.assertEqual(bytes(package.pdf), old_pdf); self.assertEqual(before, self.money())

    def test_changed_draft_cannot_consume_old_approval(self):
        self.fixed(); self.amend_draft(); row = self.amendment(); self.approve_amendment(row)
        self.save(diagnosis='PRIVATE_UNAPPROVED_CONTENT')
        with self.assertRaises(RuleError): self.confirm_doc()
        row.refresh_from_db(); self.assertEqual(row.state, 'APPROVED'); self.assertEqual(ClinicalDocumentVersion.objects.count(), 1)

    def test_missing_amendment_draft_has_business_error(self):
        self.fixed()
        with self.assertRaises(RuleError): self.amendment()
        self.assertFalse(ArchiveAmendment.objects.exists())

    def test_record_correction_requires_its_own_approval_and_retains_tooth_source(self):
        self.fixed(); head = ClinicalEncounter.objects.get(visit=self.v)
        encounters.change_draft(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision, operation_id=uuid.uuid4(),
            action='BEGIN_AMEND', fields={'reason': '核对本次检查后补充实际观察。'})
        with self.assertRaises(RuleError): encounters.prepare_record(actor=self.doc, visit_id=self.v.pk)
        row = self.amendment('RECORD'); self.approve_amendment(row)
        p = encounters.prepare_record(actor=self.doc, visit_id=self.v.pk)
        version, _ = encounters.confirm_record(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        row.refresh_from_db(); self.assertEqual(row.state, 'APPLIED'); self.assertEqual(row.result_record_id, ClinicalRecordVersion.objects.filter(encounter=version).latest('revision').pk)
        self.assertEqual(ClinicalRecordVersion.objects.count(), 2)
        with self.assertRaises(RuleError): self.submit_archive()  # The complete document still needs its corresponding source update.

    def test_database_prevents_new_document_version_bypassing_review(self):
        self.fixed(); old = ClinicalDocumentVersion.objects.get()
        values = {f.attname: getattr(old, f.attname) for f in old._meta.fields if not f.primary_key}
        values.update(revision=2, previous_id=old.pk, amendment_reason='attempt')
        with self.assertRaises(DatabaseError), transaction.atomic(): ClinicalDocumentVersion.objects.create(**values)
        self.assertEqual(ClinicalDocumentVersion.objects.count(), 1)

    def test_clinic_summary_has_status_but_no_medical_text(self):
        self.fixed()
        for actor in (self.front, self.manager):
            self.ctx(actor, actor._adc_workspace.role, self.a)
            data = queries.summary(actor)
            self.assertEqual(data['counts'].get()['archived_total'], 1)
        client = WorkspaceClient(); client.force_login(self.front)
        response = client.get(reverse('clinical_archive_summary'))
        self.assertEqual(response.status_code, 200); self.assertNotContains(response, 'PRIVATE_DOCUMENT_DIAGNOSIS')
        self.assertEqual(client.get(reverse('clinical_archive', args=[self.v.pk])).status_code, 403)

    def test_patient_and_other_roles_cannot_download_or_read_archive(self):
        package = self.fixed()
        for actor in (self.patient_user, self.front, self.manager, self.tech):
            client = WorkspaceClient(); client.force_login(actor)
            with self.subTest(actor=actor.username):
                self.assertEqual(client.get(reverse('clinical_archive_download', args=[package.pk])).status_code, 403)
                self.assertEqual(client.get(reverse('clinical_archive_manifest', args=[package.pk])).status_code, 403)
        client = WorkspaceClient(); client.force_login(self.reviewer)
        self.assertEqual(client.get(reverse('clinical_archive_download', args=[package.pk])).status_code, 200)

    def test_archive_header_and_file_do_not_follow_later_directory_edits(self):
        package = self.fixed(); snapshot = package.submission.snapshot; data = bytes(package.pdf)
        from patients.models import Patient
        Patient.objects.filter(pk=self.v.patient_id).update(name='后续核实的目录姓名')
        self.assertEqual(capture(self.v)['header'], snapshot['header'])
        package.refresh_from_db(); self.assertEqual(bytes(package.pdf), data)

    def test_auth_revocation_blocks_download_of_old_package(self):
        package = self.fixed(); self.decide(self.review_scope, 'REVOKE', actor=self.doc)
        self.ctx(self.reviewer, 'DENTIST')
        client = WorkspaceClient(); client.force_login(self.reviewer)
        self.assertEqual(client.get(reverse('clinical_archive_download', args=[package.pk])).status_code, 403)

    def test_concurrent_submissions_leave_one_active_request(self):
        self.ready(); tokens = [archives.prepare_submit(actor=self.doc, visit_id=self.v.pk, reason='并发确认准确版本。')['proposal_token'] for _ in range(2)]
        barrier = Barrier(2); context = self.doc._adc_workspace
        def work(token):
            close_old_connections(); actor = UserAccount.objects.get(pk=self.doc.pk); actor._adc_workspace = context
            barrier.wait()
            try: archives.confirm_submit(actor=actor, proposal_token=token, confirmed=True); return 'saved'
            except RuleError: return 'stale'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: result = list(pool.map(work, tokens))
        self.assertCountEqual(result, ['saved', 'stale']); self.assertEqual(ArchiveSubmission.objects.count(), 1)

    def test_concurrent_generators_publish_one_file_and_one_history_effect(self):
        self.ready(); row = self.submit_archive(); self.approve(row); barrier = Barrier(2)
        def work(_):
            close_old_connections(); barrier.wait()
            try: return generation.generate(row.pk)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: result = list(pool.map(work, range(2)))
        self.assertEqual(sum(r['published'] for r in result), 1)
        self.assertEqual(ArchivePackage.objects.count(), 1)
        self.assertEqual(ArchiveEvent.objects.filter(action='GENERATION_PUBLISHED').count(), 1)

    def test_other_clinic_duty_does_not_allow_review(self):
        self.ready(); row = self.submit_archive(); self.archive_duty(False)
        change_account(actor=self.tech, target_id=self.reviewer.pk, token=target_token(self.tech, self.reviewer), action='archive_reviewer',
            operator_password='test-only-pass-abc', reason='课程合成：仅另一店归档职责', clinic_id=self.b.pk, reviewer_enabled=True)
        self.ctx(self.reviewer, 'DENTIST')
        with self.assertRaises(PermissionDenied): self.approve(row)

    def test_review_preview_becomes_invalid_when_duty_revoked(self):
        self.ready(); row = self.submit_archive()
        p = archives.prepare_review(actor=self.reviewer, submission_id=row.pk, decision='APPROVE', note='独立核对准确来源后确认。')
        self.archive_duty(False)
        with self.assertRaises((PermissionDenied, RuleError)): archives.confirm_review(actor=self.reviewer, proposal_token=p['proposal_token'], confirmed=True)
        row.refresh_from_db(); self.assertEqual(row.state, 'PENDING')

    def test_generation_scope_revoke_rejects_old_approved_job(self):
        self.ready(); row = self.submit_archive(); self.approve(row)
        self.decide(self.review_scope, 'REVOKE', actor=self.doc)
        self.assertEqual(generation.generate(row.pk)['state'], 'STALE')
        self.assertFalse(ArchivePackage.objects.exists())

    def test_unanswered_question_requires_followup_not_fake_archive(self):
        plan = self.new_plan(); step = self.publish_plan(plan).steps.get()
        from clinical import consents
        from clinical.disclosures import FIELDS
        # An unsatisfied clinical explanation cannot be replaced by an archive approval.
        self.command(plan, 'BEGIN_AMEND', reason='补充可供本人提问的具体医疗说明。')
        raw = __import__('clinical.plan_models', fromlist=['PlanDraft']).PlanDraft.objects.get(plan=plan).payload['steps'][0]
        self.command(plan, 'DISCLOSURE', **dict({k:'课程合成医疗说明' for k,_,_ in FIELDS}, sequence=1, step_key=raw['step_key'], prepared=True))
        step = self.publish_plan(plan).steps.get()
        self.decision(step)
        p = consents.prepare(actor=self.doc, action='PUBLISH', step_id=step.pk, visit_id=self.v.pk,
            fields={'identity_reference':'SYNTHETIC-ARCHIVE-SELF','self_qualified':True})
        consents.confirm(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        p = consents.prepare(actor=self.patient_user, action='QUESTION', step_id=step.pk, fields={'text':'本次说明仍有疑问，需要医师继续解释。'})
        consents.confirm(actor=self.patient_user, proposal_token=p['proposal_token'], confirmed=True)
        self.ready()
        with self.assertRaises(RuleError): self.submit_archive()
        self.assertIn('UNANSWERED_QUESTION', [r['code'] for r in capture(self.v)['issues']])

    def test_approved_amendment_cannot_survive_review_authority_revocation(self):
        self.fixed(); self.amend_draft(); row = self.amendment(); self.approve_amendment(row)
        self.archive_duty(False)
        with self.assertRaises(PermissionDenied): self.confirm_doc()
        self.assertEqual(ClinicalDocumentVersion.objects.count(), 1)

    def test_correction_confirmation_retry_has_one_effect(self):
        self.fixed(); self.amend_draft(); row = self.amendment(); self.approve_amendment(row)
        p = documents.prepare_document(actor=self.doc, visit_id=self.v.pk)
        a, _ = documents.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        b, replay = documents.confirm_document(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        self.assertEqual(a.pk,b.pk); self.assertTrue(replay); self.assertEqual(ClinicalDocumentVersion.objects.count(), 2)
        self.assertEqual(ArchiveEvent.objects.filter(action='AMENDMENT_APPLIED').count(), 1)

    def test_new_visit_does_not_require_unlocking_old_archives(self):
        self.fixed(); visit = self.another(); self.close_care(visit); self.save(visit)
        row = self.confirm_doc(visit)
        self.assertEqual(row.document.encounter.visit_id, visit.pk)
        self.assertEqual(ArchivePackage.objects.count(), 1)

    def test_withdraw_pending_submission_keeps_sources_and_allows_new_request(self):
        self.ready(); row = self.submit_archive(); original = row.snapshot
        p = archives.prepare_action(actor=self.doc, submission_id=row.pk, action='WITHDRAW', reason='核对后撤回本次未完成申请。')
        archives.confirm_action(actor=self.doc, proposal_token=p['proposal_token'], confirmed=True)
        row.refresh_from_db(); self.assertEqual(row.state, 'STALE'); self.assertEqual(row.snapshot, original)
        self.assertEqual(self.submit_archive().number, 2)

    def test_concurrent_reviews_commit_one_result(self):
        self.ready(); row = self.submit_archive(); context = self.reviewer._adc_workspace; barrier = Barrier(2)
        tokens = [archives.prepare_review(actor=self.reviewer, submission_id=row.pk, decision='APPROVE', note='独立审核准确来源，无重复处理。')['proposal_token'] for _ in range(2)]
        def work(token):
            close_old_connections(); actor = UserAccount.objects.get(pk=self.reviewer.pk); actor._adc_workspace = context
            barrier.wait()
            try: archives.confirm_review(actor=actor, proposal_token=token, confirmed=True); return 'saved'
            except RuleError: return 'stale'
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool: result = list(pool.map(work,tokens))
        self.assertCountEqual(result,['saved','stale']); self.assertEqual(ArchiveEvent.objects.filter(action='REVIEW').count(),1)

    def test_archived_document_page_reports_actual_version_status(self):
        self.fixed(); client=WorkspaceClient(); client.force_login(self.doc)
        r=client.get(reverse('clinical_document', args=[self.v.pk]))
        self.assertEqual(r.status_code,200); self.assertContains(r,'本准确版本已有完整归档固定包')
        self.assertNotContains(r,'本版本尚未办理病案归档')

    def test_revoked_scope_removes_assigned_review_queue(self):
        self.ready(); self.submit_archive()
        self.assertEqual(queries.worklist(self.reviewer)['reviews'].count(),1)
        self.decide(self.review_scope,'REVOKE',actor=self.doc); self.ctx(self.reviewer,'DENTIST')
        self.assertEqual(queries.worklist(self.reviewer)['reviews'].count(),0)

    def test_finance_and_headquarters_do_not_gain_medical_body(self):
        self.fixed()
        for role in ('FINANCE','HQ'):
            user=UserAccount.objects.create_user(username='archive_'+role.lower())
            RoleAssignment.objects.create(user=user,role=role,scope_kind='CHAIN')
            self.ctx(user,role)
            with self.assertRaises(PermissionDenied): queries.details(user,self.v.pk)
