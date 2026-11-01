"""Medical representation and actual pre-treatment control on PostgreSQL."""
import uuid
from datetime import timedelta,date
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.core.exceptions import PermissionDenied
from django.db import transaction,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice,TreatmentRecord
from care.services import add_treatment
from clinical import consents,plans,executions,preflight
from clinical.consent_models import ConsentVersion,ConsentEvent
from clinical.disclosures import FIELDS
from clinical.plan_models import PlanDraft,PlanDecision,PerformedProcedure
from clinical.preflight_models import TreatmentPreflight,ProcedureGap,ProcedureGapReview
from portal import medical_proxies as proxies
from portal.medical_models import MedicalProxy,MedicalProxyVersion,MedicalProxyScope,MedicalProxyEvent
from portal.medical_authority import latest_version
from portal.relationships import select_subject
from portal.policies import patient_access,subject_choices
from registry.models import TreatmentType
from tests.test_treatment_continuity import PlanFixture


class MedicalFixture(PlanFixture):
    def setup_medical(self):
        self.setup_plan();self.plan=self.new_plan();raw=PlanDraft.objects.get(plan=self.plan).payload['steps'][0]
        self.command(self.plan,'DISCLOSURE',**dict({k:'SYNTHETIC_DETAIL_'+k for k,_,_ in FIELDS},sequence=1,step_key=raw['step_key'],prepared=True))
        self.step=self.publish_plan(self.plan).steps.get()
        self.delegate=UserAccount.objects.create_user(username='medical_delegate',password='synthetic-medical-only')
        self.ctx(self.front,'FRONT_DESK',self.a)
        RoleAssignment.objects.filter(user=self.front,clinic=self.a,role='FRONT_DESK').update(can_verify_medical_proxy_identity=True)

    def proxy_fields(self,**changes):
        now=timezone.now();d=dict(patient_no=self.v.patient.patient_no,username=self.delegate.username,delegate_name='合成代理林亲属',kind='WRITTEN',plan=self.plan.pk,
            steps=[self.step.step_id],identity_reference='SYNTHETIC-ID-REFERENCE',authority_reference='SYNTHETIC-WRITTEN-ORIGINAL',
            applicability='课程合成：本人具备表达条件但因本次病情无法签字，核对本次书面委托范围。',valid_from=(now-timedelta(minutes=1)).isoformat(),valid_until=(now+timedelta(days=3)).isoformat())
        d.update(changes);return d

    def submit(self,**changes):
        p=proxies.prepare_submit(actor=self.front,fields=self.proxy_fields(**changes))
        return proxies.confirm(actor=self.front,**p,confirmed=True)[0]

    def proxy_action(self,case,action,actor=None,applicable=True):
        actor=actor or (self.front if action=='MATERIALS_OK' else self.doc)
        p=proxies.prepare_action(actor=actor,case_id=case.pk,action=action,note='课程合成：已核对本次材料或医疗适用性及具体范围',applicable=applicable)
        return proxies.confirm(actor=actor,**p,confirmed=True)[0]

    def approved_proxy(self,**changes):
        case=self.submit(**changes);self.proxy_action(case,'MATERIALS_OK');self.proxy_action(case,'APPROVE')
        self.ctx(self.delegate,'PATIENT');select_subject(actor=self.delegate,key=f'medical:{case.pk}')
        case.refresh_from_db();return case

    def scheme(self,actor=None,**extra):
        actor=actor or self.delegate
        p=plans.prepare_decision(actor=actor,step_id=self.step.pk,fields=dict(decision='ACCEPTED',note='',**extra))
        return plans.confirm_decision(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]

    def medical(self,action,actor=None,**values):
        actor=actor or self.delegate
        p=consents.prepare(actor=actor,action=action,step_id=self.step.pk,visit_id=self.v.pk if actor.pk==self.doc.pk else None,fields=values)
        return consents.confirm(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]

    def offer_proxy(self,case):
        return self.medical('PUBLISH',actor=self.doc,identity_reference='SYNTHETIC-MEDICAL-APPLICABILITY',proxy_version=latest_version(case).pk,proxy_verified=True)

    def self_agreement(self):
        self.decision(self.step)
        self.medical('PUBLISH',actor=self.doc,identity_reference='SYNTHETIC-SELF-QUALIFIED',self_qualified=True)
        return self.medical('AGREED',actor=self.patient_user)

    def control(self,mode='CONSENT'):
        for item in TreatmentType.objects.filter(is_active=True):
            p=preflight.prepare_rule(actor=self.reviewer,clinic_id=self.a.pk,treatment_id=item.pk,
                mode=mode if item.pk==self.item.pk else 'REVIEW',reference='SYNTHETIC-CLINICAL-RULE',explanation='课程合成：按实际项目明确沟通和同意要求，不推定真实资格。')
            preflight.confirm_rule(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        p=preflight.prepare_rule(actor=self.reviewer,clinic_id=self.a.pk,reference='SYNTHETIC-CONTROL-ACTIVATION',activate=True)
        preflight.confirm_rule(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)

    def check(self,**extra):
        p=preflight.prepare(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(self.step),**extra)
        return preflight.confirm(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalProxyTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()

    def test_materials_and_clinical_approval_are_separate(self):
        case=self.submit();self.assertEqual(case.state,'MATERIALS');self.assertFalse(MedicalProxy.objects.filter(state='ACTIVE').exists())
        with self.assertRaises(RuleError):self.proxy_action(case,'APPROVE')
        self.proxy_action(case,'MATERIALS_OK')
        with self.assertRaises(RuleError):self.proxy_action(case,'APPROVE',applicable=False)

    def test_front_duty_is_explicit_and_does_not_grant_medical_approval(self):
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_medical_proxy_identity=False)
        with self.assertRaises(PermissionDenied):self.submit()

    def test_proxy_scheme_and_medical_decision_do_not_make_treatment_or_money(self):
        case=self.approved_proxy();choice=self.scheme();self.offer_proxy(case);event=self.medical('AGREED')
        self.assertEqual(choice.source,'PROXY');self.assertEqual(event.source,'PROXY_ACCOUNT')
        self.assertEqual(event.proxy_version_id,choice.proxy_version_id)
        from clinical.consent_selectors import details
        self.assertEqual(details(self.delegate,self.step.pk)['data']['events'][-1]['label'],'医疗代理同意')
        self.assertFalse(PerformedProcedure.objects.exists());self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(Invoice.objects.exists())

    def test_only_medical_authority_cannot_book_or_read_full_chart(self):
        case=self.approved_proxy()
        with self.assertRaises(PermissionDenied):patient_access(self.delegate)
        with self.assertRaises(PermissionDenied):patient_access(self.delegate,self_only=True)
        self.assertTrue(next(r for r in subject_choices(self.delegate) if r['key']==f'medical:{case.pk}')['medical'])

    def test_unanswered_proxy_question_is_not_agreement(self):
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        q=self.medical('QUESTION',text='课程合成：代理需要进一步说明本步骤风险。')
        with self.assertRaises(RuleError):self.medical('AGREED')
        answer=self.medical('ANSWER',actor=self.doc,reply_to=q.pk,text='课程合成：针对本步骤说明已答复。')
        self.assertEqual(answer.reply_to_id,q.pk);self.assertFalse(ConsentEvent.objects.filter(action='AGREED').exists())
        self.medical('AGREED')

    def test_guardian_has_an_independent_scope_not_appointment_authority(self):
        self.v.patient.date_of_birth=date(timezone.localdate().year-8,1,1);self.v.patient.save(update_fields=['date_of_birth'])
        case=self.approved_proxy(kind='GUARDIAN');self.scheme();self.offer_proxy(case);event=self.medical('AGREED')
        self.assertEqual(event.version.signer_kind,'PROXY')

    def test_revoke_invalidates_preview_without_rewriting_decisions(self):
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        p=consents.prepare(actor=self.delegate,action='AGREED',step_id=self.step.pk,fields={})
        self.proxy_action(case,'REVOKE',actor=self.front)
        with self.assertRaises((PermissionDenied,RuleError)):consents.confirm(actor=self.delegate,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(ConsentEvent.objects.filter(action='AGREED').exists())

    def test_expired_proxy_cannot_create_new_decision(self):
        from unittest.mock import patch
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        with patch('django.utils.timezone.now',return_value=timezone.now()+timedelta(days=4)):
            with self.assertRaises((PermissionDenied,RuleError)):self.medical('AGREED')

    def test_second_proxy_cannot_silently_replace_current_signer(self):
        case=self.approved_proxy();other=UserAccount.objects.create_user(username='other_medical_delegate')
        second=self.submit(username=other.username);self.proxy_action(second,'MATERIALS_OK')
        with self.assertRaises(RuleError):self.proxy_action(second,'APPROVE')
        case.refresh_from_db();self.assertEqual(case.state,'ACTIVE')

    def test_proxy_cannot_override_existing_patient_refusal(self):
        self.decision(self.step,'DECLINED',note='本人明确不选择此步骤')
        self.approved_proxy()
        with self.assertRaises(RuleError):self.scheme()

    def test_history_and_scope_cannot_be_changed_after_submission(self):
        case=self.submit();v=latest_version(case)
        for call in [lambda:MedicalProxyVersion.objects.filter(pk=v.pk).update(authority_reference='changed'),lambda:MedicalProxyEvent.objects.filter(proxy=case).delete(),lambda:MedicalProxyScope.objects.filter(version=v).delete(),lambda:MedicalProxy.objects.filter(pk=case.pk).update(delegate=self.front)]:
            with self.assertRaises(DatabaseError),transaction.atomic():call()

    def test_proxy_decision_replay_is_one_effect(self):
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        p=consents.prepare(actor=self.delegate,action='AGREED',step_id=self.step.pk,fields={})
        first=consents.confirm(actor=self.delegate,proposal_token=p['proposal_token'],confirmed=True)[0]
        again,replay=consents.confirm(actor=self.delegate,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(first.pk,again.pk)


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class TreatmentPreflightTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical();self.self_agreement();self.control()

    def test_normal_execution_needs_prior_check_and_uses_existing_charge_source(self):
        with self.assertRaises(RuleError):self.actual(self.step)
        check=self.check();self.review();actual=self.actual(self.step,preflight=check.pk)
        self.assertEqual(actual.preflight_id,check.pk);self.assertEqual(TreatmentRecord.objects.count(),1)
        self.assertFalse(Invoice.objects.exists())

    def test_preflight_itself_does_not_create_actual_or_charge(self):
        check=self.check();self.assertTrue(check.pk)
        self.assertFalse(PerformedProcedure.objects.exists());self.assertFalse(TreatmentRecord.objects.exists())

    def test_withdrawal_invalidates_saved_check(self):
        check=self.check();self.medical('WITHDRAWN',actor=self.patient_user,text='本人撤回未实施部分')
        with self.assertRaises(RuleError):self.actual(self.step,preflight=check.pk)

    def test_new_question_invalidates_saved_check(self):
        check=self.check();self.medical('QUESTION',actor=self.patient_user,text='本人对开治范围还有疑问。')
        with self.assertRaises(RuleError):self.actual(self.step,preflight=check.pk)

    def test_actual_time_cannot_be_backdated_before_check(self):
        before=timezone.now();check=self.check()
        with self.assertRaises(RuleError):self.actual(self.step,preflight=check.pk,observed_at=before.isoformat())

    def test_changed_rule_requires_fresh_check(self):
        check=self.check();p=preflight.prepare_rule(actor=self.reviewer,clinic_id=self.a.pk,treatment_id=self.item.pk,mode='REVIEW',reference='SYNTHETIC-NEW-RULE',explanation='课程合成：此项目需要进一步专业判断。')
        preflight.confirm_rule(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):self.actual(self.step,preflight=check.pk)

    def test_old_direct_charge_entry_cannot_bypass_control(self):
        self.v.refresh_from_db()
        with self.assertRaises(RuleError):add_treatment(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,treatment_id=self.item.pk,quantity=1)

    def test_preflight_replay_and_history_retention(self):
        p=preflight.prepare(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(self.step))
        a=preflight.confirm(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
        b,replay=preflight.confirm(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(a.pk,b.pk)
        with self.assertRaises(DatabaseError),transaction.atomic():TreatmentPreflight.objects.filter(pk=a.pk).update(communication='changed')

    def test_historical_fact_is_saved_with_gap_without_fabricating_preflight(self):
        p=executions.prepare_retrospective(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(self.step),gap_reason='课程合成：现场实际完成后发现事前资料缺失，如实补记并交复核。')
        actual=executions.confirm_retrospective(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
        self.assertIsNone(actual.preflight_id);self.assertEqual(actual.preflight_gap.state,'PENDING')
        self.assertEqual(TreatmentRecord.objects.count(),1);self.assertFalse(TreatmentPreflight.objects.exists())
        from clinical.completion import completion_blockers
        self.assertTrue(completion_blockers(self.v))
        with self.assertRaises(PermissionDenied):preflight.prepare_review(actor=self.doc,gap_id=actual.preflight_gap.pk,note_text='本人不能复核自己补记的缺口。')
        from clinical import authority_services as authority
        self.appoint(self.doc,self.a)
        self.ctx(self.doc,'DENTIST')
        proposed=authority.prepare_authority(actor=self.manager,action='PROPOSE',fields=self.fields(user=self.reviewer))
        scope=authority.confirm_authority(actor=self.manager,proposal_token=proposed['proposal_token'],confirmed=True)[0]
        self.decide(scope,'APPROVE',actor=self.doc)
        self.ctx(self.reviewer,'DENTIST')
        p=preflight.prepare_review(actor=self.reviewer,gap_id=actual.preflight_gap.pk,note_text='课程合成：已核对实际发生与材料缺口；不构成事前同意或补签。')
        review=preflight.confirm_review(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)[0]
        actual.preflight_gap.refresh_from_db();self.assertEqual(actual.preflight_gap.state,'REVIEWED')
        self.assertFalse(TreatmentPreflight.objects.exists());self.assertEqual(review.gap.performed_id,actual.pk)

    def test_review_required_rule_does_not_default_to_no_consent(self):
        p=preflight.prepare_rule(actor=self.reviewer,clinic_id=self.a.pk,treatment_id=self.item.pk,mode='REVIEW',reference='SYNTHETIC-UNKNOWN',explanation='尚未明确适用临床规则，须继续专业核对。')
        preflight.confirm_rule(actor=self.reviewer,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):self.check()


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalProxyHTTPTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()
    def client_for(self,user):
        from tests.workspace_client import WorkspaceClient
        c=WorkspaceClient();c.force_login(user);return c
    def choose(self,c,case):
        from django.urls import reverse
        r=c.post(reverse('mini_subject_select'),{'subject':f'medical:{case.pk}'},HTTP_X_ADC_WORKSPACE=c.current_token())
        self.assertEqual(r.status_code,200,r.content)
    def test_medical_only_website_and_native_read_exact_scope_without_booking_gate(self):
        from django.urls import reverse
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        c=self.client_for(self.delegate);self.choose(c,case)
        for route,args in [('portal_medical_authorizations',[]),('portal_medical_proxy',[case.pk]),('portal_plans',[]),('portal_plan',[self.plan.pk]),('portal_consent',[self.step.pk]),('mini_plan',[self.plan.pk]),('mini_consent',[self.step.pk])]:
            with self.subTest(route=route):self.assertEqual(c.get(reverse(route,args=args)).status_code,200)
        data=c.get(reverse('mini_plan',args=[self.plan.pk])).json()['data']
        self.assertNotIn('PRIVATE_PLAN_SUMMARY',str(data));self.assertEqual(data['discussion_note'],'');self.assertEqual(data['steps'][0]['actual_history'],[])
        for route in ('mini_history','mini_visits','mini_catalogue'):
            with self.subTest(route=route):self.assertEqual(c.get(reverse(route)).status_code,403)
        self.assertEqual(c.get('/portal/').status_code,302)
    def test_medical_only_patient_can_confirm_question_over_real_http(self):
        from django.urls import reverse
        case=self.approved_proxy();self.scheme();self.offer_proxy(case);c=self.client_for(self.delegate);self.choose(c,case)
        r=c.post(reverse('mini_consent_preview',args=[self.step.pk]),{'action':'QUESTION','text':'PRIVATE_PROXY_HTTP_QUESTION'},HTTP_X_ADC_WORKSPACE=c.current_token())
        self.assertEqual(r.status_code,200,r.content)
        token=r.json()['data']['proposal_token']
        r=c.post(reverse('mini_consent_confirm',args=[self.step.pk]),{'proposal_token':token,'confirmed':'on'},HTTP_X_ADC_WORKSPACE=c.current_token())
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(ConsentEvent.objects.latest('pk').source,'PROXY_ACCOUNT')
        self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(Invoice.objects.exists())
    def test_front_has_materials_but_no_medical_text_and_manager_cannot_approve(self):
        from django.urls import reverse
        case=self.submit();c=self.client_for(self.front)
        self.assertContains(c.get(reverse('medical_proxy_detail',args=[case.pk])),'SYNTHETIC-WRITTEN-ORIGINAL')
        self.assertNotContains(c.get(reverse('medical_proxy_detail',args=[case.pk])),'PRIVATE_PLAN_CHIEF')
        self.assertEqual(c.get(reverse('clinical_preflight',args=[self.v.pk])).status_code,403)
        m=self.client_for(self.manager)
        for route,args in [('medical_proxy_detail',[case.pk]),('medical_proxies',[]),('clinical_control_rules',[])]:self.assertEqual(m.get(reverse(route,args=args)).status_code,403)
    def test_proxy_cannot_read_unscoped_step_or_other_clinic_record(self):
        from django.urls import reverse
        case=self.approved_proxy();other=self.publish_plan(self.new_plan()).steps.get();c=self.client_for(self.delegate);self.choose(c,case)
        r=c.get(reverse('mini_consent',args=[other.pk]));self.assertEqual(r.status_code,403)
        self.assertEqual(c.get(reverse('mini_plan',args=[other.version.plan_id])).status_code,404)
    def test_self_cannot_click_as_proxy_on_same_disclosure(self):
        from clinical.consent_selectors import details
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        d=details(self.patient_user,self.step.pk)['data'];self.assertFalse(d['can_agree']);self.assertFalse(d['can_decide'])
        with self.assertRaises((PermissionDenied,RuleError)):self.medical('AGREED',actor=self.patient_user)
    def test_approval_does_not_survive_front_duty_revocation(self):
        case=self.submit();p=proxies.prepare_action(actor=self.front,case_id=case.pk,action='MATERIALS_OK',note='核对身份原件与独立授权材料')
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_medical_proxy_identity=False)
        with self.assertRaises(PermissionDenied):proxies.confirm(actor=self.front,**p,confirmed=True)
        case.refresh_from_db();self.assertEqual(case.state,'MATERIALS')
    def test_return_resubmission_preserves_original_and_current_scope(self):
        case=self.submit();self.proxy_action(case,'MATERIALS_OK');self.proxy_action(case,'RETURN')
        original=latest_version(case);case.refresh_from_db()
        p=proxies.prepare_submit(actor=self.front,case_id=case.pk,fields=self.proxy_fields(authority_reference='SYNTHETIC-SUPPLEMENT-ORIGINAL'))
        proxies.confirm(actor=self.front,**p,confirmed=True)
        self.assertEqual(case.versions.count(),2);original.refresh_from_db();self.assertEqual(original.authority_reference,'SYNTHETIC-WRITTEN-ORIGINAL')
    def test_same_person_cannot_switch_from_materials_to_medical_approval(self):
        RoleAssignment.objects.create(user=self.doc,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a,can_verify_medical_proxy_identity=True)
        self.ctx(self.doc,'FRONT_DESK',self.a)
        p=proxies.prepare_submit(actor=self.doc,fields=self.proxy_fields());case=proxies.confirm(actor=self.doc,**p,confirmed=True)[0]
        self.proxy_action(case,'MATERIALS_OK',actor=self.doc);self.ctx(self.doc,'DENTIST')
        with self.assertRaises(PermissionDenied):self.proxy_action(case,'APPROVE',actor=self.doc)


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalProxyConcurrencyTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()
    def parallel(self,jobs):
        from workspaces.models import WorkspaceContext
        gate=Barrier(len(jobs))
        def run(job):
            user,ctx,handler,kwargs=job;close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=user);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctx);gate.wait(timeout=20)
                try:return ('ok',handler(actor=actor,**kwargs)[0].pk)
                except (RuleError,PermissionDenied) as e:return ('rejected',type(e).__name__)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:return list(pool.map(run,jobs))
    def job(self,user,handler,p):return (user.pk,user._adc_workspace.pk,handler,dict(proposal_token=p['proposal_token'],confirmed=True))
    def test_duplicate_proxy_submission_has_one_effect(self):
        p=proxies.prepare_submit(actor=self.front,fields=self.proxy_fields());rows=self.parallel([self.job(self.front,proxies.confirm,p)]*2)
        self.assertEqual([r[0] for r in rows],['ok','ok']);self.assertEqual(MedicalProxy.objects.count(),1);self.assertEqual(MedicalProxyEvent.objects.count(),1)
    def test_revocation_and_agreement_serialize_and_preserve_history(self):
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        agreement=consents.prepare(actor=self.delegate,action='AGREED',step_id=self.step.pk,fields={})
        revoke=proxies.prepare_action(actor=self.front,case_id=case.pk,action='REVOKE',note='合成资料：患者要求终止本次代理范围')
        rows=self.parallel([self.job(self.delegate,consents.confirm,agreement),self.job(self.front,proxies.confirm,revoke)])
        self.assertEqual(rows[1][0],'ok');case.refresh_from_db();self.assertEqual(case.state,'REVOKED')
        self.assertLessEqual(ConsentEvent.objects.filter(action='AGREED').count(),1)
        with self.assertRaises((RuleError,PermissionDenied)):self.medical('AGREED')
        self.assertFalse(PerformedProcedure.objects.exists())
    def test_parallel_agreement_creates_one_event(self):
        case=self.approved_proxy();self.scheme();self.offer_proxy(case)
        p=[consents.prepare(actor=self.delegate,action='AGREED',step_id=self.step.pk,fields={}) for _ in range(2)]
        r=self.parallel([self.job(self.delegate,consents.confirm,x) for x in p]);self.assertEqual(sum(x[0]=='ok' for x in r),1)
        self.assertEqual(ConsentEvent.objects.filter(action='AGREED').count(),1)
    def test_withdrawal_and_preflight_cannot_leave_usable_stale_check(self):
        self.self_agreement();self.control()
        check=preflight.prepare(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(self.step))
        withdraw=consents.prepare(actor=self.patient_user,action='WITHDRAWN',step_id=self.step.pk,fields={'text':'本人撤回尚未实施的本步骤同意'})
        rows=self.parallel([self.job(self.doc,preflight.confirm,check),self.job(self.patient_user,consents.confirm,withdraw)])
        self.assertEqual(rows[1][0],'ok')
        for retained in TreatmentPreflight.objects.all():
            with self.assertRaises((RuleError,PermissionDenied)):self.actual(self.step,preflight=retained.pk)
        self.assertFalse(PerformedProcedure.objects.exists());self.assertFalse(TreatmentRecord.objects.exists())


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalProxyStatusTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()
    def test_pending_delegate_can_read_only_account_bound_status(self):
        from tests.workspace_client import WorkspaceClient
        from django.urls import reverse
        case=self.submit();c=WorkspaceClient();c.force_login(self.delegate)
        r=c.post(reverse('mini_login'),{'username':self.delegate.username,'password':'synthetic-medical-only'})
        self.assertEqual(r.status_code,200,r.content);self.assertFalse(r.json()['data']['authenticated'])
        d=c.get(reverse('mini_medical_authorization',args=[case.pk]));self.assertEqual(d.status_code,200,d.content)
        data=d.json()['data'];self.assertTrue(data['status_only']);self.assertNotIn('identity_reference',data);self.assertNotIn('plan',data)
        self.assertNotIn(self.v.patient.name,str(data));self.assertNotIn('SYNTHETIC-WRITTEN-ORIGINAL',str(data))
        self.assertEqual(c.get(reverse('portal_medical_proxy',args=[case.pk])).status_code,200)
        self.assertNotEqual(c.get(reverse('mini_plan',args=[self.plan.pk])).status_code,200)
    def test_withdrawn_delegate_retains_status_without_new_clinical_access(self):
        from tests.workspace_client import WorkspaceClient
        from django.urls import reverse
        case=self.approved_proxy();self.scheme();self.offer_proxy(case);self.medical('AGREED');self.proxy_action(case,'REVOKE',actor=self.front)
        c=WorkspaceClient();c.force_login(self.delegate);c.post(reverse('mini_login'),{'username':self.delegate.username,'password':'synthetic-medical-only'})
        r=c.get(reverse('mini_medical_authorization',args=[case.pk]));self.assertEqual(r.status_code,200,r.content)
        self.assertTrue(r.json()['data']['status_only']);self.assertEqual(r.json()['data']['state'],'REVOKED')
        self.assertEqual(ConsentEvent.objects.filter(action='AGREED').count(),1)


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class PreflightIntegrationTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()
    def test_proxy_agreement_and_current_basis_allow_check_but_revocation_stops_execution(self):
        case=self.approved_proxy();self.scheme();self.offer_proxy(case);self.medical('AGREED');self.control();check=self.check()
        self.proxy_action(case,'REVOKE',actor=self.front)
        with self.assertRaises((PermissionDenied,RuleError)):self.actual(self.step,preflight=check.pk)
        self.assertFalse(TreatmentRecord.objects.exists())
    def test_equipment_failure_invalidates_prior_check(self):
        from scheduling.resources import current_plan
        self.self_agreement();self.control();check=self.check();plan=current_plan(self.v)
        self.maintain(plan.claims.first().asset)
        with self.assertRaises((PermissionDenied,RuleError)):self.actual(self.step,preflight=check.pk)
        self.assertFalse(TreatmentRecord.objects.exists())
    def test_communication_rule_cannot_hide_unanswered_medical_question(self):
        self.self_agreement();self.control(mode='COMMUNICATION');self.medical('QUESTION',actor=self.patient_user,text='本人针对实际方案还有新疑问。')
        with self.assertRaises(RuleError):self.check(communication='本次沟通已留存，不能跳过具体未答问题。')
    def test_partial_stage_uses_own_check_without_duplicate_charge(self):
        self.plan=self.new_plan(charge_basis='ON_COMPLETION')
        raw=PlanDraft.objects.get(plan=self.plan).payload['steps'][0]
        self.command(self.plan,'DISCLOSURE',**dict({k:'SYNTHETIC_PARTIAL_'+k for k,_,_ in FIELDS},sequence=1,step_key=raw['step_key'],prepared=True))
        self.step=self.publish_plan(self.plan).steps.get()
        self.self_agreement();self.control();check=self.check();self.review()
        actual=self.actual(self.step,preflight=check.pk,progress='PARTIAL',charge_mode='NO_CHARGE',reason='按实际分次安排，本阶段不另行收费。')
        self.assertIsNone(actual.charge_line_id);self.assertEqual(actual.preflight_id,check.pk)
        self.assertFalse(TreatmentRecord.objects.exists());self.assertEqual(ConsentEvent.objects.filter(action='AGREED').count(),1)
    def test_real_website_preflight_form_is_reviewable_before_confirm(self):
        from tests.workspace_client import WorkspaceClient
        from django.urls import reverse
        self.self_agreement();self.control();c=WorkspaceClient();c.force_login(self.doc)
        path=reverse('clinical_preflight',args=[self.v.pk]);r=c.get(path,{'step':self.step.pk});self.assertEqual(r.status_code,200,r.content)
        form=r.context['form'];values={f.name:f.value() if f.value() is not None else '' for f in form}
        values.update(step_version=self.step.pk,treatment_type=self.item.pk,quantity='1',tooth='16',surfaces=['M','O'],progress='COMPLETE',charge_mode='CHARGE',observed_at='',communication='')
        r=c.post(path,values);self.assertEqual(r.status_code,200,r.content);self.assertContains(r,self.v.patient.name)
        self.assertFalse(TreatmentPreflight.objects.exists())
        data={f.name:f.value() if f.value() is not None else '' for f in r.context['form']};data.update(phase='confirm',confirmed='on')
        r=c.post(path,data);self.assertEqual(r.status_code,302,r.content);self.assertEqual(TreatmentPreflight.objects.count(),1)
        self.assertFalse(PerformedProcedure.objects.exists());self.assertFalse(Invoice.objects.exists())


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class MedicalProxyFirstLoginTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()
    def test_first_password_login_with_medical_only_rights_reaches_subject_selector(self):
        from django.test import Client
        from django.urls import reverse
        case=self.approved_proxy();c=Client()
        response=c.post(reverse('portal_login'),{'username':self.delegate.username,'password':'synthetic-medical-only'})
        self.assertEqual(response.status_code,302)
        home=c.get(reverse('portal_home'));self.assertRedirects(home,reverse('portal_subjects'))
        r=c.get(reverse('portal_subjects'));self.assertContains(r,f'medical:{case.pk}')
        self.assertContains(r,self.v.patient.name)


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ProxyExecutionTests(MedicalFixture,TransactionTestCase):
    def setUp(self):self.setup_medical()
    def test_valid_proxy_consent_supports_one_actual_without_acquiring_bill_rights(self):
        self.approved_proxy();self.scheme();self.offer_proxy(MedicalProxy.objects.get());event=self.medical('AGREED');self.control();check=self.check();self.review()
        actual=self.actual(self.step,preflight=check.pk)
        self.assertEqual(actual.preflight.consent_decision_id,event.pk);self.assertEqual(TreatmentRecord.objects.count(),1)
        with self.assertRaises(PermissionDenied):patient_access(self.delegate,self_only=True)
