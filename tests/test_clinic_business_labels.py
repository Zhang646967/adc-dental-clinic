from django.test import SimpleTestCase

from clinical.document_forms import DocumentForm
from clinical.document_models import ClinicalDocumentVersion
from clinical.forms import ProfessionalCaseForm
from clinical.models import ProfessionalAuthorization
from finance.cash_models import CashEntry
from finance.reconciliation_models import CashEvidenceVersion
from insurance.forms import EligibilityForm
from insurance.models import EligibilityFact
from insurance.settlement_forms import SettlementForm
from insurance.settlement_models import SettlementEvent, SettlementRequest, SimulationOutcome


class ClinicBusinessLabelTests(SimpleTestCase):
    def test_settlement_screens_and_forms_use_the_same_measurement_labels(self):
        for code, label in SettlementForm.base_fields["simulation_mode"].choices:
            self.assertEqual(SettlementRequest(simulation_mode=code).get_simulation_mode_display(), label)
            self.assertNotRegex(label, "模拟|课程|合成")
        enrolled = EligibilityFact(scheme="EMPLOYEE", state="VERIFIED")
        self.assertEqual(enrolled.get_scheme_display(), dict(EligibilityForm.base_fields["scheme"].choices)["EMPLOYEE"])
        self.assertEqual(enrolled.get_state_display(), "院内待遇测算依据已核对")
        self.assertEqual(SettlementRequest(state="PROCESSING").get_state_display(), "院内测算处理中")
        self.assertEqual(SettlementRequest(state="DECLINED").get_state_display(), "本次测算未受理")
        self.assertEqual(SimulationOutcome(result="ACCEPTED").get_result_display(), "本次院内测算已受理")

    def test_cash_entries_distinguish_an_entry_type_from_its_posting_state(self):
        receipt = CashEntry(kind="RECEIPT", state="PENDING")
        self.assertEqual(receipt.display_kind, "收款登记")
        self.assertEqual(receipt.state, "PENDING")
        self.assertEqual(CashEntry(kind="REFUND", state="POSTED").display_kind, "退款登记")
        self.assertEqual(CashEntry(kind="REFUND", advance_patient_id=2).display_kind, "患者预收原渠道退款")

    def test_account_evidence_and_credentials_do_not_claim_institutional_verification(self):
        version = ClinicalDocumentVersion(evidence_kind="ACCOUNT_CONFIRMATION")
        self.assertEqual(version.get_evidence_kind_display(), "医师账号确认")
        self.assertEqual(version.get_evidence_kind_display(), dict(DocumentForm.base_fields["evidence_kind"].choices)[version.evidence_kind])
        case = ProfessionalAuthorization(source_kind="SYNTHETIC")
        self.assertIn("未经执业资质核验", case.get_source_kind_display())
        self.assertEqual(case.get_source_kind_display(), dict(ProfessionalCaseForm.base_fields["source_kind"].choices)[case.source_kind])

    def test_only_known_automatic_event_explanations_get_a_new_display_name(self):
        old_cash = "随原始收付款申请提交的合成凭据"
        old_query = "按原唯一请求编号取回本地模拟结果"
        cash = CashEvidenceVersion(initial=True, reason=old_cash)
        query = SettlementEvent(action="QUERY", reason=old_query)
        self.assertIn("外部收付另行核对", cash.display_reason)
        self.assertEqual(query.display_reason, "按原请求编号取回院内测算结果")
        self.assertEqual((cash.reason, query.reason), (old_cash, old_query))
        self.assertEqual(CashEvidenceVersion(initial=False, reason=old_cash).display_reason, old_cash)
        self.assertEqual(SettlementEvent(action="REVIEW", reason=old_query).display_reason, old_query)
