"""Actual PostgreSQL permissions, retained source, review and concurrent decisions."""
import hashlib
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import DatabaseError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice, TreatmentRecord
from finance.cash_models import CashEntry
from insurance import services, selectors, catalogue_source
from insurance.forms import MappingForm
from insurance.models import PolicyCatalogue, PolicyItem, ClinicArrangement, FeeMapping, EligibilityFact, InsuranceEvent
from patients.models import Patient
from registry.models import TreatmentType
from scheduling.models import Visit
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext


class InsuranceFixtureMixin(FixtureMixin):
    def setUp(self):
        self.make_fixture()
        for user, role, clinic in [(self.front, 'FRONT_DESK', self.a), (self.front2, 'FRONT_DESK', self.a), (self.manager, 'MANAGER', self.a)]:
            user._adc_workspace = WorkspaceContext.objects.create(user=user, role=role, clinic=clinic)
        self.f1 = self.finance('insurance-finance-one'); self.f2 = self.finance('insurance-finance-two')
        self.today = timezone.localdate(); self.end = self.today + timedelta(days=30)
        self.fee = TreatmentType.objects.create(code='INS-FEE', name='合成目录适配项目', unit_definition='每牙', standard_unit_price=100)

    def finance(self, name):
        user = UserAccount.objects.create_user(username=name, password='isolated-test-password-123')
        RoleAssignment.objects.create(user=user, role='FINANCE', scope_kind='CHAIN')
        user._adc_workspace = WorkspaceContext.objects.create(user=user, role='FINANCE')
        return user

    def create(self, preview, actor):
        return services.confirm_preparation(actor=actor, proposal_token=preview['proposal_token'], confirmed=True)[0]

    def catalogue(self, publish=True):
        row = self.create(services.prepare_catalogue(actor=self.f1), self.f1)
        if publish:
            self.review(row, 'catalogue')
            row.refresh_from_db()
        return row

    def review(self, row, kind, actor=None, decision='approve'):
        actor = actor or self.f2
        p = services.prepare_review(actor=actor, kind=kind, pk=row.pk, decision=decision, reason='合成资料逐项核对')
        return services.confirm_review(actor=actor, proposal_token=p['proposal_token'], confirmed=True)[0]

    def arrangement(self, catalogue=None, publish=True, **kw):
        catalogue = catalogue or self.catalogue()
        d = dict(actor=self.manager, catalogue_id=catalogue.pk, starts_on=self.today, ends_on=self.end, reference='SIM-ARRANGEMENT')
        d.update(kw); row = self.create(services.prepare_arrangement(**d), self.manager)
        if publish:
            self.review(row, 'arrangement'); row.refresh_from_db()
        return row

    def mapping(self, catalogue=None, item=None, publish=True):
        catalogue = catalogue or self.catalogue()
        item = item or catalogue.items.filter(payment_class='A', unit__isnull=False).first()
        p = services.prepare_mapping(actor=self.manager, treatment_type_id=self.fee.pk, policy_item_id=item.pk,
            policy_units_per_fee='1', compatibility_basis='合成收费项目和目录项目的含义及单位经人工逐项核对，一对一。')
        row = self.create(p, self.manager)
        if publish:
            self.review(row, 'mapping'); row.refresh_from_db()
        return row

    def eligibility_preview(self, **kw):
        d = dict(actor=self.front, patient_id=self.p1.pk, insured_region='CN-43', scheme='EMPLOYEE', state='VERIFIED',
                 starts_on=self.today, ends_on=self.end, reference='SIM-ELIGIBILITY', basis='合成场景资料核对，不代表真实医保待遇。')
        d.update(kw); return services.prepare_eligibility(**d)

    def disable(self, row, kind, actor=None):
        actor = actor or self.f2
        p = services.prepare_disable(actor=actor, kind=kind, pk=row.pk, reason='课程版本停用，原事实保留')
        return services.confirm_disable(actor=actor, proposal_token=p['proposal_token'], confirmed=True)[0]


