"""v0.4 real PostgreSQL acceptance tests. Authored here; run in Docker, NOT SQLite."""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction, IntegrityError
from django.test import TransactionTestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from assistants.models import AssistantEvent, UsageBucket
from assistants.services import respond
from assistants.provider import ProviderError
from assistants.quotas import RateLimited
from care.models import VisitRecordVersion, TreatmentRecord, Invoice, AuditEvent
from care.services import review_allergies,add_treatment,remove_treatment,complete_visit
from portal.models import PatientAccess,BookingReceipt
from portal.services import preview_booking,confirm_booking,cancel_booking,public_options
from registry.models import TreatmentType,Allergy
from scheduling.models import Visit
from scheduling.services import change_appointment
from tests.fixtures import FixtureMixin

class V04Fixture(FixtureMixin):
    def set_up_v04(self):
        self.make_fixture()
        self.pa=UserAccount.objects.create_user(username="patient_a",password="testing-only")
        self.pb=UserAccount.objects.create_user(username="patient_b",password="testing-only")
        self.access=PatientAccess.objects.create(user=self.pa,patient=self.p1)
        self.access2=PatientAccess.objects.create(user=self.pb,patient=self.p2)
        self.doctor=UserAccount.objects.create_user(username="dentist_a",password="testing-only",dentist=self.d1)
        RoleAssignment.objects.create(user=self.doctor,role="DENTIST",scope_kind="SELF_DENTIST")
        self.service=TreatmentType.objects.create(code="CLEAN",name="演示洁治",unit_definition="标准单位",standard_unit_price=Decimal("99.99"))
        self.allergy=Allergy.objects.create(code="LATEX",name="乳胶")
    def token(self,user=None):
        return preview_booking(user=user or self.pa,slot_id=self.slot1.pk,start=self.t)[2]
    def arrived(self):
        v=self.book()
        return change_appointment(actor=self.front,visit_id=v.pk,expected_version=v.lock_version,action="check_in")
    def review(self,v,status="NO_KNOWN",ids=()):
        v.refresh_from_db();self.p1.refresh_from_db()
        patient=v.patient
        patient.refresh_from_db()
        return review_allergies(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,
            patient_version=patient.allergy_info_version,status=status,allergy_ids=ids)
    def line(self,v,quantity=Decimal("1.125")):
        v.refresh_from_db()
        return add_treatment(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,
            treatment_id=self.service.pk,quantity=quantity)
    def finish(self,v,outcome="TREATED",reason=""):
        v.refresh_from_db()
        return complete_visit(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,outcome=outcome,reason=reason)

