"""C2.3 real PostgreSQL responsibility, actual completion and lab readiness."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
import uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice,TreatmentRecord
from care.services import complete_visit
from clinical import recall,laboratory,next_visits,plans,executions
from clinical.continuity_models import RecallEpisode,RecallEvent,LabCase,LabReview,LabEvent
from clinical.lab_readiness import step_readiness
from clinical.plan_models import PlanDraft,PlanAppointment
from finance.cash_models import CashEntry
from scheduling.models import Visit
from tests.test_treatment_continuity import PlanFixture
from workspaces.models import WorkspaceContext


class ContinuityFixture(PlanFixture):
    def setup_continuity(self):self.setup_plan();self.followup_number=0
    def accepted_step(self,**values):
        plan=self.new_plan(**values);step=self.publish_plan(plan).steps.get();self.decision(step);return plan,step
    def lab_request(self,step):
        p=laboratory.prepare_lab(actor=self.doc,action='CREATE',visit_id=self.v.pk,fields=dict(step_version=step.pk,
            work_kind='RESTORATION',specification='PRIVATE_LAB_SPECIFICATION',vendor_name='明确标注的合成加工方',logistics_note='只需按合成单号协调送返',needed_on=timezone.localdate()+timedelta(days=3)))
        return laboratory.confirm_lab(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
    def lab_action(self,case,action,actor=None,**extra):
        actor=actor or (self.doc if action in ('REVIEW','WITHDRAW') else self.front)
        fields=dict(note='合成手工加工件流转核对',followup_due_at=timezone.now()+timedelta(hours=2),reference='SYNTHETIC-LAB-REF',occurred_at=timezone.now(),
            target_step_version=case.step_version_id,decision='ACCEPTED',findings='PRIVATE_LAB_FINDINGS',coordination_note='已完成本周期核对',assessed_at=timezone.now())
        fields.update(extra)
        p=laboratory.prepare_lab(actor=actor,action=action,case_id=case.pk,visit_id=self.v.pk if action in ('REVIEW','WITHDRAW') else None,fields=fields)
        return laboratory.confirm_lab(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]
    def accepted_lab(self,step):
        case=self.lab_request(step)
        for action in ('CLAIM','DISPATCH','RECEIVE','REVIEW'):case=self.lab_action(case,action)
        return case
    def open_recall(self,instruction):
        p=recall.prepare_recall(actor=self.front,action='OPEN',instruction_id=instruction.pk,fields=dict(followup_due_at=timezone.now()+timedelta(hours=2),note='认领本店后续联系'))
        return recall.confirm_recall(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)[0]
    def recall_action(self,row,action,actor=None,**extra):
        actor=actor or self.front
        fields=dict(note='合成复诊联系与内部协调',followup_due_at=timezone.now()+timedelta(hours=2),outcome='NO_ANSWER')
        if action=='COMPLETE':
            candidates=recall.completion_candidates(row.instruction)
            fields.update(evidence_kind=candidates[0]['kind'] if candidates else 'RECORD',evidence_id=candidates[0]['id'] if candidates else 99999999)
        fields.update(extra);p=recall.prepare_recall(actor=actor,action=action,episode_id=row.pk,fields=fields)
        return recall.confirm_recall(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]
    def scheduled_followup(self,instruction):
        self.followup_number+=1;visit=self.booking(start=self.t+timedelta(minutes=30*self.followup_number))
        p=next_visits.prepare_link(actor=self.front,instruction_id=instruction.pk,visit_id=visit.pk)
        next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        return visit
    def attend_followup(self,visit):
        Visit.objects.filter(pk=visit.pk).update(status='CHECKED_IN',attended=True,attended_at=timezone.now()-timedelta(seconds=1))
        visit.refresh_from_db();self.clinical(visit)
        return visit
    def close_followup(self,visit,step=None,**actual):
        self.attend_followup(visit)
        if step:
            self.actual(step,visit=visit,**actual);self.review(visit);visit.refresh_from_db()
            return complete_visit(actor=self.doc,visit_id=visit.pk,expected_version=visit.lock_version,outcome='TREATED')
        visit.refresh_from_db()
        return complete_visit(actor=self.doc,visit_id=visit.pk,expected_version=visit.lock_version,outcome='NO_TREATMENT',reason='本次完成实际检查，未实施治疗')


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class RecallLaboratoryTests(ContinuityFixture,TransactionTestCase):
    def setUp(self):self.setup_continuity()
    def test_contact_and_no_answer_keep_attributed_future_work(self):
        instruction=self.instruction();row=self.open_recall(instruction);row=self.recall_action(row,'CONTACT',outcome='NO_ANSWER')
        self.assertEqual(row.state,'OPEN');self.assertEqual(row.owner_id,self.front.pk);self.assertGreater(row.followup_due_at,timezone.now());self.assertEqual(row.events.count(),2)
    def test_booking_is_not_recall_completion(self):
        instruction=self.instruction();row=self.open_recall(instruction);visit=self.scheduled_followup(instruction)
        with self.assertRaises(RuleError):self.recall_action(row,'COMPLETE')
        visit.refresh_from_db();self.assertEqual(visit.status,'SCHEDULED');self.assertIsNone(row.completion_record_id)
    def test_arrival_and_draft_or_confirmed_exam_need_actual_closed_visit(self):
        instruction=self.instruction();row=self.open_recall(instruction);visit=self.scheduled_followup(instruction);self.attend_followup(visit)
        self.assertEqual(recall.completion_candidates(instruction),[])
        with self.assertRaises(RuleError):self.recall_action(row,'COMPLETE')
    def test_closed_confirmed_followup_is_explicitly_completed_once(self):
        instruction=self.instruction();row=self.open_recall(instruction);visit=self.scheduled_followup(instruction);self.close_followup(visit)
        candidate=recall.completion_candidates(instruction)[0]
        p=recall.prepare_recall(actor=self.front,action='COMPLETE',episode_id=row.pk,fields=dict(evidence_kind=candidate['kind'],evidence_id=candidate['id']))
        first,_=recall.confirm_recall(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        second,replay=recall.confirm_recall(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(first.pk,second.pk);self.assertEqual(first.state,'COMPLETED');self.assertEqual(first.completion_record_id,candidate['id']);self.assertEqual(row.events.filter(action='COMPLETE').count(),1)
    def test_partial_step_close_still_allows_next_booking_and_full_completion(self):
        plan,step=self.accepted_step(charge_basis='ON_COMPLETION');instruction=self.instruction(step_version=step.pk,completion_rule='STEP_COMPLETED');row=self.open_recall(instruction)
        first=self.scheduled_followup(instruction);self.close_followup(first,step,progress='PARTIAL',charge_mode='NO_CHARGE',reason='本次完成中间阶段，后续仍需继续')
        self.assertEqual(recall.completion_candidates(instruction),[]);self.assertTrue(next_visits.instruction_booking_projection(instruction)['needs_booking'])
        second=self.scheduled_followup(instruction);self.close_followup(second,step);row=self.recall_action(row,'COMPLETE')
        self.assertEqual(row.state,'COMPLETED');self.assertIsNotNone(row.completion_performed_id);self.assertEqual(PlanAppointment.objects.filter(instruction=instruction).count(),2)
    def test_patient_refusal_requires_review_and_preserves_appointment(self):
        instruction=self.instruction();row=self.open_recall(instruction);visit=self.scheduled_followup(instruction)
        row=self.recall_action(row,'CONTACT',outcome='DECLINED',note='本人明确暂不继续，不自动再次联系，转内部医师核对')
        self.assertEqual(row.state,'REVIEW');visit.refresh_from_db();self.assertEqual(visit.status,'SCHEDULED')
        with self.assertRaises(RuleError):self.recall_action(row,'CONTACT',outcome='REACHED')
        row=self.recall_action(row,'RESUME',note='本人重新同意继续协调，保留先前拒绝记录');self.assertEqual(row.state,'OPEN')
    def test_active_owner_cannot_be_replaced_by_another_frontdesk(self):
        row=self.open_recall(self.instruction())
        with self.assertRaises((PermissionDenied,RuleError)):self.recall_action(row,'REASSIGN',actor=self.front2)
        with self.assertRaises(PermissionDenied):self.recall_action(row,'CONTACT',actor=self.front2)
    def test_unavailable_owner_can_be_explicitly_reassigned_with_history(self):
        row=self.open_recall(self.instruction());RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        row=self.recall_action(row,'REASSIGN',actor=self.front2);self.assertEqual(row.owner_id,self.front2.pk);self.assertEqual(row.events.count(),2)
    def test_revoked_frontdesk_cannot_confirm_pending_contact(self):
        row=self.open_recall(self.instruction());p=recall.prepare_recall(actor=self.front,action='CONTACT',episode_id=row.pk,fields=dict(outcome='NO_ANSWER',note='未接通，保留待办',followup_due_at=timezone.now()+timedelta(hours=2)))
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        with self.assertRaises((PermissionDenied,RuleError)):recall.confirm_recall(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(row.events.count(),1)
    def test_withdrawal_requires_doctor_direction_and_keeps_original_booking(self):
        instruction=self.instruction();row=self.open_recall(instruction);visit=self.scheduled_followup(instruction)
        with self.assertRaises(RuleError):self.recall_action(row,'WITHDRAW')
        p=next_visits.prepare_withdrawal(actor=self.doc,visit_id=self.v.pk,instruction_id=instruction.pk,reason='医师重新核对后明确撤回原复诊目标')
        next_visits.confirm_instruction(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        row=self.recall_action(row,'WITHDRAW');visit.refresh_from_db();self.assertEqual(row.state,'WITHDRAWN');self.assertEqual(visit.status,'SCHEDULED')
    def test_wrong_clinic_has_no_recall_or_lab_case_projection(self):
        self.open_recall(self.instruction());plan,step=self.accepted_step(requires_lab=True);self.lab_request(step)
        self.ctx(self.front,'FRONT_DESK',self.b);self.assertFalse(recall.scoped_episodes(self.front).exists());self.assertFalse(laboratory.front_cases(self.front).exists())
    def test_database_refuses_original_source_as_followup_completion(self):
        row=self.open_recall(self.instruction())
        with self.assertRaises(DatabaseError),transaction.atomic():
            RecallEpisode.objects.filter(pk=row.pk).update(state='COMPLETED',revision=1,completed_at=timezone.now(),completion_record_id=row.instruction.source_record_id)
    def test_late_actual_care_completes_without_rewriting_window(self):
        instruction=self.instruction(latest_on=self.t.date());row=self.open_recall(instruction);visit=self.scheduled_followup(instruction);original=instruction.latest_on
        later=timezone.now()+timedelta(days=3)
        with patch('django.utils.timezone.now',return_value=later):
            self.close_followup(visit);row=self.recall_action(row,'COMPLETE')
        instruction.refresh_from_db();self.assertEqual(instruction.latest_on,original);self.assertGreater(row.events.get(action='COMPLETE').snapshot['evidence']['late_days'],0)
    def test_lab_request_and_physical_return_do_not_post_money_or_acceptance(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step)
        for action in ('CLAIM','DISPATCH','RECEIVE'):case=self.lab_action(case,action)
        self.assertEqual(case.state,'RECEIVED');self.assertFalse(LabReview.objects.exists());self.assertFalse(step_readiness(step)['ready'])
        self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_physical_return_cannot_authorize_actual_or_unplanned_bypass(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step)
        for action in ('CLAIM','DISPATCH','RECEIVE'):case=self.lab_action(case,action)
        with self.assertRaises(RuleError):self.actual(step)
        with self.assertRaises(RuleError):self.actual(reason='尝试使用计划外入口跳过当前加工件要求')
        self.assertFalse(TreatmentRecord.objects.exists())
    def test_frontdesk_has_no_clinical_lab_acceptance(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step)
        with self.assertRaises(PermissionDenied):self.lab_action(case,'REVIEW',actor=self.front)
    def test_accepted_case_authorizes_only_exact_current_step_and_actual_time(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        self.assertTrue(step_readiness(step)['ready']);actual=self.actual(step)
        self.assertEqual(len(actual.charge_snapshot['readiness']['cases']),1);self.assertEqual(actual.charge_snapshot['readiness']['cases'][0]['id'],case.pk);self.assertEqual(TreatmentRecord.objects.count(),1)
    def test_rework_requires_another_physical_cycle_before_acceptance(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        case=self.lab_action(case,'REVIEW',decision='REWORK',findings='PRIVATE_REWORK_FINDING',coordination_note='需返工，保留原约并明确协调')
        self.assertFalse(step_readiness(step)['ready'])
        with self.assertRaises(RuleError):self.lab_action(case,'REVIEW')
        for action in ('DISPATCH','RECEIVE','REVIEW'):case=self.lab_action(case,action)
        self.assertEqual(case.cycle,2);self.assertTrue(step_readiness(step)['ready']);self.assertEqual(LabReview.objects.count(),3)
    def test_delay_preserves_original_needed_date_and_booking(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);original=case.needed_on
        instruction=self.instruction(step_version=step.pk);visit=self.scheduled_followup(instruction)
        for action in ('CLAIM','DISPATCH'):case=self.lab_action(case,action)
        case=self.lab_action(case,'DELAY',expected_on=original+timedelta(days=2),note='手工获悉延误，需联系患者明确协调')
        case.refresh_from_db();visit.refresh_from_db();self.assertEqual(case.needed_on,original);self.assertEqual(visit.status,'SCHEDULED');self.assertGreater(case.followup_due_at,timezone.now())
        self.assertEqual(case.events.get(action='DELAY').snapshot['expected_on'],(original+timedelta(days=2)).isoformat())
    def test_new_plan_version_requires_its_own_explicit_compatibility_review(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        self.command(plan,'BEGIN_AMEND',reason='补充方案讨论版本，明确原加工件需要重新核对适配');new=self.publish_plan(plan).steps.get();self.decision(new)
        self.assertFalse(step_readiness(new)['ready'])
        with self.assertRaises(RuleError):self.actual(new)
        case=self.lab_action(case,'REVIEW',target_step_version=new.pk,findings='明确按新版本逐项核对原加工件适配，合成验收通过')
        self.assertTrue(step_readiness(new)['ready']);self.assertEqual(case.reviews.count(),2)
    def test_changed_position_cannot_reuse_accepted_original_case(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        self.command(plan,'BEGIN_AMEND',reason='新的讨论改为另一牙位，原件不推断为可用')
        values=dict(PlanDraft.objects.get(plan=plan).payload['steps'][0]);values.pop('step_key');values.update(sequence=1,tooth=17)
        self.command(plan,'UPDATE_STEP',**values);new=self.publish_plan(plan).steps.get();self.decision(new)
        with self.assertRaises(RuleError):self.lab_action(case,'REVIEW',target_step_version=new.pk)
        self.assertFalse(step_readiness(new)['ready'])
    def test_rework_after_actual_preview_rejects_stale_charge(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        p=executions.prepare_execution(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(step))
        self.lab_action(case,'REVIEW',decision='REWORK',findings='发现新的适配问题，需返工',coordination_note='原约保留，前台联系协调')
        with self.assertRaises(RuleError):executions.confirm_execution(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(TreatmentRecord.objects.exists())
    def test_unknown_lab_requirement_is_not_an_assumed_negative(self):
        plan,step=self.accepted_step(requires_lab=None)
        self.assertIsNone(step.requires_lab);self.assertFalse(step_readiness(step)['ready'])
        with self.assertRaises(RuleError):self.actual(step)
        with self.assertRaises(RuleError):self.lab_request(step)
    def test_patient_defer_blocks_dispatch_but_does_not_erase_physical_return(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);case=self.lab_action(case,'CLAIM');self.decision(step,'DEFERRED',note='本人暂缓后续安排')
        with self.assertRaises(RuleError):self.lab_action(case,'DISPATCH')
        self.decision(step);case=self.lab_action(case,'DISPATCH');self.decision(step,'DECLINED',note='本人不再选择此步骤')
        case=self.lab_action(case,'RECEIVE');self.assertEqual(case.state,'RECEIVED')
        with self.assertRaises(RuleError):self.lab_action(case,'REVIEW')
    def test_voiding_all_cases_does_not_clear_required_lab_gate(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);case=self.lab_action(case,'WITHDRAW',note='明确撤回此加工请求，原需求仍待重新安排')
        self.assertEqual(case.state,'WITHDRAWN');self.assertFalse(step_readiness(step)['ready'])
        with self.assertRaises(RuleError):self.actual(step)
    def test_actual_timestamp_cannot_precede_known_lab_acceptance(self):
        plan,step=self.accepted_step(requires_lab=True);self.accepted_lab(step)
        with self.assertRaises(RuleError):self.actual(step,observed_at=timezone.now()-timedelta(seconds=1))
    def test_database_does_not_accept_a_case_without_review(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step);case=self.lab_action(case,'CLAIM')
        with self.assertRaises(DatabaseError),transaction.atomic():LabCase.objects.filter(pk=case.pk).update(state='ACCEPTED',revision=case.revision+1)
    def test_recall_lab_event_review_and_case_identity_are_retained(self):
        row=self.open_recall(self.instruction());plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        for model,pk,values in [(RecallEvent,row.events.first().pk,dict(note='rewrite')),(LabReview,case.reviews.first().pk,dict(findings='rewrite')),
            (LabEvent,case.events.first().pk,dict(note='rewrite')),(LabCase,case.pk,dict(specification='rewrite',revision=case.revision+1))]:
            with self.subTest(model=model.__name__):
                with self.assertRaises(DatabaseError),transaction.atomic():model.objects.filter(pk=pk).update(**values)
    def test_concurrent_return_confirmations_keep_one_physical_receipt(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.lab_request(step)
        for action in ('CLAIM','DISPATCH'):case=self.lab_action(case,action)
        values=dict(note='合成返回核对',followup_due_at=timezone.now()+timedelta(hours=2),reference='SYNTHETIC-RETURN',occurred_at=timezone.now())
        tokens=[laboratory.prepare_lab(actor=self.front,action='RECEIVE',case_id=case.pk,fields=values)['proposal_token'] for _ in range(2)]
        gate=Barrier(2);uid=self.front.pk;ctxid=self.front._adc_workspace.pk
        def work(token):
            close_old_connections();actor=UserAccount.objects.get(pk=uid);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctxid)
            try:
                gate.wait(timeout=15);return laboratory.confirm_lab(actor=actor,proposal_token=token,confirmed=True)[0].pk
            except RuleError:return 'conflict'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,tokens))
        self.assertEqual(results.count('conflict'),1);self.assertEqual(case.events.filter(action='RECEIVE').count(),1);self.assertFalse(LabReview.objects.exists())
    def test_logistics_owner_handover_does_not_invalidate_unchanged_clinical_readiness(self):
        plan,step=self.accepted_step(requires_lab=True);case=self.accepted_lab(step)
        p=executions.prepare_execution(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(step))
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        self.lab_action(case,'CLAIM',actor=self.front2,note='在岗前台明确接续责任，临床验收事实不变')
        actual,_=executions.confirm_execution(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(actual.step_version_id,step.pk);self.assertEqual(TreatmentRecord.objects.count(),1)
