"""Real website/native HTTP; shared commands and PostgreSQL remain enabled."""
from datetime import timedelta
import uuid
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from care.models import Invoice,TreatmentRecord
from care.services import complete_visit
from clinical import plans,executions
from clinical.models import SensitiveReadEvent
from clinical.plan_models import TreatmentPlan,PlanDraft,PlanVersion,PlanDecision,PerformedProcedure,PlanAppointment
from finance.cash_models import CashEntry
from portal.models import PatientRelationship,PatientAppointmentGrant
from tests.test_treatment_continuity import PlanFixture
from tests.workspace_client import WorkspaceClient


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class TreatmentContinuityHTTPTests(PlanFixture,TransactionTestCase):
    def setUp(self):self.setup_plan()
    def client_for(self,user):
        client=WorkspaceClient();client.force_login(user);return client
    def values(self,form):return {f.name:f.value() if f.value() is not None else '' for f in form}
    def mini_post(self,c,name,data,**kwargs):return c.post(reverse(name,kwargs=kwargs),data,HTTP_X_ADC_WORKSPACE=c.current_token())
    def test_website_can_open_write_and_confirm_plan_without_charging(self):
        c=self.client_for(self.doc);url=reverse('clinical_plans',args=[self.v.pk]);r=c.get(url);self.assertEqual(r.status_code,200)
        data=self.values(r.context['form']);data['confirmed']='on';self.assertEqual(c.post(url,data).status_code,302)
        plan=TreatmentPlan.objects.get();url=reverse('clinical_plan_detail',args=[self.v.pk,plan.pk]);r=c.get(url)
        data=self.values(r.context['notes_form']);data.update(action='NOTES',summary='PRIVATE_HTTP_PLAN',discussion_note='已与本人讨论，先保留版本',amendment_reason='')
        self.assertEqual(c.post(url,data).status_code,302)
        r=c.get(url);data=self.values(r.context['step_form']);data.update(action='ADD_STEP',treatment_type=self.item.pk,service=self.service.pk,
            description='PRIVATE_HTTP_STEP',goal='PRIVATE_HTTP_GOAL',tooth=16,surfaces=['M','O'],estimated_quantity='1',estimated_unit_price='',estimate_note='费用仍待评估',alternative_group='',charge_basis='PER_EXECUTION',requires_lab='NO')
        r=c.post(url,data);self.assertEqual(r.status_code,302,r.content)
        target=reverse('clinical_plan_preview',args=[self.v.pk,plan.pk]);r=c.get(target);self.assertEqual(r.status_code,200,r.content)
        self.assertContains(r,'PRIVATE_HTTP_STEP');self.assertContains(r,'费用待评估');self.assertFalse(PlanVersion.objects.exists())
        data=self.values(r.context['form']);data.update(phase='confirm',confirmed='on');self.assertEqual(c.post(target,data).status_code,302)
        self.assertEqual(PlanVersion.objects.count(),1);self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_stale_website_text_is_preserved_and_rebase_does_not_save(self):
        plan=self.new_plan();c=self.client_for(self.doc);url=reverse('clinical_plan_detail',args=[self.v.pk,plan.pk]);r=c.get(url)
        first=self.values(r.context['notes_form']);first.update(action='NOTES',summary='first acknowledged',discussion_note='',amendment_reason='')
        other=dict(first,operation_id=str(uuid.uuid4()),summary='PRIVATE_UNSAVED_PLAN')
        self.assertEqual(c.post(url,first).status_code,302);r=c.post(url,other)
        self.assertEqual(r.status_code,409);self.assertContains(r,'PRIVATE_UNSAVED_PLAN',status_code=409);self.assertContains(r,'first acknowledged',status_code=409)
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload['summary'],'first acknowledged')
        other['review_current']='yes';r=c.post(url,other);self.assertEqual(r.status_code,200)
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload['summary'],'first acknowledged')
        data=self.values(r.context['notes_form']);data['action']='NOTES';self.assertEqual(c.post(url,data).status_code,302)
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload['summary'],'PRIVATE_UNSAVED_PLAN')
    def test_cross_patient_plan_form_is_denied_without_copying_text(self):
        plan=self.new_plan();c=self.client_for(self.doc);url=reverse('clinical_plan_detail',args=[self.v.pk,plan.pk]);r=c.get(url);data=self.values(r.context['notes_form'])
        other=self.booking(patient=self.p2,start=self.t+timedelta(hours=1));data.update(action='NOTES',summary='PRIVATE_WRONG_PATIENT')
        r=c.post(reverse('clinical_plan_detail',args=[other.pk,plan.pk]),data)
        self.assertEqual(r.status_code,404);self.assertNotIn('PRIVATE_WRONG_PATIENT',PlanDraft.objects.get(plan=plan).payload['summary'])
    def test_patient_website_decision_is_preview_first_and_not_payment(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get();c=self.client_for(self.patient_user)
        page=c.get(reverse('portal_plan',args=[plan.pk]));self.assertContains(page,'PRIVATE_PLAN_SUMMARY');self.assertNotContains(page,'工作草稿')
        url=reverse('portal_plan_decision',args=[plan.pk,step.pk]);r=c.post(url,dict(decision='ACCEPTED',note='本人已核对这个具体步骤'))
        self.assertEqual(r.status_code,200,r.content);self.assertFalse(PlanDecision.objects.exists())
        data=self.values(r.context['form']);data.update(phase='confirm',confirmed='on');self.assertEqual(c.post(url,data).status_code,302)
        self.assertEqual(PlanDecision.objects.get().decision,'ACCEPTED');self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(Invoice.objects.exists())
    def test_appointment_delegate_cannot_read_or_decide_clinical_plan(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get()
        relation=PatientRelationship.objects.create(clinic=self.a,patient=self.p2,delegate_user=self.patient_user,related_name='合成预约委托',kind='DELEGATE',state='VERIFIED',created_by=self.front)
        grant=PatientAppointmentGrant.objects.create(relationship=relation,valid_from=timezone.now()-timedelta(days=1),valid_until=timezone.now()+timedelta(days=1),created_by=self.front)
        c=self.client_for(self.patient_user);self.assertEqual(c.post(reverse('portal_subjects'),{'subject':'grant:'+str(grant.pk)}).status_code,302)
        for name,args in [('portal_plans',[]),('portal_plan',[plan.pk]),('mini_plans',[]),('mini_plan',[plan.pk])]:
            with self.subTest(route=name):self.assertEqual(c.get(reverse(name,args=args)).status_code,403)
        r=self.mini_post(c,'mini_plan_decision_preview',dict(decision='ACCEPTED'),pk=plan.pk,step_id=step.pk);self.assertEqual(r.status_code,403)
        self.assertFalse(PlanDecision.objects.exists())
    def test_seven_roles_keep_clinical_plan_private_and_frontdesk_minimal(self):
        plan=self.new_plan();self.publish_plan(plan);self.instruction()
        finance=UserAccount.objects.create_user(username='plan_finance');RoleAssignment.objects.create(user=finance,role='FINANCE',scope_kind='CHAIN')
        hq=UserAccount.objects.create_user(username='plan_hq');RoleAssignment.objects.create(user=hq,role='HQ',scope_kind='CHAIN')
        for actor in (self.doc,self.front,self.manager,self.tech,self.patient_user,finance,hq):
            c=self.client_for(actor)
            with self.subTest(role=actor.username):
                r=c.get(reverse('clinical_plan_detail',args=[self.v.pk,plan.pk]));self.assertEqual(r.status_code,200 if actor.pk==self.doc.pk else 403)
                r=c.get(reverse('clinical_next_list'));self.assertEqual(r.status_code,200 if actor.pk==self.front.pk else 403)
                if actor.pk==self.front.pk:self.assertNotContains(r,'PRIVATE_NEXT_PURPOSE');self.assertNotContains(r,'PRIVATE_PLAN_GOAL')
    def test_mini_plan_and_website_share_exact_patient_decisions(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get();c=self.client_for(self.patient_user)
        r=c.get(reverse('mini_plan',args=[plan.pk]));self.assertEqual(r.status_code,200,r.content);d=r.json()['data'];self.assertEqual(d['steps'][0]['id'],step.pk);self.assertIsNone(d['steps'][0]['decision'])
        r=self.mini_post(c,'mini_plan_decision_preview',dict(decision='DEFERRED',note='PRIVATE_PATIENT_DEFER'),pk=plan.pk,step_id=step.pk);self.assertEqual(r.status_code,200,r.content)
        token=r.json()['data']['proposal_token'];self.assertFalse(PlanDecision.objects.exists())
        for _ in range(2):
            r=self.mini_post(c,'mini_plan_decision_confirm',dict(proposal_token=token,confirmed='on',decision='ACCEPTED',note='FORGED_HIDDEN_NOTE'),pk=plan.pk,step_id=step.pk);self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(PlanDecision.objects.count(),1);self.assertEqual(PlanDecision.objects.get().note,'PRIVATE_PATIENT_DEFER')
        self.assertContains(c.get(reverse('portal_plan',args=[plan.pk])),'PRIVATE_PATIENT_DEFER');self.assertFalse(CashEntry.objects.exists())
    def test_native_missing_and_other_patient_plan_errors_are_private_json(self):
        plan=self.new_plan();self.publish_plan(plan);other=UserAccount.objects.create_user(username='missing_plan_patient')
        from portal.models import PatientAccess
        PatientAccess.objects.create(user=other,patient=self.p2);c=self.client_for(other)
        r=c.get(reverse('mini_plan',args=[plan.pk]));self.assertEqual(r.status_code,404);self.assertEqual(r.json()['code'],'NOT_FOUND');self.assertNotIn('PRIVATE_PLAN_SUMMARY',str(r.json()))
    def test_stale_patient_preview_requires_current_version_decision(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get();c=self.client_for(self.patient_user)
        r=self.mini_post(c,'mini_plan_decision_preview',dict(decision='ACCEPTED'),pk=plan.pk,step_id=step.pk);token=r.json()['data']['proposal_token']
        self.command(plan,'BEGIN_AMEND',reason='实际沟通后追加下一版讨论依据');self.publish_plan(plan)
        r=self.mini_post(c,'mini_plan_decision_confirm',dict(proposal_token=token,confirmed='on'),pk=plan.pk,step_id=step.pk)
        self.assertEqual(r.status_code,409);self.assertFalse(PlanDecision.objects.exists())
    def test_actual_web_preview_does_not_charge_until_confirmation(self):
        c=self.client_for(self.doc);url=reverse('clinical_actual',args=[self.v.pk]);r=c.get(url);data=self.values(r.context['form'])
        data.update(phase='preview',step_version='',treatment_type=self.item.pk,quantity='1',tooth=16,surfaces=['M','O'],progress='COMPLETE',charge_mode='CHARGE',reason='本次计划外已提供实际处置',observed_at='')
        r=c.post(url,data);self.assertEqual(r.status_code,200,r.content);self.assertContains(r,'100.00');self.assertFalse(TreatmentRecord.objects.exists())
        data=self.values(r.context['form']);data.update(phase='confirm',confirmed='on');r=c.post(url,data);self.assertEqual(r.status_code,302,r.content)
        self.assertEqual(PerformedProcedure.objects.count(),1);self.assertEqual(TreatmentRecord.objects.count(),1)
        r=c.get(reverse('care_workspace',args=[self.v.pk]));self.assertContains(r,'登记或核对实际执行');self.assertContains(r,'核对实际执行来源并更正');self.assertNotContains(r,'确认并添加治疗')
    def test_staged_zero_invoice_explains_actual_care_and_no_waiver(self):
        step=self.publish_plan(self.new_plan(charge_basis='ON_COMPLETION')).steps.get();self.decision(step)
        self.actual(step,progress='PARTIAL',charge_mode='NO_CHARGE',reason='明确分阶段治疗，完成时计费')
        self.review();c=self.client_for(self.doc);r=c.get(reverse('care_complete',args=[self.v.pk]))
        self.assertEqual(r.context['form']['outcome'].value(),'TREATED');self.assertContains(r,'不是未治疗')
        data=self.values(r.context['form']);data.update(confirmed='on',outcome='TREATED');r=c.post(reverse('care_complete',args=[self.v.pk]),data)
        self.assertEqual(r.status_code,302,r.content);invoice=Invoice.objects.get();r=c.get(reverse('invoice_detail',args=[invoice.pk]))
        self.assertContains(r,'本次已提供阶段治疗');self.assertNotContains(r,'未实施治疗');self.assertNotContains(r,'PRIVATE_PLAN_EXAM');self.assertNotContains(r,'申请数量／单价更正')
    def test_frontdesk_can_link_without_reading_clinical_target(self):
        row=self.instruction();later=self.booking(start=self.t+timedelta(hours=1));c=self.client_for(self.front);url=reverse('clinical_next_link',args=[row.pk])
        r=c.get(url);self.assertEqual(r.status_code,200,r.content);self.assertNotContains(r,'PRIVATE_NEXT_PURPOSE')
        r=c.post(url,dict(phase='preview',visit=later.pk));self.assertEqual(r.status_code,200,r.content);self.assertFalse(PlanAppointment.objects.exists())
        data=self.values(r.context['form']);data.update(phase='confirm',confirmed='on');r=c.post(url,data);self.assertEqual(r.status_code,302,r.content);self.assertEqual(PlanAppointment.objects.count(),1)
    def test_plan_history_read_is_logged_without_clinical_text(self):
        plan=self.new_plan();self.publish_plan(plan);c=self.client_for(self.patient_user)
        self.assertEqual(c.get(reverse('portal_plan',args=[plan.pk])).status_code,200)
        self.assertEqual(c.get(reverse('mini_plan',args=[plan.pk])).status_code,200)
        rows=SensitiveReadEvent.objects.filter(actor=self.patient_user,object_kind='PLAN');self.assertEqual(rows.count(),2)
        self.assertNotIn('PRIVATE_PLAN',str(list(rows.values())));self.assertEqual(set(rows.values_list('outcome',flat=True)),{'ALLOW'})