class PortalAcceptanceTests(V04Fixture,TransactionTestCase):
    def setUp(self): self.set_up_v04()
    def test_preview_does_not_create_visit(self):
        self.token();self.assertEqual(Visit.objects.count(),0)
    def test_confirmation_creates_bound_patient_only(self):
        v=confirm_booking(actor=self.pa,token=self.token())
        self.assertEqual(v.patient_id,self.p1.pk);self.assertEqual(BookingReceipt.objects.count(),1)
    def test_confirmation_retry_returns_same_visit(self):
        t=self.token();a=confirm_booking(actor=self.pa,token=t);b=confirm_booking(actor=self.pa,token=t)
        self.assertEqual(a.pk,b.pk);self.assertEqual(Visit.objects.count(),1)
    def test_signed_token_rejects_another_account(self):
        with self.assertRaises(RuleError): confirm_booking(actor=self.pb,token=self.token())
        self.assertFalse(Visit.objects.exists())
    def test_signed_token_tampering_rejected(self):
        with self.assertRaises(RuleError): confirm_booking(actor=self.pa,token=self.token()+"tampered")
    def test_expired_token_rejected(self):
        t=self.token()
        with patch("django.core.signing.time.time",return_value=timezone.now().timestamp()+700):
            with self.assertRaises(RuleError): confirm_booking(actor=self.pa,token=t)
    def test_patient_cannot_impersonate_front_desk(self):
        with self.assertRaises(PermissionDenied): self.book(actor=self.pa)
    def test_revoked_patient_binding_blocks_confirmation(self):
        t=self.token();self.access.is_active=False;self.access.save()
        with self.assertRaises(PermissionDenied): confirm_booking(actor=self.pa,token=t)
    def test_portal_respects_staff_booking_conflict(self):
        t=self.token();self.book(patient_no=self.p2.patient_no)
        with self.assertRaises(RuleError): confirm_booking(actor=self.pa,token=t)
        self.assertFalse(BookingReceipt.objects.exists());self.assertEqual(Visit.objects.count(),1)
    def test_patient_cancellation_preserves_history(self):
        v=confirm_booking(actor=self.pa,token=self.token())
        cancel_booking(actor=self.pa,visit_id=v.pk,expected_version=v.lock_version,reason="时间有变")
        v.refresh_from_db();self.assertEqual(v.status,"CANCELLED");self.assertFalse(v.attended)
        self.assertFalse(Invoice.objects.exists());self.assertTrue(BookingReceipt.objects.filter(visit=v).exists())
    def test_patient_cannot_cancel_other_patient(self):
        v=self.book(patient_no=self.p2.patient_no)
        with self.assertRaises(Visit.DoesNotExist): cancel_booking(actor=self.pa,visit_id=v.pk,expected_version=v.lock_version,reason="取消")
    def test_patient_own_detail_404_for_other_patient(self):
        v=self.book(patient_no=self.p2.patient_no);self.client.force_login(self.pa)
        self.assertEqual(self.client.get(reverse("portal_visit",args=[v.pk])).status_code,404)
    def test_patient_cannot_read_staff_patient_details(self):
        self.client.force_login(self.pa)
        self.assertIn(self.client.get(reverse("patient_detail",args=[self.p2.pk])).status_code,(403,404))
    def test_patient_pages_render(self):
        self.client.force_login(self.pa)
        for route in ("portal_home","portal_appointments","portal_slots","portal_help","portal_assistant"):
            with self.subTest(route=route): self.assertEqual(self.client.get(reverse(route)).status_code,200)
    def test_portal_confirmation_requires_checkbox(self):
        self.client.force_login(self.pa)
        result=self.client.post(reverse("portal_confirm"),{"token":self.token()})
        self.assertEqual(result.status_code,200);self.assertFalse(Visit.objects.exists())
    def test_public_slots_exclude_occupied_and_have_no_patient_data(self):
        self.book();rows=public_options(self.pa)
        self.assertFalse(any(r["slot"].pk==self.slot1.pk and r["start"]==self.t for r in rows))
        self.assertTrue(all(set(row)=={"slot","start","end","start_iso"} for row in rows))
    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_blocks_booking_even_service(self):
        with self.assertRaises(PermissionDenied): confirm_booking(actor=self.pa,token=self.token())

