"""C2.3 website work, minimal projections and exact service authority over PG."""
from datetime import timedelta
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from care.models import Invoice,TreatmentRecord
from clinical import recall,plans,laboratory
from clinical.continuity_models import RecallEpisode,LabCase,LabReview
from clinical.models import SensitiveReadEvent
from clinical.plan_models import PlanDecision
from finance.cash_models import CashEntry
from scheduling.models import BookingService
from tests.test_recall_laboratory import ContinuityFixture
from tests.workspace_client import WorkspaceClient


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class RecallLaboratoryHTTPTests(ContinuityFixture,TransactionTestCase):
    def setUp(self):self.setup_continuity()
    def client_for(self,user):
        client=WorkspaceClient();client.force_login(user);return client
    def values(self,form):return {f.name:f.value() if f.value() is not None else '' for f in form}
    def confirm_page(self,c,url,page,**extra):
        values=self.values(page.context['form']);values.update(phase='confirm',confirmed='on',**extra)
        return c.post(url,values)
    def future_due(self):return timezone.localtime(timezone.now()+timedelta(hours=2)).strftime('%Y-%m-%dT%H:%M:%S')
    def test_frontdesk_claim_preview_and_recorded_contact_are_separate(self):
        instruction=self.instruction();c=self.client_for(self.front);url=reverse('clinical_recall_claim',args=[instruction.pk])
        self.assertContains(c.get(reverse('frontdesk_home')),'复诊随访与责任')
        r=c.get(url);self.assertEqual(r.status_code,200,r.content);self.assertNotContains(r,'PRIVATE_NEXT_PURPOSE')
        r=c.post(url,dict(phase='preview',followup_due_at=self.future_due(),note='PRIVATE_CONTACT_RESPONSIBILITY'));self.assertEqual(r.status_code,200,r.content);self.assertFalse(RecallEpisode.objects.exists())
        self.assertEqual(self.confirm_page(c,url,r,note='FORGED_NEW_NOTE').status_code,302);row=RecallEpisode.objects.get()
        self.assertEqual(row.events.get().note,'PRIVATE_CONTACT_RESPONSIBILITY')
        url=reverse('clinical_recall_action',args=[row.pk,'contact']);r=c.post(url,dict(phase='preview',outcome='NO_ANSWER',note='PRIVATE_CONTACT_NO_ANSWER',followup_due_at=self.future_due()))
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(self.confirm_page(c,url,r).status_code,302)
        row.refresh_from_db();self.assertEqual(row.state,'OPEN');self.assertContains(c.get(reverse('clinical_recall_detail',args=[row.pk])),'PRIVATE_CONTACT_NO_ANSWER')
    def test_real_completion_page_lists_only_actual_defined_evidence(self):
        instruction=self.instruction();row=self.open_recall(instruction);visit=self.scheduled_followup(instruction);c=self.client_for(self.front)
        url=reverse('clinical_recall_action',args=[row.pk,'complete']);r=c.get(url);self.assertEqual(r.status_code,200);self.assertEqual(list(r.context['form'].fields['evidence'].choices),[])
        self.close_followup(visit);r=c.get(url);choices=r.context['form'].fields['evidence'].choices;self.assertEqual(len(choices),1)
        r=c.post(url,dict(phase='preview',evidence=choices[0][0],note='核对实际完成结果'));self.assertEqual(r.status_code,200,r.content)
        self.assertEqual(self.confirm_page(c,url,r).status_code,302);row.refresh_from_db();self.assertEqual(row.state,'COMPLETED')
    def test_lab_frontdesk_projection_and_preview_do_not_disclose_clinical_text(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);c=self.client_for(self.front)
        for name,args in [('clinical_labs',[]),('clinical_lab_detail',[case.pk])]:
            r=c.get(reverse(name,args=args));self.assertEqual(r.status_code,200,r.content);self.assertNotContains(r,'PRIVATE_LAB_SPECIFICATION');self.assertNotContains(r,'PRIVATE_PLAN_GOAL')
        for action in ('claim','dispatch','receive'):
            url=reverse('clinical_lab_action',args=[case.pk,action]);r=c.post(url,dict(phase='preview',note='手工核对本次送返',reference='SYNTHETIC-WEB-LAB',occurred_at='',followup_due_at=self.future_due()))
            self.assertEqual(r.status_code,200,r.content);self.assertNotContains(r,'PRIVATE_LAB_SPECIFICATION');self.assertEqual(self.confirm_page(c,url,r,findings='FORGED_CLINICAL_ACCEPTANCE').status_code,302)
        case.refresh_from_db();self.assertEqual(case.state,'RECEIVED');self.assertFalse(LabReview.objects.exists());self.assertFalse(TreatmentRecord.objects.exists())
    def test_doctor_lab_request_and_acceptance_have_attributed_preview(self):
        plan,step=self.accepted_step(requires_lab=True);c=self.client_for(self.doc);url=reverse('clinical_doctor_labs',args=[self.v.pk]);r=c.get(url)
        data=self.values(r.context['form']);data.update(phase='preview',step_version=step.pk,work_kind='RESTORATION',vendor_name='合成手工加工方',specification='PRIVATE_HTTP_LAB_SPEC',logistics_note='前台仅核对手工交接号',needed_on=(timezone.localdate()+timedelta(days=3)).isoformat())
        r=c.post(url,data);self.assertEqual(r.status_code,200,r.content);self.assertFalse(LabCase.objects.exists());self.assertContains(r,'PRIVATE_HTTP_LAB_SPEC')
        self.assertEqual(self.confirm_page(c,url,r,specification='FORGED_REPLACEMENT_SPEC').status_code,302);case=LabCase.objects.get();self.assertEqual(case.specification,'PRIVATE_HTTP_LAB_SPEC')
        for action in ('CLAIM','DISPATCH','RECEIVE'):case=self.lab_action(case,action)
        url=reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'review']);r=c.get(url);data=self.values(r.context['form'])
        data.update(phase='preview',target_step_version=step.pk,decision='ACCEPTED',findings='PRIVATE_HTTP_LAB_REVIEW',coordination_note='已完成本周期核对',assessed_at='')
        r=c.post(url,data);self.assertEqual(r.status_code,200,r.content);self.assertFalse(LabReview.objects.exists());self.assertEqual(self.confirm_page(c,url,r).status_code,302)
        case.refresh_from_db();self.assertEqual(case.state,'ACCEPTED');self.assertEqual(LabReview.objects.get().findings,'PRIVATE_HTTP_LAB_REVIEW');self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_frontdesk_cannot_enter_doctor_acceptance_or_change_clinical_need(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);c=self.client_for(self.front)
        self.assertEqual(c.get(reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'review'])).status_code,403)
        self.assertEqual(c.post(reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'review']),dict(phase='confirm',confirmed='on')).status_code,403)
        self.assertEqual(c.get(reverse('clinical_lab_action',args=[case.pk,'review'])).status_code,404)
        self.assertFalse(LabReview.objects.exists())
    def test_seven_roles_keep_coordination_and_management_distinct(self):
        self.open_recall(self.instruction());plan,step=self.accepted_step(requires_lab=True);self.lab_request(step)
        hq=UserAccount.objects.create_user(username='c23_hq');RoleAssignment.objects.create(user=hq,role='HQ',scope_kind='CHAIN')
        finance=UserAccount.objects.create_user(username='c23_finance');RoleAssignment.objects.create(user=finance,role='FINANCE',scope_kind='CHAIN')
        for actor in (self.front,self.doc,self.manager,hq,finance,self.tech,self.patient_user):
            c=self.client_for(actor)
            with self.subTest(actor=actor.username):
                self.assertEqual(c.get(reverse('clinical_recalls')).status_code,200 if actor.pk==self.front.pk else 403)
                self.assertEqual(c.get(reverse('clinical_doctor_labs',args=[self.v.pk])).status_code,200 if actor.pk==self.doc.pk else 403)
                r=c.get(reverse('clinical_coordination_summary'));self.assertEqual(r.status_code,200 if actor.pk in (self.manager.pk,hq.pk) else 403)
                if r.status_code==200:
                    for private in ('PRIVATE_NEXT_PURPOSE','PRIVATE_LAB_SPECIFICATION',self.v.patient.patient_no):self.assertNotContains(r,private)
    def test_patient_released_progress_omits_frontdesk_notes_and_lab_specifications(self):
        plan,step=self.accepted_step(requires_lab=True);instruction=self.instruction(step_version=step.pk);row=self.open_recall(instruction)
        self.recall_action(row,'CONTACT',note='PRIVATE_CONTACT_INTERNAL',outcome='NO_ANSWER');self.lab_request(step);c=self.client_for(self.patient_user)
        page=c.get(reverse('portal_plan',args=[plan.pk]));self.assertEqual(page.status_code,200,page.content);self.assertContains(page,'尚未全部通过')
        r=c.get(reverse('mini_plan',args=[plan.pk]));self.assertEqual(r.status_code,200);d=r.json()['data'];self.assertFalse(d['steps'][0]['readiness']['ready'])
        for private in ('PRIVATE_CONTACT_INTERNAL','PRIVATE_LAB_SPECIFICATION','PRIVATE_LAB_FINDINGS'):
            self.assertNotContains(page,private);self.assertNotIn(private,str(d))
    def test_other_clinic_has_no_case_contact_or_record_existence_projection(self):
        row=self.open_recall(self.instruction());plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);c=self.client_for(self.front)
        self.assertEqual(c.post(reverse('activate_clinic'),dict(clinic=self.b.pk)).status_code,302)
        for name,pk in [('clinical_recall_detail',row.pk),('clinical_lab_detail',case.pk)]:
            r=c.get(reverse(name,args=[pk]));self.assertEqual(r.status_code,404);self.assertNotContains(r,self.v.patient.patient_no,status_code=404)
    def test_revoked_frontdesk_confirmation_does_not_create_contact(self):
        row=self.open_recall(self.instruction());c=self.client_for(self.front);url=reverse('clinical_recall_action',args=[row.pk,'contact'])
        page=c.post(url,dict(phase='preview',outcome='NO_ANSWER',note='PRIVATE_NOT_COMMITTED',followup_due_at=self.future_due()));self.assertEqual(page.status_code,200)
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        response=self.confirm_page(c,url,page);self.assertIn(response.status_code,(403,409));self.assertEqual(row.events.count(),1)
    def test_role_and_service_denial_cannot_be_bypassed_by_direct_plan_or_lab_url(self):
        service=BookingService.objects.create(department=self.department,code='SCOPE-Y',name='仅乙服务范围',duration_minutes=30);service.dentists.add(self.d1)
        authority=self.authorize(service=service.pk);plan,step=self.accepted_step(service=service.pk,requires_lab=True);case=self.lab_request(step)
        self.decide(authority,'REVOKE');c=self.client_for(self.doc)
        r=c.get(reverse('clinical_plan_detail',args=[self.v.pk,plan.pk]));self.assertEqual(r.status_code,403);self.assertNotContains(r,'PRIVATE_PLAN_GOAL',status_code=403)
        r=c.get(reverse('clinical_plans',args=[self.v.pk]));self.assertEqual(r.status_code,200);self.assertNotContains(r,'PRIVATE_PLAN_SUMMARY')
        self.assertEqual(c.get(reverse('clinical_plan_decision',args=[self.v.pk,step.pk])).status_code,403)
        r=c.get(reverse('clinical_doctor_labs',args=[self.v.pk]));self.assertEqual(r.status_code,200);self.assertNotContains(r,'PRIVATE_LAB_SPECIFICATION')
        self.assertEqual(c.get(reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'withdraw'])).status_code,404)
        with self.assertRaises(PermissionDenied):plans.prepare_decision(actor=self.doc,step_id=step.pk,visit_id=self.v.pk,fields=dict(decision='ACCEPTED',reference='不可跨服务记录'))
        with self.assertRaises(PermissionDenied):laboratory.prepare_lab(actor=self.doc,action='WITHDRAW',visit_id=self.v.pk,case_id=case.pk,fields=dict(note='不可跨范围撤回'))
    def test_sensitive_read_metadata_excludes_contact_and_clinical_text(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step);c=self.client_for(self.doc)
        self.assertEqual(c.get(reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'review'])).status_code,200)
        event=SensitiveReadEvent.objects.filter(actor=self.doc,object_kind='LAB').latest('pk');self.assertEqual(event.object_id,case.pk);self.assertEqual(event.outcome,'ALLOW')
        self.assertNotIn('PRIVATE_LAB',str(list(SensitiveReadEvent.objects.values())))
    def test_doctor_review_queue_retains_work_after_source_visit_closes(self):
        from care.services import complete_visit
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);self.v.refresh_from_db()
        complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='NO_TREATMENT',reason='本次实际检查后等待加工准备，尚未实施治疗')
        for action in ('CLAIM','DISPATCH','RECEIVE'):case=self.lab_action(case,action)
        c=self.client_for(self.doc);r=c.get(reverse('clinical_doctor_lab_queue'));self.assertEqual(r.status_code,200,r.content);self.assertContains(r,case.case_no)
        self.assertContains(c.get(reverse('doctor_home')),'已返回待验收 1 项')
        self.assertEqual(c.get(reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'review'])).status_code,200)
    def test_read_only_professional_scope_can_read_case_but_not_open_review_action(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step);self.decide(self.authority,'REVOKE');self.authorize(can_record=False)
        c=self.client_for(self.doc);self.assertEqual(c.get(reverse('clinical_doctor_labs',args=[self.v.pk])).status_code,200)
        self.assertEqual(c.get(reverse('clinical_doctor_lab_action',args=[self.v.pk,case.pk,'review'])).status_code,403)
    @override_settings(ADC_READ_ONLY=True)
    def test_read_only_instance_keeps_coordination_readable_and_refuses_effect(self):
        # Build the fixture outside read-only mode; no setting bypass in the command.
        with override_settings(ADC_READ_ONLY=False):
            row=self.open_recall(self.instruction());c=self.client_for(self.front)
            url=reverse('clinical_recall_action',args=[row.pk,'contact']);p=c.post(url,dict(phase='preview',outcome='NO_ANSWER',note='未提交的只读联系',followup_due_at=self.future_due()))
        self.assertEqual(c.get(reverse('clinical_recall_detail',args=[row.pk])).status_code,200)
        self.assertEqual(p.status_code,200);self.assertEqual(self.confirm_page(c,url,p).status_code,403);self.assertEqual(row.events.count(),1)
