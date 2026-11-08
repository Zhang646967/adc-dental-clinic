"""C4.1 scenarios through staff HTTP and real PostgreSQL connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import RoleAssignment, UserAccount
from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent, Invoice, TreatmentRecord
from care.services import review_allergies
from clinical import encounters, prescriptions
from clinical.prescription_models import Prescription, PrescriptionCatalogueItem, PrescriptionDecision, PrescriptionDuty, PrescriptionVersion
from finance.cash_models import CashEntry
from registry.models import Allergy
from tests.test_clinical_authority import AuthorityFixture
from tests.workspace_client import WorkspaceClient
from workspaces.context import available_roles
from workspaces.models import WorkspaceContext


class PrescriptionFixture(AuthorityFixture):
    def setup_prescription_fixture(self):
        self.setup_authority()
        self.authorize()
        self.visit = self.checked_visit()
        self.rx_user = UserAccount.objects.create_user(username='synthetic_rx', password='synthetic-rx-test-123')
        self.configure('provision', '--prescriber', self.doc.username, '--pharmacist', self.rx_user.username)
        self.ctx(self.rx_user, 'PHARMACIST', self.a)
        head = encounters.start_encounter(actor=self.doc, visit_id=self.visit.pk,
            expected_visit_version=self.visit.lock_version, operation_id=uuid4())[0]
        encounters.change_draft(actor=self.doc, visit_id=self.visit.pk, expected_revision=head.revision,
            operation_id=uuid4(), action='NOTES', fields=dict(
                chief_complaint='课程合成主诉', examination='PRIVATE_EXAMINATION_NOT_FOR_PHARMACY',
                history_review='UNAVAILABLE', history_id=None, history_discrepancy='',
                history_assessment='面谈自述尚未知，待核对。', dentition='PERMANENT',
                observed_at=timezone.now().isoformat(),
            ))
        preview = encounters.prepare_record(actor=self.doc, visit_id=self.visit.pk)
        encounters.confirm_record(actor=self.doc, proposal_token=preview['proposal_token'], confirmed=True)
        self.record = prescriptions.current_record(self.visit)
        self.items = list(PrescriptionCatalogueItem.objects.filter(clinic=self.a))
        self.review_confirmed_allergies('NO_KNOWN')

    def review_confirmed_allergies(self, status, allergy_ids=()):
        self.visit.refresh_from_db()
        review_allergies(actor=self.doc, visit_id=self.visit.pk, expected_version=self.visit.lock_version,
                         patient_version=self.visit.patient.allergy_info_version, status=status, allergy_ids=allergy_ids)
        self.visit.refresh_from_db()

    def configure(self, *args):
        return call_command('configure_prescription_rehearsal', '--synthetic-only', '--operator', self.tech.username,
                            '--clinic', self.a.clinic_code, *args, stdout=StringIO())

    def rows(self):
        return [dict(item_id=self.items[0].pk, dose='1.125', frequency=1, days=2, quantity=2)]

    def submit(self, previous=None, entries=None):
        _, token = prescriptions.prepare_submit(self.doc, self.visit, self.record.pk, previous,
                                               '课程合成开方依据', self.rows() if entries is None else entries)
        return prescriptions.confirm(self.doc, token, True)[0]


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_PRESCRIPTION_REHEARSAL=True)
class PrescriptionReviewTests(PrescriptionFixture, TransactionTestCase):
    def setUp(self):
        self.setup_prescription_fixture()

    def login(self, user, password):
        client = Client(enforce_csrf_checks=True)
        login_url = reverse('login')
        client.get(login_url)
        response = client.post(login_url, dict(username=user.username, password=password,
                                               csrfmiddlewaretoken=client.cookies['csrftoken'].value))
        self.assertEqual(response.status_code, 302)
        return client, client.get(response.url)

    def post(self, client, route, from_page, fields, expected=200):
        result = client.post(route, {
            'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
            'workspace_token': from_page.context['workspace_token_value'],
            **fields,
        })
        self.assertEqual(result.status_code, expected)
        return result

    def confirm_page(self, client, preview):
        self.assertContains(preview, '核对处方办理')
        return self.post(client, reverse('prescription_confirm'), preview, {
            'proposal_token': preview.context['form'].initial['proposal_token'], 'confirmed': 'on',
        }, 302)

    def compose(self, client, page, *, initial=False):
        fields = page.context['form'].initial
        values = dict(fields, indication='课程合成开方依据', **{
            'items-TOTAL_FORMS': 5, 'items-INITIAL_FORMS': 2 if initial else 0,
            'items-0-item': self.items[0].pk, 'items-0-dose': '1.125',
            'items-0-frequency': 1, 'items-0-days': 2, 'items-0-quantity': 2,
        })
        if initial:
            values['items-1-DELETE'] = 'on'
        else:
            values.update({
                'items-1-item': self.items[1].pk, 'items-1-dose': '2',
                'items-1-frequency': 1, 'items-1-days': 2, 'items-1-quantity': 4,
            })
        values['previous'] = values['previous'] or ''
        return self.post(client, reverse('prescription_visit', args=[self.visit.pk]), page, values)

    def test_normal_staff_paths_return_revision_then_approve(self):
        doctor, _ = self.login(self.doc, 'synthetic-pass-123')
        encounter = doctor.get(reverse('clinical_encounter', args=[self.visit.pk]))
        self.assertContains(encounter, '办理本次处方')
        opening = reverse('prescription_visit', args=[self.visit.pk])
        draft = doctor.get(opening)
        preview = self.compose(doctor, draft)
        self.assertEqual(PrescriptionVersion.objects.count(), 0)
        first = self.confirm_page(doctor, preview)
        self.assertEqual(self.confirm_page(doctor, preview).url, first.url)
        self.assertContains(doctor.get(first.url), '待审核')

        reviewer, choice = self.login(self.rx_user, 'synthetic-rx-test-123')
        self.assertContains(choice, '请选择本次要处理的诊所')
        queue = self.post(reviewer, reverse('activate_clinic'), choice, {'clinic': self.a.pk}, 302)
        self.assertContains(reviewer.get(queue.url), '处方 #')
        old = reviewer.get(first.url)
        self.assertNotContains(old, 'PRIVATE_EXAMINATION_NOT_FOR_PHARMACY')
        prior = old.context['version']
        returned = self.post(reviewer, first.url, old, dict(
            version_id=prior.pk, action='RETURNED', reason='请重新核对合成依据。',
        ))
        self.confirm_page(reviewer, returned)
        self.assertContains(doctor.get(first.url), '已退回修改')

        revision = self.compose(doctor, doctor.get(opening), initial=True)
        second = self.confirm_page(doctor, revision)
        new = reviewer.get(second.url)
        self.assertContains(new, '第 2 版')
        approved = self.post(reviewer, second.url, new, dict(
            version_id=new.context['version'].pk, action='APPROVED', reason='已逐项核对合成处方。',
        ))
        self.confirm_page(reviewer, approved)
        self.assertContains(doctor.get(second.url), '审核通过')
        self.assertContains(doctor.get(first.url), '历史版本')
        self.assertEqual(list(PrescriptionVersion.objects.order_by('number').values_list('number', 'decision__action')),
                         [(1, 'RETURNED'), (2, 'APPROVED')])
        self.assertEqual([len(row.items) for row in PrescriptionVersion.objects.order_by('number')], [2, 1])
        self.assertEqual(AuditEvent.objects.filter(event_type='PRESCRIPTION_SUBMITTED').count(), 2)
        self.assertEqual(AuditEvent.objects.filter(event_type='PRESCRIPTION_DECIDED').count(), 2)
        self.assertFalse(Invoice.objects.exists() or CashEntry.objects.exists() or TreatmentRecord.objects.exists())

    def test_cross_clinic_front_desk_and_self_review_denied(self):
        version = self.submit()
        path = reverse('prescription_detail', args=[version.prescription_id])
        outsider = UserAccount.objects.create_user(username='rx_other_clinic')
        RoleAssignment.objects.create(user=outsider, clinic=self.b, role='PHARMACIST', scope_kind='CLINIC')
        PrescriptionDuty.objects.create(user=outsider, clinic=self.b, kind='REVIEW', reference='SYNTHETIC',
                                        valid_from=timezone.now() - timedelta(days=1),
                                        valid_until=timezone.now() + timedelta(days=1))
        other = WorkspaceClient()
        other.force_login(outsider)
        self.assertEqual(other.get(path).status_code, 404)
        self.assertNotContains(other.get(reverse('prescription_review_queue')), '处方 #')
        front = WorkspaceClient()
        front.force_login(self.front)
        self.assertEqual(front.get(path).status_code, 403)
        self.assertEqual(front.get(reverse('prescription_review_queue')).status_code, 403)
        pharmacist_client = WorkspaceClient()
        pharmacist_client.force_login(self.rx_user)
        self.assertEqual(pharmacist_client.get(reverse('clinical_encounter', args=[self.visit.pk])).status_code, 403)
        RoleAssignment.objects.create(user=self.doc, clinic=self.a, role='PHARMACIST', scope_kind='CLINIC')
        PrescriptionDuty.objects.create(user=self.doc, clinic=self.a, kind='REVIEW', reference='SYNTHETIC',
                                        valid_from=timezone.now() - timedelta(days=1),
                                        valid_until=timezone.now() + timedelta(days=1))
        self.ctx(self.doc, 'PHARMACIST', self.a)
        with self.assertRaisesMessage(PermissionDenied, '独立审核'):
            prescriptions.prepare_decision(self.doc, version, 'APPROVED', '不能自审')
        self.assertFalse(PrescriptionDecision.objects.exists())

    def test_revoked_reissued_and_expired_duties_reject_old_confirmation(self):
        version = self.submit()
        _, approval = prescriptions.prepare_decision(self.rx_user, version, 'APPROVED', '合成审核')
        self.configure('revoke', '--user', self.rx_user.username, '--duty', 'REVIEW')
        with self.assertRaises(PermissionDenied):
            prescriptions.confirm(self.rx_user, approval, True)
        self.configure('provision', '--prescriber', self.doc.username, '--pharmacist', self.rx_user.username)
        with self.assertRaisesMessage(RuleError, '职责已变化'):
            prescriptions.confirm(self.rx_user, approval, True)
        now = timezone.now()
        PrescriptionDuty.objects.filter(user=self.rx_user, revoked_at__isnull=True).update(
            valid_from=now - timedelta(days=2), valid_until=now - timedelta(days=1),
        )
        self.assertNotIn('PHARMACIST', available_roles(self.rx_user))
        self.assertFalse(PrescriptionDecision.objects.exists())

    def test_updated_history_blocks_approval_and_allows_return(self):
        version = self.submit()
        _, approval = prescriptions.prepare_decision(self.rx_user, version, 'APPROVED', '合成审核')
        encounters.submit_history(actor=self.doc, visit_id=self.visit.pk, expected_revision=0, operation_id=uuid4(),
            confirmed=True, fields=dict(
                medical_status='UNKNOWN', medical_history='', medication_status='UNKNOWN', medications='',
                allergy_status='REPORTED', reported_allergies='合成补充过敏自述',
            ))
        with self.assertRaisesMessage(RuleError, '自述资料已有更新'):
            prescriptions.confirm(self.rx_user, approval, True)
        _, returned = prescriptions.prepare_decision(self.rx_user, version, 'RETURNED', '请核对补充自述。')
        prescriptions.confirm(self.rx_user, returned, True)
        self.assertEqual(PrescriptionDecision.objects.get().action, 'RETURNED')

    def test_confirmed_allergy_change_requires_new_prescription_before_approval(self):
        self.review_confirmed_allergies('UNKNOWN')
        with self.assertRaisesMessage(RuleError, '复核当前过敏资料'):
            self.submit()
        self.review_confirmed_allergies('NO_KNOWN')
        version = self.submit()
        _, approval = prescriptions.prepare_decision(self.rx_user, version, 'APPROVED', '合成审核')

        allergy = Allergy.objects.create(code='C41-VERIFIED', name='新核实合成过敏条目')
        self.review_confirmed_allergies('KNOWN', [allergy.pk])
        self.assertEqual(prescriptions.current_record(self.visit).pk, version.record_id)
        with self.assertRaisesMessage(RuleError, '医师核实过敏资料缺失或已变化'):
            prescriptions.confirm(self.rx_user, approval, True)
        self.assertFalse(PrescriptionDecision.objects.exists())

        _, returned = prescriptions.prepare_decision(self.rx_user, version, 'RETURNED', '请核对新资料。')
        prescriptions.confirm(self.rx_user, returned, True)
        revised = self.submit(previous=version.pk)
        pharmacy = WorkspaceClient()
        pharmacy.force_login(self.rx_user)
        self.assertContains(pharmacy.get(reverse('prescription_detail', args=[revised.prescription_id])), allergy.name)
        _, approval = prescriptions.prepare_decision(self.rx_user, revised, 'APPROVED', '核对后重新审方')
        prescriptions.confirm(self.rx_user, approval, True)
        self.assertEqual(list(PrescriptionDecision.objects.order_by('pk').values_list('action', flat=True)),
                         ['RETURNED', 'APPROVED'])

    def test_legacy_pending_prescription_is_readable_and_can_be_returned(self):
        def emit_legacy_receipt(actor, event_type, subject, **kwargs):
            kwargs['summary'] = {'version': subject.number}
            return emit(actor, event_type, subject, **kwargs)

        with patch.object(prescriptions, 'emit', side_effect=emit_legacy_receipt):
            legacy = self.submit()
        pharmacy = WorkspaceClient()
        pharmacy.force_login(self.rx_user)
        self.assertContains(pharmacy.get(reverse('prescription_detail', args=[legacy.prescription_id])), '待审核')
        with self.assertRaisesMessage(RuleError, '医师核实过敏资料缺失或已变化'):
            prescriptions.prepare_decision(self.rx_user, legacy, 'APPROVED', '旧版本无绑定依据')
        _, returned = prescriptions.prepare_decision(self.rx_user, legacy, 'RETURNED', '请重新核对过敏资料。')
        prescriptions.confirm(self.rx_user, returned, True)
        self.assertEqual(PrescriptionDecision.objects.get().action, 'RETURNED')

    def test_withdrawal_and_new_version_reject_old_proposal(self):
        version = self.submit()
        _, approval = prescriptions.prepare_decision(self.rx_user, version, 'APPROVED', '合成审核')
        _, withdrawal = prescriptions.prepare_decision(self.doc, version, 'WITHDRAWN', '重新核对合成处方')
        prescriptions.confirm(self.doc, withdrawal, True)
        second = self.submit(previous=version.pk)
        self.assertEqual(second.number, 2)
        with self.assertRaisesMessage(RuleError, '已有办理结果'):
            prescriptions.confirm(self.rx_user, approval, True)
        self.assertEqual(PrescriptionDecision.objects.get().action, 'WITHDRAWN')

    def test_workspace_revision_invalidates_old_confirmation(self):
        version = self.submit()
        _, approval = prescriptions.prepare_decision(self.rx_user, version, 'APPROVED', '合成审核')
        ctx = self.rx_user._adc_workspace
        WorkspaceContext.objects.filter(pk=ctx.pk).update(revision=ctx.revision + 1)
        ctx.refresh_from_db()
        with self.assertRaisesMessage(RuleError, '重新预览'):
            prescriptions.confirm(self.rx_user, approval, True)
        self.assertFalse(PrescriptionDecision.objects.exists())

    def test_foreign_catalogue_and_invalid_dose_rejected_without_creating_case(self):
        other = PrescriptionCatalogueItem.objects.create(
            clinic=self.b, code='SYNTHETIC-OTHER', name='合成条目', strength='演练',
            dose_unit='份', quantity_unit='份', route='LOCAL',
        )
        for changes in ({'item_id': other.pk}, {'dose': 'NaN'}, {'dose': '-1'}, {'quantity': 0}):
            with self.subTest(changes=changes), self.assertRaises(RuleError):
                self.submit(entries=[dict(self.rows()[0], **changes)])
        self.assertFalse(Prescription.objects.exists())

    def test_two_postgresql_connections_keep_exactly_one_decision(self):
        version = self.submit()
        second = UserAccount.objects.create_user(username='rx_independent_second')
        self.configure('provision', '--prescriber', self.doc.username, '--pharmacist', second.username)
        self.ctx(second, 'PHARMACIST', self.a)
        contenders = [(self.rx_user, 'APPROVED'), (second, 'RETURNED')]
        prepared = [
            (u.pk, u._adc_workspace.pk, prescriptions.prepare_decision(u, version, action, '合成依据')[1])
            for u, action in contenders
        ]
        barrier = Barrier(2)

        def commit(entry):
            close_old_connections()
            try:
                user_id, workspace_id, token = entry
                user = UserAccount.objects.get(pk=user_id)
                user._adc_workspace = WorkspaceContext.objects.get(pk=workspace_id)
                barrier.wait(timeout=10)
                prescriptions.confirm(user, token, True)
                return 'saved'
            except RuleError:
                return 'stale'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(commit, prepared)), ['saved', 'stale'])
        self.assertEqual(PrescriptionDecision.objects.filter(version=version).count(), 1)

    def test_postgresql_retains_versions_decisions_and_independent_actor(self):
        version = self.submit()
        with self.assertRaises(DatabaseError), transaction.atomic():
            PrescriptionDecision.objects.create(version=version, actor=self.doc, duty=version.prescriber_duty,
                                               action='APPROVED', reason='错误的自审', operation_id=uuid4())
        _, approval = prescriptions.prepare_decision(self.rx_user, version, 'APPROVED', '合成审核')
        prescriptions.confirm(self.rx_user, approval, True)
        for mutate in (
            lambda: PrescriptionVersion.objects.filter(pk=version.pk).update(indication='覆盖旧版本'),
            lambda: PrescriptionDecision.objects.filter(version=version).update(reason='覆盖旧审核'),
        ):
            with self.assertRaises(DatabaseError), transaction.atomic():
                mutate()

    def test_populated_prescription_database_refuses_reverse(self):
        version = self.submit()
        executor = MigrationExecutor(connection)
        latest = executor.loader.graph.leaf_nodes()
        try:
            with self.assertRaisesMessage(RuntimeError, 'reversing the prescription schema is refused'):
                executor.migrate([('clinical', '0017_c41_prescriptions')])
            self.assertTrue(PrescriptionVersion.objects.filter(pk=version.pk).exists())
            self.assertIn(('clinical', '0018_c41_prescription_guards'),
                          MigrationExecutor(connection).loader.applied_migrations)
        finally:
            MigrationExecutor(connection).migrate(latest)

    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_non_synthetic_configuration_disables_pharmacy_and_entry(self):
        self.assertNotIn('PHARMACIST', available_roles(self.rx_user))
        doctor = WorkspaceClient()
        doctor.force_login(self.doc)
        self.assertEqual(doctor.get(reverse('prescription_visit', args=[self.visit.pk])).status_code, 404)