class CareAcceptanceTests(V04Fixture,TransactionTestCase):
    def setUp(self): self.set_up_v04()
    def test_front_desk_cannot_add_treatment(self):
        v=self.arrived()
        with self.assertRaises(PermissionDenied): add_treatment(actor=self.front,visit_id=v.pk,expected_version=v.lock_version,treatment_id=self.service.pk,quantity=1)
    def test_allergy_review_records_current_version(self):
        v=self.arrived();draft=self.review(v,"KNOWN",[self.allergy.pk]);self.p1.refresh_from_db()
        self.assertEqual(draft.allergy_review_snapshot["information_version"],self.p1.allergy_info_version)
        self.assertEqual(draft.allergy_review_snapshot["status"],"KNOWN")
    def test_unknown_review_blocks_treated_completion(self):
        v=self.arrived();self.review(v,"UNKNOWN");self.line(v)
        with self.assertRaises(RuleError): self.finish(v)
        self.assertFalse(Invoice.objects.exists())
    def test_changed_patient_allergy_version_blocks_completion(self):
        v=self.arrived();self.review(v);self.line(v)
        self.p1.refresh_from_db();self.p1.allergy_info_version+=1;self.p1.save(update_fields=["allergy_info_version"])
        with self.assertRaises(RuleError): self.finish(v)
    def test_treatment_uses_catalogue_snapshot_and_decimal_amount(self):
        v=self.arrived();line=self.line(v)
        self.assertEqual(line.unit_price,Decimal("99.99"));self.assertEqual(line.line_amount,Decimal("112.49"))
    def test_completion_publishes_one_invoice(self):
        v=self.arrived();self.review(v);self.line(v);inv=self.finish(v)
        v.refresh_from_db();self.assertEqual(v.status,"COMPLETED");self.assertTrue(v.attended)
        self.assertEqual(inv.current_record_version.total_amount,Decimal("112.49"));self.assertEqual(Invoice.objects.count(),1)
    def test_completion_retry_returns_original_invoice(self):
        v=self.arrived();self.review(v);self.line(v);a=self.finish(v);b=self.finish(v)
        self.assertEqual(a.pk,b.pk);self.assertEqual(Invoice.objects.count(),1)
    def test_no_treatment_close_preserves_attendance_and_zero_bill(self):
        v=self.arrived();inv=self.finish(v,"NO_TREATMENT","患者选择延期治疗")
        v.refresh_from_db();self.assertEqual(v.status,"CLOSED_NO_TREATMENT");self.assertTrue(v.attended)
        self.assertEqual(inv.current_record_version.total_amount,Decimal("0"));self.assertFalse(TreatmentRecord.objects.exists())
    def test_no_treatment_requires_reason(self):
        v=self.arrived()
        with self.assertRaises(RuleError): self.finish(v,"NO_TREATMENT")
        self.assertFalse(Invoice.objects.exists())
    def test_no_treatment_rejects_actual_lines(self):
        v=self.arrived();self.line(v)
        with self.assertRaises(RuleError): self.finish(v,"NO_TREATMENT","离开")
    def test_treated_requires_actual_lines(self):
        v=self.arrived();self.review(v)
        with self.assertRaises(RuleError): self.finish(v)
    def test_audit_failure_rolls_back_completion(self):
        v=self.arrived();self.review(v);self.line(v)
        with patch("care.services.emit",side_effect=RuntimeError("synthetic audit failure")):
            with self.assertRaises(RuntimeError): self.finish(v)
        v.refresh_from_db();self.assertEqual(v.status,"CHECKED_IN");self.assertFalse(Invoice.objects.exists())
        self.assertEqual(v.record_versions.get().state,"DRAFT")
    def test_catalogue_reprice_does_not_change_published_invoice(self):
        v=self.arrived();self.review(v);self.line(v);inv=self.finish(v)
        self.service.standard_unit_price=200;self.service.name="新名称";self.service.save()
        line=inv.current_record_version.treatment_lines.get()
        self.assertEqual(line.name_snapshot,"演示洁治");self.assertEqual(line.unit_price,Decimal("99.99"))
    def test_database_rejects_published_line_rewrite(self):
        v=self.arrived();self.review(v);line=self.line(v);self.finish(v)
        with self.assertRaises(IntegrityError):
            with transaction.atomic(): TreatmentRecord.objects.filter(pk=line.pk).update(quantity=2)
    def test_draft_line_remove_recalculates_total(self):
        v=self.arrived();line=self.line(v);v.refresh_from_db()
        draft=remove_treatment(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,line_id=line.pk,reason="重复录入")
        self.assertEqual(draft.total_amount,Decimal("0"));self.assertFalse(draft.treatment_lines.exists())
    def test_invoice_patient_ownership(self):
        v=self.arrived();inv=self.finish(v,"NO_TREATMENT","延期")
        self.client.force_login(self.pa);self.assertEqual(self.client.get(reverse("portal_invoice",args=[inv.pk])).status_code,200)
        self.client.force_login(self.pb);self.assertEqual(self.client.get(reverse("portal_invoice",args=[inv.pk])).status_code,404)
    def test_workspace_and_preview_render_without_writes(self):
        v=self.arrived();self.client.force_login(self.doctor)
        for name in ("care_workspace","care_complete"):
            self.assertEqual(self.client.get(reverse(name,args=[v.pk])).status_code,200)
        self.assertFalse(VisitRecordVersion.objects.exists());self.assertFalse(Invoice.objects.exists())
    def test_stale_version_rejected_for_treatment(self):
        v=self.arrived();version=v.lock_version;self.review(v)
        with self.assertRaises(RuleError): add_treatment(actor=self.doctor,visit_id=v.pk,expected_version=version,treatment_id=self.service.pk,quantity=1)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_blocks_complete(self):
        with self.assertRaises(PermissionDenied): complete_visit(actor=self.doctor,visit_id=999,expected_version=0,outcome="NO_TREATMENT",reason="test")