@override_settings(ADC_CLINICAL_SYNTHETIC=True, ADC_READ_ONLY=False)
class InsurancePreparationTests(InsuranceFixtureMixin, TransactionTestCase):
    def test_catalogue_retains_source_bytes_all_rows_and_exact_duplicates(self):
        row = self.catalogue(False)
        raw, data = catalogue_source.load_source(catalogue_source.SOURCE_KEY)
        self.assertEqual(bytes(row.original_bytes), raw)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), row.source_digest)
        self.assertEqual(row.normalized_rows, data['items'])
        self.assertEqual(row.items.count(), 202); self.assertEqual(row.source_summary['physical_rows'], 232)
        self.assertEqual(row.source_summary['identical_extra_rows'], 30); self.assertEqual(row.state, 'DRAFT')

    def test_source_unknown_classification_and_two_missing_units_remain_missing(self):
        row = self.catalogue()
        unknown = row.items.get(code='013105010310000')
        self.assertEqual(unknown.payment_class, 'UNKNOWN'); self.assertIsNone(unknown.pre_self_pay_percent)
        self.assertEqual(row.items.filter(unit__isnull=True).count(), 2)
        self.assertEqual(row.items.filter(payment_class='A').count(), 65)

    def test_import_preview_has_no_database_effect(self):
        services.prepare_catalogue(actor=self.f1)
        self.assertFalse(PolicyCatalogue.objects.exists()); self.assertFalse(PolicyItem.objects.exists())

    def test_raw_or_normalized_asset_changes_reject_entire_import(self):
        with tempfile.TemporaryDirectory() as folder:
            for name in ['hunan-oral-2026.json', 'hunan-oral-2026.word.bin']:
                shutil.copy(catalogue_source.PACKAGE / name, Path(folder) / name)
            p = Path(folder) / 'hunan-oral-2026.json'; d = json.loads(p.read_text()); d['items'][0]['unit'] = '伪造单位'; p.write_text(json.dumps(d))
            with patch.object(catalogue_source, 'PACKAGE', Path(folder)), self.assertRaises(RuleError):
                services.prepare_catalogue(actor=self.f1)
            shutil.copy(catalogue_source.PACKAGE / 'hunan-oral-2026.json', p)
            raw = Path(folder) / 'hunan-oral-2026.word.bin'; raw.write_bytes(raw.read_bytes() + b'changed')
            with patch.object(catalogue_source, 'PACKAGE', Path(folder)), self.assertRaises(RuleError):
                services.prepare_catalogue(actor=self.f1)
        self.assertFalse(PolicyCatalogue.objects.exists()); self.assertFalse(PolicyItem.objects.exists())

    def test_duplicate_source_is_reported_and_same_operation_replays(self):
        p = services.prepare_catalogue(actor=self.f1); row = self.create(p, self.f1)
        replay, repeated = services.confirm_preparation(actor=self.f1, proposal_token=p['proposal_token'], confirmed=True)
        self.assertEqual(replay.pk, row.pk); self.assertTrue(repeated)
        with self.assertRaisesMessage(RuleError, '已保留'):
            services.prepare_catalogue(actor=self.f2)
        self.assertEqual(PolicyCatalogue.objects.count(), 1); self.assertEqual(PolicyItem.objects.count(), 202)

    def test_import_requires_finance_and_publication_requires_different_account(self):
        with self.assertRaises(PermissionDenied): services.prepare_catalogue(actor=self.manager)
        row = self.catalogue(False)
        with self.assertRaises(PermissionDenied): self.review(row, 'catalogue', actor=self.f1)
        self.review(row, 'catalogue'); row.refresh_from_db(); self.assertEqual(row.state, 'CONFIRMED')

    def test_rejected_source_can_be_explicitly_resubmitted_without_fabricating_policy(self):
        old = self.catalogue(False); self.review(old, 'catalogue', decision='reject')
        p = services.prepare_catalogue(actor=self.f1, previous_id=old.pk, reason='已核对前次未通过事项，重新提交原来源')
        row = self.create(p, self.f1); self.assertEqual(row.review_attempt, 2); self.assertEqual(row.previous_id, old.pk)
        self.assertEqual(bytes(row.original_bytes), bytes(old.original_bytes)); self.assertEqual(row.normalized_rows, old.normalized_rows)
        self.assertEqual(row.version_code, old.version_code); self.review(row, 'catalogue')
        old.refresh_from_db(); self.assertEqual(old.state, 'REJECTED'); self.assertEqual(old.events.filter(action='REVIEW').count(), 1)

    def test_disabled_source_retry_does_not_revive_previous_arrangement(self):
        old = self.catalogue(); arrangement = self.arrangement(old); self.disable(old, 'catalogue')
        row = self.create(services.prepare_catalogue(actor=self.f1, previous_id=old.pk, reason='课程继续使用，重新核对原政策来源'), self.f1)
        self.review(row, 'catalogue'); arrangement.refresh_from_db()
        self.assertEqual(arrangement.catalogue_id, old.pk); self.assertIsNone(selectors.dashboard(self.front)['active_arrangement'])

    def test_resubmission_requires_latest_terminal_source_and_unique_attempt(self):
        old = self.catalogue()
        with self.assertRaises(RuleError): services.prepare_catalogue(actor=self.f1, previous_id=old.pk, reason='未停用不能重复发布')
        self.disable(old, 'catalogue')
        p = services.prepare_catalogue(actor=self.f1, previous_id=old.pk, reason='原来源重新核对')
        self.create(p, self.f1)
        with self.assertRaises(RuleError): services.prepare_catalogue(actor=self.f2, previous_id=old.pk, reason='不能跳过最新核对')
        self.assertEqual(PolicyCatalogue.objects.count(), 2)

    def test_departed_original_importer_does_not_block_new_account_resubmission(self):
        old = self.catalogue(False); self.review(old, 'catalogue', decision='reject')
        RoleAssignment.objects.filter(user=self.f1, role='FINANCE').update(is_active=False)
        row = self.create(services.prepare_catalogue(actor=self.f2, previous_id=old.pk, reason='现任财务接续原未通过资料'), self.f2)
        self.review(row, 'catalogue', actor=self.finance('current-independent-finance'))
        row.refresh_from_db(); self.assertEqual(row.state, 'CONFIRMED'); self.assertEqual(row.prepared_by_id, self.f2.pk)

    def test_database_rejects_skipped_review_attempt_chain(self):
        row = self.catalogue(False); self.review(row, 'catalogue', decision='reject')
        data = dict(PolicyCatalogue.objects.values().get(pk=row.pk)); data.pop('id')
        data.update(previous_id=row.pk, review_attempt=3, state='DRAFT', revision=0, reviewed_by_id=None, reviewed_at=None, review_reason='')
        with self.assertRaises(DatabaseError), transaction.atomic(): PolicyCatalogue.objects.create(**data)

    def test_revoked_preparer_cannot_have_catalogue_approved_but_can_be_rejected(self):
        row = self.catalogue(False)
        RoleAssignment.objects.filter(user=self.f1, role='FINANCE').update(is_active=False)
        with self.assertRaises(RuleError): self.review(row, 'catalogue')
        self.review(row, 'catalogue', decision='reject'); row.refresh_from_db(); self.assertEqual(row.state, 'REJECTED')

    def test_revoked_reviewer_after_preview_has_no_effect(self):
        row = self.catalogue(False)
        p = services.prepare_review(actor=self.f2, kind='catalogue', pk=row.pk, decision='approve', reason='合成复核依据')
        RoleAssignment.objects.filter(user=self.f2, role='FINANCE').update(is_active=False)
        with self.assertRaises(PermissionDenied): services.confirm_review(actor=self.f2, proposal_token=p['proposal_token'], confirmed=True)
        row.refresh_from_db(); self.assertEqual(row.state, 'DRAFT')

    def test_stale_review_does_not_overwrite_completed_decision(self):
        row = self.catalogue(False)
        p = services.prepare_review(actor=self.f2, kind='catalogue', pk=row.pk, decision='approve', reason='合成复核依据')
        self.review(row, 'catalogue', decision='reject')
        with self.assertRaises(RuleError): services.confirm_review(actor=self.f2, proposal_token=p['proposal_token'], confirmed=True)

    def test_draft_or_disabled_catalogue_cannot_prepare_arrangements(self):
        row = self.catalogue(False)
        with self.assertRaises(RuleError): self.arrangement(row)
        self.review(row, 'catalogue'); self.disable(row, 'catalogue')
        with self.assertRaises(RuleError): self.arrangement(row)

    def test_arrangement_dates_cannot_precede_policy_or_reverse(self):
        row = self.catalogue()
        for start, end in [('2026-05-31', '2026-06-03'), ('2026-08-02', '2026-08-01')]:
            with self.assertRaises(RuleError): self.arrangement(row, starts_on=start, ends_on=end)

    def test_arrangement_has_independent_review_and_inclusive_date_range(self):
        row = self.arrangement()
        self.assertNotEqual(row.prepared_by_id, row.reviewed_by_id)
        other = self.arrangement(row.catalogue, publish=False, starts_on=self.end, ends_on=self.end + timedelta(days=1))
        with self.assertRaises(RuleError): self.review(other, 'arrangement')
        future = self.arrangement(row.catalogue, starts_on=self.end + timedelta(days=1), ends_on=self.end + timedelta(days=5))
        self.assertEqual(future.state, 'CONFIRMED')

    def test_database_rejects_overlapping_confirmed_arrangements(self):
        row = self.arrangement(); other = self.arrangement(row.catalogue, publish=False)
        with self.assertRaises(DatabaseError), transaction.atomic():
            ClinicArrangement.objects.filter(pk=other.pk).update(state='CONFIRMED', revision=1, reviewed_by=self.f2,
                reviewed_at=timezone.now(), review_reason='试图绕过命令形成重复占用')

    def test_manager_cannot_read_or_disable_other_clinic_preparation(self):
        row = self.arrangement(publish=False)
        self.manager._adc_workspace.clinic = self.b; self.manager._adc_workspace.save(update_fields=['clinic'])
        RoleAssignment.objects.create(user=self.manager, role='MANAGER', scope_kind='CLINIC', clinic=self.b)
        with self.assertRaises(ObjectDoesNotExist): services.reviewed_subject(self.manager, 'arrangement', row.pk)
        self.assertEqual(selectors.dashboard(self.manager)['counts']['arrangements'], 0)

    def test_arrangement_history_remains_reachable_after_twenty_rows(self):
        cat = self.catalogue()
        rows = [self.arrangement(cat, publish=False, reference=f'SIM-PAGE-{n}') for n in range(21)]
        first = selectors.dashboard(self.manager); older = selectors.dashboard(self.manager, arrangements_page=2)
        self.assertEqual(first['counts']['arrangements'], 21); self.assertEqual(len(first['arrangements']), 20)
        self.assertEqual([r.pk for r in older['arrangements']], [rows[0].pk]); self.assertEqual(older['arrangements_page'].paginator.num_pages, 2)

    def test_manager_cannot_self_review_by_changing_role(self):
        row = self.arrangement(publish=False)
        RoleAssignment.objects.create(user=self.manager, role='FINANCE', scope_kind='CHAIN')
        self.manager._adc_workspace.role = 'FINANCE'; self.manager._adc_workspace.clinic = None
        self.manager._adc_workspace.save(update_fields=['role', 'clinic'])
        with self.assertRaises(PermissionDenied): self.review(row, 'arrangement', actor=self.manager)

    def test_catalogue_disabled_after_arrangement_preview_invalidates_confirmation(self):
        cat = self.catalogue()
        p = services.prepare_arrangement(actor=self.manager, catalogue_id=cat.pk, starts_on=self.today, ends_on=self.end, reference='SIM-STILL-DRAFT')
        self.disable(cat, 'catalogue')
        with self.assertRaises(RuleError): self.create(p, self.manager)
        self.assertFalse(ClinicArrangement.objects.exists())

    def test_stale_preparation_can_be_rejected_after_catalogue_disabled(self):
        row = self.arrangement(publish=False)
        self.disable(row.catalogue, 'catalogue')
        self.review(row, 'arrangement', decision='reject'); row.refresh_from_db(); self.assertEqual(row.state, 'REJECTED')

    def test_fee_mapping_retains_units_without_changing_fee_price(self):
        row = self.mapping()
        self.fee.refresh_from_db(); self.assertEqual(self.fee.standard_unit_price, 100)
        self.assertEqual(row.fee_snapshot['unit'], '每牙'); self.assertEqual(row.policy_units_per_fee, 1)

    def test_missing_policy_unit_or_rule_keeps_mapping_awaiting_review(self):
        cat = self.catalogue()
        for item in [cat.items.filter(unit__isnull=True).first(), cat.items.get(payment_class='UNKNOWN')]:
            row = self.mapping(cat, item, publish=False)
            with self.assertRaisesMessage(RuleError, '缺失'): self.review(row, 'mapping')
            row.refresh_from_db(); self.assertEqual(row.state, 'DRAFT')

    def test_nonpayable_mapping_is_explicit_not_a_fund_entitlement(self):
        cat = self.catalogue(); row = self.mapping(cat, cat.items.filter(payment_class='NOT_PAYABLE', unit__isnull=False).first())
        self.assertEqual(row.state, 'CONFIRMED'); self.assertFalse(Invoice.objects.exists()); self.assertFalse(CashEntry.objects.exists())

    def test_fee_change_after_mapping_preview_rejects_confirmation(self):
        cat = self.catalogue(); item = cat.items.filter(payment_class='A').first()
        p = services.prepare_mapping(actor=self.manager, treatment_type_id=self.fee.pk, policy_item_id=item.pk,
            policy_units_per_fee='1', compatibility_basis='合成单位已核对')
        TreatmentType.objects.filter(pk=self.fee.pk).update(unit_definition='每次')
        with self.assertRaises(RuleError): self.create(p, self.manager)
        self.assertFalse(FeeMapping.objects.exists())

    def test_fee_change_before_review_or_after_activation_is_visible(self):
        row = self.mapping(publish=False)
        TreatmentType.objects.filter(pk=self.fee.pk).update(unit_definition='每次')
        with self.assertRaises(RuleError): self.review(row, 'mapping')
        row = FeeMapping.objects.select_related('treatment_type', 'policy_item__catalogue').get(pk=row.pk)
        self.assertIn('变化', selectors.mapping_blocker(row))

    def test_mapping_quantity_requires_positive_four_decimal_units(self):
        cat = self.catalogue(); item = cat.items.filter(payment_class='A').first()
        for quantity in ['0', '-1', '0.00001', 'NaN', 'Infinity']:
            with self.assertRaises(RuleError): services.prepare_mapping(actor=self.manager, treatment_type_id=self.fee.pk,
                policy_item_id=item.pk, policy_units_per_fee=quantity, compatibility_basis='合成单位核对')
        form = MappingForm(dict(treatment_type_id=self.fee.pk, policy_item_id=item.pk, policy_units_per_fee='0.0001', compatibility_basis='合成单位核对'))
        self.assertTrue(form.is_valid(), form.errors)

    def test_duplicate_active_fee_mapping_requires_explicit_old_disable(self):
        row = self.mapping(); other = self.mapping(row.policy_item.catalogue, publish=False)
        with self.assertRaises(RuleError): self.review(other, 'mapping')
        self.disable(row, 'mapping', self.manager); self.review(other, 'mapping')
        self.assertEqual(FeeMapping.objects.filter(state='CONFIRMED').count(), 1)

    def test_eligibility_is_append_only_and_does_not_follow_location_or_phone(self):
        self.arrangement()
        first = self.create(self.eligibility_preview(insured_region='CN-11'), self.front)
        row, blocker = selectors.eligibility_at(self.a.pk, self.p1.pk, self.today)
        self.assertEqual(row.pk, first.pk); self.assertIn('参保地', blocker)
        second = self.create(self.eligibility_preview(state='UNKNOWN', insured_region='UNKNOWN', scheme='UNKNOWN'), self.front)
        self.assertEqual(second.previous_id, first.pk); self.assertEqual(second.version, 2)
        first.refresh_from_db(); self.assertEqual(first.insured_region, 'CN-11'); self.assertEqual(first.source, 'LOCAL_SIMULATION')

    def test_eligibility_cannot_be_certified_with_unknown_area_or_type(self):
        for kw in [dict(insured_region='UNKNOWN'), dict(scheme='UNKNOWN')]:
            with self.assertRaises(RuleError): self.eligibility_preview(**kw)

    def test_eligibility_requires_synthetic_reference_not_real_card(self):
        with self.assertRaises(RuleError): self.eligibility_preview(reference='430101200001011234')
        self.assertFalse(EligibilityFact.objects.exists())

    def test_frontdesk_cannot_use_other_clinic_patient_or_manager_financial_scope(self):
        with self.assertRaises(ObjectDoesNotExist): self.eligibility_preview(patient_id=self.p2.pk)
        with self.assertRaises(PermissionDenied): self.eligibility_preview(actor=self.manager)

    def test_eligibility_preview_and_repeat_do_not_create_patient_or_second_version(self):
        p = self.eligibility_preview(); self.assertFalse(EligibilityFact.objects.exists())
        row = self.create(p, self.front); repeated = self.create(p, self.front)
        self.assertEqual(row.pk, repeated.pk); self.assertEqual(EligibilityFact.objects.count(), 1); self.assertEqual(Patient.objects.count(), 2)

    def test_stale_eligibility_preview_requires_current_version_comparison(self):
        p = self.eligibility_preview(); self.create(self.eligibility_preview(state='UNKNOWN'), self.front)
        with self.assertRaises(RuleError): self.create(p, self.front)
        self.assertEqual(EligibilityFact.objects.count(), 1)

    def test_eligibility_dates_and_clinic_arrangement_checked_separately(self):
        self.create(self.eligibility_preview(), self.front)
        self.assertIn('没有', selectors.eligibility_at(self.a.pk, self.p1.pk, self.today)[1])
        self.arrangement(); self.assertEqual(selectors.eligibility_at(self.a.pk, self.p1.pk, self.today)[1], '')
        self.assertIn('有效期', selectors.eligibility_at(self.a.pk, self.p1.pk, self.end + timedelta(days=1))[1])

    def test_eligibility_or_catalogue_history_cannot_be_updated_or_deleted(self):
        cat = self.catalogue(); row = self.create(self.eligibility_preview(), self.front)
        for mutate in [lambda: EligibilityFact.objects.filter(pk=row.pk).update(basis='覆盖旧核对'),
                       lambda: EligibilityFact.objects.filter(pk=row.pk).delete(),
                       lambda: PolicyItem.objects.filter(catalogue=cat).update(unit='伪造补齐单位'),
                       lambda: PolicyCatalogue.objects.filter(pk=cat.pk).update(notice='覆盖原通知'),
                       lambda: InsuranceEvent.objects.all().update(reason='覆盖历史')]:
            with self.assertRaises(DatabaseError), transaction.atomic(): mutate()

    def test_eligibility_chain_cannot_cross_patient_by_direct_insert(self):
        row = self.create(self.eligibility_preview(), self.front)
        with self.assertRaises(DatabaseError), transaction.atomic():
            EligibilityFact.objects.create(clinic=self.a, patient=self.p2, previous=row, version=2, insured_region='CN-43',
                scheme='EMPLOYEE', state='VERIFIED', starts_on=self.today, ends_on=self.end, reference='SIM-BAD-CHAIN', basis='错误链', recorded_by=self.front)

    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_never_confirms_preparation(self):
        p = services.prepare_catalogue(actor=self.f1)
        with self.assertRaises(PermissionDenied): self.create(p, self.f1)

    @override_settings(ADC_CLINICAL_SYNTHETIC=False)
    def test_real_environment_cannot_create_simulation(self):
        p = services.prepare_catalogue(actor=self.f1)
        with self.assertRaises(PermissionDenied): self.create(p, self.f1)

    def test_preparation_workflow_creates_no_clinical_invoice_or_cash_facts(self):
        cat = self.catalogue(); self.arrangement(cat); self.mapping(cat)
        self.create(self.eligibility_preview(), self.front)
        self.assertEqual(Patient.objects.count(), 2)
        for model in [Visit, TreatmentRecord, Invoice, CashEntry]: self.assertFalse(model.objects.exists())

    def concurrent(self, callback, actors):
        barrier = Barrier(len(actors))
        def run(actor):
            close_old_connections()
            user = UserAccount.objects.get(pk=actor.pk); user._adc_workspace = WorkspaceContext.objects.get(pk=actor._adc_workspace.pk)
            barrier.wait(timeout=10)
            try: return ('ok', callback(user))
            except RuleError: return ('stale', None)
            finally: close_old_connections()
        with ThreadPoolExecutor(max_workers=len(actors)) as pool: return list(pool.map(run, actors))

    def test_concurrent_same_operation_import_has_one_catalogue(self):
        p = services.prepare_catalogue(actor=self.f1)
        results = self.concurrent(lambda actor: self.create(p, actor).pk, [self.f1, self.f1])
        self.assertEqual([s for s, _ in results], ['ok', 'ok']); self.assertEqual(results[0][1], results[1][1])
        self.assertEqual(PolicyCatalogue.objects.count(), 1); self.assertEqual(PolicyItem.objects.count(), 202)

    def test_concurrent_first_imports_from_different_accounts_keep_one_source(self):
        previews = {u.pk: services.prepare_catalogue(actor=u) for u in [self.f1, self.f2]}
        results = self.concurrent(lambda actor: self.create(previews[actor.pk], actor).pk, [self.f1, self.f2])
        self.assertEqual(sorted(s for s, _ in results), ['ok', 'stale']); self.assertEqual(PolicyCatalogue.objects.count(), 1)
        self.assertEqual(PolicyItem.objects.count(), 202)

    def test_concurrent_explicit_resubmissions_create_one_next_review(self):
        old = self.catalogue(False); self.review(old, 'catalogue', decision='reject')
        previews = {u.pk: services.prepare_catalogue(actor=u, previous_id=old.pk, reason='重新核对同一原文来源') for u in [self.f1, self.f2]}
        results = self.concurrent(lambda actor: self.create(previews[actor.pk], actor).pk, [self.f1, self.f2])
        self.assertEqual(sorted(s for s, _ in results), ['ok', 'stale']); self.assertEqual(PolicyCatalogue.objects.count(), 2)
        self.assertEqual(PolicyCatalogue.objects.filter(previous=old).count(), 1)

    def test_concurrent_same_review_retains_single_decision(self):
        row = self.catalogue(False)
        p = services.prepare_review(actor=self.f2, kind='catalogue', pk=row.pk, decision='approve', reason='合成并发核对')
        results = self.concurrent(lambda actor: services.confirm_review(actor=actor, proposal_token=p['proposal_token'], confirmed=True)[0].pk, [self.f2, self.f2])
        self.assertEqual([s for s, _ in results], ['ok', 'ok']); self.assertEqual(InsuranceEvent.objects.filter(action='REVIEW').count(), 1)

    def test_concurrent_overlapping_arrangements_only_one_confirmed(self):
        cat = self.catalogue(); a = self.arrangement(cat, publish=False); b = self.arrangement(cat, publish=False)
        f3 = self.finance('insurance-third-reviewer')
        previews = {self.f2.pk: services.prepare_review(actor=self.f2, kind='arrangement', pk=a.pk, decision='approve', reason='合成并发核对'),
                    f3.pk: services.prepare_review(actor=f3, kind='arrangement', pk=b.pk, decision='approve', reason='合成并发核对')}
        results = self.concurrent(lambda actor: services.confirm_review(actor=actor, proposal_token=previews[actor.pk]['proposal_token'], confirmed=True)[0].pk, [self.f2, f3])
        self.assertEqual(sorted(s for s, _ in results), ['ok', 'stale']); self.assertEqual(ClinicArrangement.objects.filter(state='CONFIRMED').count(), 1)

    def test_concurrent_eligibility_versions_have_single_current_result(self):
        previews = {self.front.pk: self.eligibility_preview(), self.front2.pk: self.eligibility_preview(actor=self.front2, state='UNKNOWN')}
        results = self.concurrent(lambda actor: self.create(previews[actor.pk], actor).pk, [self.front, self.front2])
        self.assertEqual(sorted(s for s, _ in results), ['ok', 'stale']); self.assertEqual(EligibilityFact.objects.count(), 1)
