"""C3.2B1 PostgreSQL contract and website/native authority evidence."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import DatabaseError, close_old_connections, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice, TreatmentRecord, AuditEvent
from clinical import consents
from clinical.consent_models import MedicalConsent, ConsentVersion, ConsentEvent
from clinical.consent_selectors import details
from clinical.disclosures import FIELDS
from clinical.plan_models import PlanDraft, PlanDecision, PerformedProcedure
from finance.cash_models import CashEntry
from portal.models import PatientAccess, PatientRelationship, PatientAppointmentGrant
from tests.test_treatment_continuity import PlanFixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalConsentTests(PlanFixture, TransactionTestCase):
    def setUp(self):
        self.setup_plan();self.plan=self.new_plan()
        self.notice(self.plan);self.step=self.publish_plan(self.plan).steps.get()
        self.decision(self.step)

    def notice(self, plan):
        raw=PlanDraft.objects.get(plan=plan).payload['steps'][0]
        self.command(plan,'DISCLOSURE',**dict({key:'PRIVATE_CONSENT_'+key for key,_,_ in FIELDS},
            sequence=1,step_key=raw['step_key'],prepared=True))

    def preview(self, action, *, actor=None, step=None, **fields):
        actor=actor or self.patient_user
        return consents.prepare(actor=actor,action=action,step_id=(step or self.step).pk,
            visit_id=self.v.pk if actor.pk==self.doc.pk else None,fields=fields)

    def do(self, action, *, actor=None, **fields):
        actor=actor or self.patient_user;p=self.preview(action,actor=actor,**fields)
        return consents.confirm(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]

    def publish(self, **fields):
        return self.do('PUBLISH',actor=self.doc,identity_reference='SYNTHETIC-SELF-CHECK-REF',self_qualified=True,**fields)

    def test_preview_is_read_only_and_first_publish_has_exact_source(self):
        p=self.preview('PUBLISH',actor=self.doc,identity_reference='SYNTHETIC-REF',self_qualified=True)
        self.assertFalse(MedicalConsent.objects.exists())
        event=consents.confirm(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertEqual(event.version.step_version_id,self.step.pk)
        self.assertEqual(event.version.source_record_id,self.step.version.source_record_id)
        self.assertEqual(event.version.prepared_by_id,self.doc.pk)

    def test_self_decision_retains_evidence_without_changing_scheme_care_or_money(self):
        before=list(PlanDecision.objects.values());self.publish();event=self.do('AGREED')
        self.assertEqual(event.source,'SELF_ACCOUNT');self.assertEqual(event.self_access.user_id,self.patient_user.pk)
        self.assertEqual(list(PlanDecision.objects.values()),before)
        for model in (PerformedProcedure,TreatmentRecord,Invoice,CashEntry):self.assertFalse(model.objects.exists())
        self.assertEqual(details(self.patient_user,self.step.pk)['data']['status'],'本人同意')

    def test_question_requires_answer_and_answer_is_not_consent(self):
        self.publish();question=self.do('QUESTION',text='PRIVATE_NEW_QUESTION')
        with self.assertRaises(RuleError):self.preview('AGREED')
        answer=self.do('ANSWER',actor=self.doc,reply_to=question.pk,text='PRIVATE_DOCTOR_ANSWER')
        self.assertEqual(answer.reply_to_id,question.pk)
        self.assertFalse(ConsentEvent.objects.filter(action='AGREED').exists())
        self.assertEqual(self.do('AGREED').action,'AGREED')

    def test_decline_defer_and_withdraw_are_explicit_and_do_not_cancel_visit(self):
        self.publish();self.do('DECLINED',text='希望讨论其他安排')
        with self.assertRaises(RuleError):self.preview('AGREED')
        self.publish(amendment_reason='再次说明患者关切与新的决定机会')
        self.do('DEFERRED',text='留出考虑时间')
        self.publish(amendment_reason='患者复核后重新告知')
        self.do('AGREED');self.do('WITHDRAWN',text='未实施部分暂不接受')
        self.v.refresh_from_db();self.assertEqual(self.v.status,'CHECKED_IN')
        self.assertEqual(ConsentEvent.objects.filter(action__in=consents.DECISIONS).count(),4)

    def test_new_explanation_does_not_inherit_old_agreement(self):
        old=self.publish();self.do('AGREED')
        new=self.publish(amendment_reason='重新核对具体范围及原问题')
        d=details(self.patient_user,self.step.pk)['data'];self.assertEqual(d['status'],'待本人决定')
        self.assertEqual(new.version.previous_id,old.version_id)
        self.assertTrue(details(self.patient_user,self.step.pk,revision=1)['data']['can_withdraw'])

    def test_old_agreement_can_be_withdrawn_without_affecting_new_version(self):
        old=self.publish();self.do('AGREED');self.publish(amendment_reason='新告知仍待本人决定')
        p=consents.prepare(actor=self.patient_user,action='WITHDRAWN',step_id=self.step.pk,version_id=old.version_id,fields={'text':'撤回旧版未实施部分'})
        consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(details(self.patient_user,self.step.pk)['data']['status'],'待本人决定')
        self.assertEqual(details(self.patient_user,self.step.pk,revision=1)['data']['status'],'撤回同意')

    def test_unanswered_questions_survive_republication(self):
        self.publish();self.do('QUESTION',text='仍需明确的具体问题')
        self.publish(amendment_reason='重新告知也不能丢弃未回答问题')
        with self.assertRaises(RuleError):self.preview('AGREED')

    def test_stale_preview_and_same_operation_replay(self):
        self.publish();p=self.preview('AGREED');self.do('QUESTION',text='提交预览后又提出新疑问')
        with self.assertRaises(RuleError):consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        p=self.preview('DEFERRED',text='等待答复后再考虑')
        first=consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)[0]
        again,replay=consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(first.pk,again.pk)

    def test_publisher_revoke_blocks_agreement_but_allows_withdrawal(self):
        self.publish();p=self.preview('AGREED');self.decide(self.authority,'REVOKE')
        with self.assertRaises(PermissionDenied):consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(self.do('DECLINED',text='等待合适医师继续沟通').action,'DECLINED')

    def test_revoke_does_not_prevent_withdrawal_of_retained_agreement(self):
        self.publish();self.do('AGREED');self.decide(self.authority,'REVOKE')
        self.assertEqual(self.do('WITHDRAWN',text='撤回未实施部分的同意').action,'WITHDRAWN')

    def test_appointment_guardian_does_not_acquire_medical_consent(self):
        self.publish();guardian=UserAccount.objects.create_user(username='consent_guardian')
        relation=PatientRelationship.objects.create(clinic=self.a,patient=self.v.patient,related_name='合成监护人',kind='GUARDIAN',
            delegate_user=guardian,state='VERIFIED',created_by=self.front)
        grant=PatientAppointmentGrant.objects.create(relationship=relation,created_by=self.front,
            valid_from=timezone.now()-timedelta(days=1),valid_until=timezone.now()+timedelta(days=2))
        self.ctx(guardian,'PATIENT');guardian._adc_workspace.patient_grant=grant;guardian._adc_workspace.save(update_fields=['patient_grant'])
        with self.assertRaises(PermissionDenied):details(guardian,self.step.pk)
        with self.assertRaises(PermissionDenied):self.preview('AGREED',actor=guardian)

    def test_other_chain_roles_do_not_inherit_clinical_access(self):
        self.publish()
        for role in ('FINANCE','HQ'):
            user=UserAccount.objects.create_user(username='consent_'+role.lower())
            RoleAssignment.objects.create(user=user,role=role,scope_kind='CHAIN')
            self.ctx(user,role)
            with self.assertRaises(PermissionDenied):details(user,self.step.pk)

    def test_new_plan_version_requires_new_scheme_choice_and_medical_offer(self):
        old=self.publish();self.do('AGREED');self.command(self.plan,'BEGIN_AMEND',reason='具体方案内容发生变化')
        self.command(self.plan,'NOTES',summary='改变后的实际治疗范围');self.notice(self.plan)
        new=self.publish_plan(self.plan).steps.get()
        with self.assertRaises(RuleError):self.preview('AGREED')
        with self.assertRaises(RuleError):self.preview('PUBLISH',actor=self.doc,step=new,identity_reference='SYNTHETIC-RECHECK',self_qualified=True,amendment_reason='新方案重新告知')
        self.decision(new)
        p=self.preview('PUBLISH',actor=self.doc,step=new,identity_reference='SYNTHETIC-RECHECK',self_qualified=True,amendment_reason='新方案重新告知')
        fresh=consents.confirm(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertEqual(fresh.version.previous_id,old.version_id)
        self.assertEqual(details(self.patient_user,new.pk)['data']['status'],'待本人决定')

    def test_doctor_question_queue_tracks_unanswered_without_fabricating_consent(self):
        self.publish();question=self.do('QUESTION',text='需要负责医师核对的具体问题')
        client=WorkspaceClient();client.force_login(self.doc)
        self.assertContains(client.get(reverse('clinical_consent',args=[self.v.pk,self.step.pk])),'医疗告知与本人决定')
        self.assertContains(client.get(reverse('clinical_consents')),'有未答复疑问')
        self.do('ANSWER',actor=self.doc,reply_to=question.pk,text='已向患者说明具体安排')
        self.assertContains(client.get(reverse('clinical_consents')),'当前没有待办理事项')
        self.assertFalse(ConsentEvent.objects.filter(action='AGREED').exists())

    def test_revoked_patient_authority_blocks_pending_confirmation(self):
        self.publish();p=self.preview('AGREED');PatientAccess.objects.filter(user=self.patient_user).update(is_active=False)
        with self.assertRaises(PermissionDenied):consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(ConsentEvent.objects.filter(action='AGREED').exists())

    def test_other_patient_and_nonclinical_roles_cannot_read_or_decide(self):
        self.publish();other=UserAccount.objects.create_user(username='consent_other')
        PatientAccess.objects.create(user=other,patient=self.p2);self.ctx(other,'PATIENT')
        for actor in (self.front,self.manager,self.tech,other):
            with self.subTest(actor=actor.pk),self.assertRaises((PermissionDenied,ObjectDoesNotExist)):
                details(actor,self.step.pk)

    def test_doctor_cannot_impersonate_patient_click(self):
        self.publish()
        with self.assertRaises(PermissionDenied):self.preview('AGREED',actor=self.doc)

    def test_paper_original_is_explicit_with_two_timestamps(self):
        self.publish();event=self.do('AGREED',actor=self.doc,paper=True,paper_verified=True,
            reference='SYNTHETIC-PAPER-001',occurred_at=timezone.now().isoformat())
        self.assertEqual(event.source,'PAPER_REFERENCE');self.assertIsNone(event.self_access_id)
        self.assertLessEqual(event.occurred_at,event.recorded_at)
        self.assertEqual(event.actor_id,self.doc.pk)

    def test_paper_missing_reference_future_or_preversion_time_rejected(self):
        event=self.publish()
        for values in ({'reference':''},{'occurred_at':(timezone.now()+timedelta(days=1)).isoformat()},
                       {'occurred_at':(event.version.recorded_at-timedelta(minutes=1)).isoformat()}):
            fields=dict(paper=True,paper_verified=True,reference='SYNTHETIC-PAPER',occurred_at=timezone.now().isoformat());fields.update(values)
            with self.assertRaises(RuleError):self.preview('AGREED',actor=self.doc,**fields)

    def test_versions_events_and_head_identity_are_retained_in_postgresql(self):
        event=self.publish()
        for fn in (lambda:ConsentVersion.objects.filter(pk=event.version_id).update(identity_reference='replacement'),
                   lambda:ConsentEvent.objects.filter(pk=event.pk).update(text='replacement'),
                   lambda:MedicalConsent.objects.filter(pk=event.consent_id).update(opened_by=self.patient_user)):
            with self.assertRaises(DatabaseError),transaction.atomic():fn()

    def test_questions_answer_only_once_and_same_case(self):
        self.publish();q=self.do('QUESTION',text='请说明具体风险');self.do('ANSWER',actor=self.doc,reply_to=q.pk,text='医师具体答复')
        with self.assertRaises(RuleError):self.preview('ANSWER',actor=self.doc,reply_to=q.pk,text='第二次覆盖')

    def test_actual_identity_changes_require_clinician_recheck(self):
        self.publish();p=self.preview('AGREED');self.v.patient.name='更正后的姓名';self.v.patient.save(update_fields=['name'])
        with self.assertRaises(RuleError):consents.confirm(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)

    def test_missing_attestation_or_minor_does_not_publish_self_offer(self):
        with self.assertRaises(RuleError):self.preview('PUBLISH',actor=self.doc,identity_reference='仅提供微信身份')
        self.v.patient.date_of_birth=timezone.localdate()-timedelta(days=365*12);self.v.patient.save(update_fields=['date_of_birth'])
        with self.assertRaises(RuleError):self.publish()
        self.assertFalse(MedicalConsent.objects.exists())

    def test_audit_contains_only_metadata_not_clinical_question(self):
        self.publish();self.do('QUESTION',text='PRIVATE_QUESTION_NOT_IN_LOG')
        rows=AuditEvent.objects.filter(event_type__startswith='MEDICAL_CONSENT_')
        self.assertEqual(rows.count(),2);self.assertNotIn('PRIVATE_QUESTION',str(list(rows.values())))

    def test_parallel_confirmations_create_one_decision(self):
        self.publish();previews=[self.preview('AGREED')['proposal_token'] for _ in range(2)]
        user=self.patient_user.pk;context=self.patient_user._adc_workspace.pk;gate=Barrier(2)
        def submit(token):
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=user);actor._adc_workspace=WorkspaceContext.objects.get(pk=context);gate.wait(timeout=20)
                try:return consents.confirm(actor=actor,proposal_token=token,confirmed=True)[0].pk
                except RuleError:return None
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,previews))
        self.assertEqual(sum(x is not None for x in results),1);self.assertEqual(ConsentEvent.objects.filter(action='AGREED').count(),1)

    def test_website_and_native_use_same_decision_history(self):
        self.publish();client=WorkspaceClient();client.force_login(self.patient_user)
        path=reverse('mini_consent',args=[self.step.pk]);response=client.get(path)
        self.assertEqual(response.status_code,200);self.assertEqual(len(response.json()['data']['disclosure']['fields']),8)
        p=client.post(reverse('mini_consent_preview',args=[self.step.pk]),{'action':'QUESTION','text':'PRIVATE_HTTP_QUESTION'},HTTP_X_ADC_WORKSPACE=client.current_token())
        self.assertEqual(p.status_code,200,p.content)
        token=p.json()['data']['proposal_token'];r=client.post(reverse('mini_consent_confirm',args=[self.step.pk]),{'proposal_token':token,'confirmed':'on'},HTTP_X_ADC_WORKSPACE=client.current_token())
        self.assertEqual(r.status_code,200,r.content)
        self.assertContains(client.get(reverse('portal_consent',args=[self.step.pk])),'PRIVATE_HTTP_QUESTION')