class AssistantAcceptanceTests(V04Fixture,TransactionTestCase):
    def setUp(self): self.set_up_v04()
    def api(self,user,audience="patient",**payload):
        self.client.force_login(user)
        return self.client.post(reverse("assistant_api",args=[audience]),data=json.dumps(payload),content_type="application/json")
    def test_patient_cannot_use_staff_assistant(self):
        self.assertEqual(self.api(self.pa,"staff",message="今天").status_code,403)
    def test_technical_admin_cannot_use_business_assistant(self):
        self.assertEqual(self.api(self.tech,"staff",message="今天").status_code,403)
    def test_staff_cannot_use_patient_assistant_without_binding(self):
        self.assertEqual(self.api(self.front,message="预约").status_code,403)
    def test_csrf_required_for_chat(self):
        c=__import__("tests.workspace_client",fromlist=["WorkspaceClient"]).WorkspaceClient(enforce_csrf_checks=True);c.force_login(self.pa)
        response=c.post(reverse("assistant_api",args=["patient"]),data=json.dumps({"message":"预约"}),content_type="application/json")
        self.assertEqual(response.status_code,403)
    def test_demo_does_not_call_provider(self):
        with patch("assistants.provider.classify") as p:
            result=respond(user=self.pa,audience="patient",message="预约")
        p.assert_not_called();self.assertEqual(result["mode"],"demo");self.assertFalse(result["actions_executed"])
    def test_clinical_question_is_handoff_not_diagnosis(self):
        with patch("assistants.provider.classify") as p:
            result=respond(user=self.pa,audience="patient",message="牙痛吃什么药")
        p.assert_not_called();self.assertEqual(result["intent"],"clinical");self.assertFalse(Visit.objects.exists())
    def test_secret_input_not_saved_or_sent(self):
        result=self.api(self.pa,message="sk-this-is-a-test-secret-000")
        self.assertEqual(result.status_code,400);self.assertFalse(AssistantEvent.objects.exists())
    def test_json_extra_fields_rejected(self):
        self.assertEqual(self.api(self.pa,message="预约",patient_id=self.p2.pk).status_code,400)
    def test_metadata_contains_no_raw_message(self):
        text="帮我预约蓝色星球专用文字"
        result=respond(user=self.pa,audience="patient",message=text)
        event=AssistantEvent.objects.get(request_id=result["request_id"])
        self.assertNotIn(text,str(event.__dict__));self.assertEqual(event.input_chars,len(text))
    def test_patient_summary_only_reads_self(self):
        self.book(patient_no=self.p2.patient_no,slot_id=self.slot2.pk)
        result=respond(user=self.pa,audience="patient",message="我的预约")
        self.assertNotIn(self.b.name,str(result["facts"]))
    @override_settings(AI_MODE="remote")
    def test_remote_requires_consent(self):
        with patch("assistants.provider.classify") as p:
            result=respond(user=self.pa,audience="patient",message="预约",consent=False)
        p.assert_not_called();self.assertEqual(result["mode"],"local_only")
    @override_settings(AI_MODE="remote")
    def test_provider_gets_only_redacted_question(self):
        self.book()
        with patch("assistants.provider.classify",return_value="appointments") as p:
            result=respond(user=self.pa,audience="patient",message="查我的预约，电话13800138000，email test@example.com",consent=True)
        sent=p.call_args.args[0]
        self.assertNotIn("13800138000",sent);self.assertNotIn("test@example.com",sent)
        self.assertNotIn(self.p1.patient_no,sent);self.assertEqual(result["mode"],"remote")
    @override_settings(AI_MODE="remote")
    def test_provider_failure_is_explicit_fallback(self):
        with patch("assistants.provider.classify",side_effect=ProviderError("provider_unavailable")):
            result=respond(user=self.pa,audience="patient",message="预约",consent=True)
        self.assertEqual(result["mode"],"fallback");self.assertFalse(Visit.objects.exists())
    @override_settings(AI_MODE="remote")
    def test_authorization_rechecked_after_provider(self):
        def revoke(*args):
            PatientAccess.objects.filter(pk=self.access.pk).update(is_active=False)
            return "appointments"
        with patch("assistants.provider.classify",side_effect=revoke):
            with self.assertRaises(PermissionDenied): respond(user=self.pa,audience="patient",message="我的预约",consent=True)
        self.assertFalse(AssistantEvent.objects.exists())
    @override_settings(AI_USER_MINUTE_LIMIT=1)
    def test_quota_blocks_second_request(self):
        respond(user=self.pa,audience="patient",message="预约")
        with self.assertRaises(RateLimited): respond(user=self.pa,audience="patient",message="预约")
        self.assertEqual(AssistantEvent.objects.count(),1)
    @override_settings(AI_MODE="remote",ADC_READ_ONLY=True)
    def test_readonly_never_spends_remote_quota(self):
        with patch("assistants.provider.classify") as p:
            result=respond(user=self.pa,audience="patient",message="预约",consent=True)
        p.assert_not_called();self.assertEqual(result["mode"],"local_only")
    def test_staff_assistant_page_renders(self):
        self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse("staff_assistant")).status_code,200)
    def test_api_returns_private_cache_header(self):
        result=self.api(self.pa,message="预约")
        self.assertEqual(result.status_code,200);self.assertIn("no-store",result["Cache-Control"])
