"""C3.2A: concrete explanations, exact versions and existing boundaries."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from importlib import import_module
from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from adc_core.rules import RuleError
from care.models import Invoice, TreatmentRecord
from clinical import plans
from clinical.disclosures import FIELDS
from clinical.plan_models import PlanDraft, PlanVersion, PlanDecision, PerformedProcedure
from clinical.plan_selectors import self_plan_details
from finance.cash_models import CashEntry
from tests.test_treatment_continuity import PlanFixture
from tests.workspace_client import WorkspaceClient
from accounts.models import UserAccount
from workspaces.models import WorkspaceContext


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class TreatmentDisclosureTests(PlanFixture, TransactionTestCase):
    def setUp(self):self.setup_plan()

    def notice_fields(self,plan,**changes):
        row=PlanDraft.objects.get(plan=plan).payload['steps'][0]
        data={key:'PRIVATE_DISCLOSURE_'+key for key,_,_ in FIELDS}
        data.update(sequence=1,step_key=row['step_key'],prepared=True)
        data.update(changes);return data

    def prepare(self,plan,**changes):
        return self.command(plan,'DISCLOSURE',**self.notice_fields(plan,**changes))

    def test_legacy_version_is_explicitly_missing_not_fabricated(self):
        plan=self.new_plan();version=self.publish_plan(plan)
        self.assertEqual(version.disclosures,{})
        d=self_plan_details(self.patient_user,plan.pk)['steps'][0].disclosure
        self.assertFalse(d['available']);self.assertEqual(d['state'],'MISSING')
        self.assertEqual(d['fields'],[])

    def test_prepared_explanation_is_attributed_and_does_not_record_consent_or_money(self):
        plan=self.new_plan();self.prepare(plan,prepared_by=99999,prepared_at='2000-01-01T00:00:00+00:00')
        version=self.publish_plan(plan);saved=next(iter(version.disclosures.values()))
        self.assertEqual(saved['prepared_by'],self.doc.pk)
        self.assertEqual(saved['prepared_by_name'],self.doc.dentist.name)
        self.assertNotEqual(saved['prepared_at'],'2000-01-01T00:00:00+00:00')
        self.assertTrue(self_plan_details(self.patient_user,plan.pk)['steps'][0].disclosure['available'])
        for model in (PlanDecision,PerformedProcedure,TreatmentRecord,Invoice,CashEntry):self.assertFalse(model.objects.exists())

    def test_new_draft_is_not_visible_to_patient_until_version_confirmation(self):
        plan=self.new_plan();old=self.publish_plan(plan)
        self.command(plan,'BEGIN_AMEND',reason='补充本步骤治疗说明，保留原讨论版本')
        self.prepare(plan)
        self.assertEqual(self_plan_details(self.patient_user,plan.pk)['version'].pk,old.pk)
        self.assertFalse(self_plan_details(self.patient_user,plan.pk)['steps'][0].disclosure['available'])
        self.assertTrue(self.publish_plan(plan).disclosures)

    def test_incomplete_prepared_explanation_rolls_back_without_losing_saved_content(self):
        plan=self.new_plan();self.prepare(plan,prepared=False,risks='保留已有风险草稿')
        before=PlanDraft.objects.get(plan=plan).payload
        with self.assertRaises(RuleError):self.prepare(plan,risks='')
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload,before)

    def test_unfinished_explanation_never_exposes_draft_text_to_patient(self):
        plan=self.new_plan();self.prepare(plan,prepared=False)
        self.publish_plan(plan);d=self_plan_details(self.patient_user,plan.pk)['steps'][0].disclosure
        self.assertFalse(d['available']);self.assertEqual(d['fields'],[])
        self.assertNotIn('PRIVATE_DISCLOSURE',str(d))

    def test_step_and_summary_changes_require_review_and_old_explanation_remains(self):
        plan=self.new_plan();self.prepare(plan);old=self.publish_plan(plan)
        self.command(plan,'BEGIN_AMEND',reason='复核牙位与新方案摘要，原说明保留')
        row=dict(PlanDraft.objects.get(plan=plan).payload['steps'][0]);row.update(sequence=1,tooth=26)
        self.command(plan,'UPDATE_STEP',**row);self.command(plan,'NOTES',summary='不同的后续治疗范围')
        with self.assertRaises(RuleError):plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.prepare(plan,risks='重新核对后为本版本记录的风险')
        new=self.publish_plan(plan);old.refresh_from_db()
        self.assertEqual(next(iter(old.disclosures.values()))['risks'],'PRIVATE_DISCLOSURE_risks')
        self.assertEqual(next(iter(new.disclosures.values()))['risks'],'重新核对后为本版本记录的风险')
        self.assertEqual(new.previous_id,old.pk)

    def test_catalogue_definition_change_requires_new_review(self):
        plan=self.new_plan();self.prepare(plan)
        self.item.name='修改后的课程治疗目录';self.item.save(update_fields=['name'])
        with self.assertRaises(RuleError):plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.prepare(plan);self.assertTrue(self.publish_plan(plan).disclosures)

    def test_source_refresh_requires_review(self):
        plan=self.new_plan();self.prepare(plan);self.v=self.another()
        self.command(plan,'REFRESH_SOURCE')
        with self.assertRaises(RuleError):plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.prepare(plan);self.assertTrue(self.publish_plan(plan).disclosures)

    def test_old_preview_and_replayed_save_do_not_create_extra_effects(self):
        plan=self.new_plan();self.prepare(plan)
        p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        plan.refresh_from_db();op=uuid.uuid4();data=self.notice_fields(plan,questions='新问题及医师待说明事项')
        kwargs=dict(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk,expected_revision=plan.revision,operation_id=op,action='DISCLOSURE',fields=data)
        plans.change_plan(**kwargs);self.assertTrue(plans.change_plan(**kwargs)[1])
        with self.assertRaises(RuleError):plans.change_plan(**dict(kwargs,fields=dict(data,risks='changed same operation')))
        with self.assertRaises(RuleError):plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        new=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        first=plans.confirm_plan(actor=self.doc,proposal_token=new['proposal_token'],confirmed=True)[0]
        self.assertEqual(plans.confirm_plan(actor=self.doc,proposal_token=new['proposal_token'],confirmed=True)[0].pk,first.pk)
        self.assertEqual(PlanVersion.objects.count(),1)

    def test_wrong_step_identity_does_not_move_explanation(self):
        plan=self.new_plan()
        with self.assertRaises(RuleError):self.prepare(plan,step_key=str(uuid.uuid4()))
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload['disclosures'],{})

    def test_concurrent_tabs_cannot_overwrite_the_acknowledged_explanation(self):
        plan=self.new_plan();plan.refresh_from_db();revision=plan.revision
        user_id=self.doc.pk;context_id=self.doc._adc_workspace.pk;gate=Barrier(2)
        def save(label):
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=user_id);actor._adc_workspace=WorkspaceContext.objects.get(pk=context_id)
                fields=self.notice_fields(plan,risks=label);gate.wait(timeout=15)
                try:
                    plans.change_plan(actor=actor,visit_id=self.v.pk,plan_id=plan.pk,expected_revision=revision,
                        operation_id=uuid.uuid4(),action='DISCLOSURE',fields=fields)
                    return label
                except RuleError:return None
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,['TAB_ONE','TAB_TWO']))
        winners=[r for r in results if r];self.assertEqual(len(winners),1)
        notice=next(iter(PlanDraft.objects.get(plan=plan).payload['disclosures'].values()))
        self.assertEqual(notice['risks'],winners[0])

    def test_confirmed_explanation_and_migration_are_preserved(self):
        plan=self.new_plan();self.prepare(plan);version=self.publish_plan(plan)
        with self.assertRaises(DatabaseError),transaction.atomic():
            PlanVersion.objects.filter(pk=version.pk).update(disclosures={})
        migration=import_module('clinical.migrations.0008_plan_disclosures')
        with self.assertRaises(RuntimeError):migration.preserve_disclosures(apps,connection.schema_editor())
        with connection.cursor() as cursor:
            cursor.execute("SELECT column_default FROM information_schema.columns WHERE table_name='adc_plan_version' AND column_name='disclosures'")
            self.assertIn('{}',cursor.fetchone()[0])

    def test_revoked_professional_scope_cannot_confirm_or_edit(self):
        plan=self.new_plan();self.prepare(plan);p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.decide(self.authority,'REVOKE')
        with self.assertRaises(PermissionDenied):self.prepare(plan)
        with self.assertRaises(PermissionDenied):plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)

    def test_web_and_native_projection_share_exact_version_and_clinical_scope(self):
        plan=self.new_plan();self.prepare(plan);version=self.publish_plan(plan)
        client=WorkspaceClient();client.force_login(self.patient_user)
        response=client.get(reverse('portal_plan',args=[plan.pk]));self.assertContains(response,'PRIVATE_DISCLOSURE_risks')
        data=client.get(reverse('mini_plan',args=[plan.pk])).json()['data']
        self.assertEqual(data['version'],version.revision);self.assertTrue(data['steps'][0]['disclosure']['available'])
        self.assertNotIn('prepared_by',data['steps'][0]['disclosure'])
        client.force_login(self.front)
        for route in [reverse('portal_plan',args=[plan.pk]),reverse('mini_plan',args=[plan.pk])]:
            response=client.get(route);self.assertIn(response.status_code,[403,404]);self.assertNotIn(b'PRIVATE_DISCLOSURE',response.content)

    def test_doctor_form_preserves_invalid_input_and_preview_contains_explanation(self):
        plan=self.new_plan();client=WorkspaceClient();client.force_login(self.doc)
        url=reverse('clinical_plan_detail',args=[self.v.pk,plan.pk]);response=client.get(url)
        form=response.context['disclosure_form'];data={f.name:f.value() if f.value() is not None else '' for f in form}
        data.update(self.notice_fields(plan),action='DISCLOSURE',prepared='on',risks='')
        response=client.post(url,data);self.assertEqual(response.status_code,400)
        self.assertContains(response,'PRIVATE_DISCLOSURE_purpose',status_code=400)
        data['risks']='PRIVATE_DISCLOSURE_risks';response=client.post(url,data);self.assertEqual(response.status_code,302,response.content)
        self.assertIn('?notice=1#plan-disclosure',response.url)
        response=client.get(reverse('clinical_plan_preview',args=[self.v.pk,plan.pk]));self.assertContains(response,'PRIVATE_DISCLOSURE_risks')
