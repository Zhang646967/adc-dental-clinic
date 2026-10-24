"""C2.2 PostgreSQL facts: versions, patient decisions and unique actual charges."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
import uuid
from django.core.exceptions import PermissionDenied
from django.db import transaction,DatabaseError,close_old_connections
from django.test import TransactionTestCase,override_settings
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice,TreatmentRecord
from care.services import review_allergies,complete_visit,add_treatment,remove_treatment
from clinical import encounters,plans,executions,next_visits
from clinical.plan_models import *
from clinical.plan_payload import estimate_totals,normalize_plan
from finance.cash_models import CashEntry
from portal.models import PatientAccess
from registry.models import TreatmentType
from scheduling.models import Visit
from scheduling.services import change_appointment
from tests.test_clinical_authority import AuthorityFixture
from workspaces.models import WorkspaceContext


class PlanFixture(AuthorityFixture):
    def setup_plan(self):
        self.setup_authority();self.authority=self.authorize();self.v=self.checked_visit();self.clinical(self.v)
        self.item=TreatmentType.objects.create(code='C22-ACTUAL',name='合成实际处置',unit_definition='颗次',standard_unit_price='100.00')
        self.patient_user=UserAccount.objects.create_user(username='plan_patient',password='synthetic-plan-only')
        PatientAccess.objects.create(user=self.patient_user,patient=self.v.patient);self.ctx(self.patient_user,'PATIENT')
    def clinical(self,visit):
        head,_=encounters.start_encounter(actor=self.doc,visit_id=visit.pk,expected_visit_version=visit.lock_version,operation_id=uuid.uuid4())
        encounters.change_draft(actor=self.doc,visit_id=visit.pk,expected_revision=head.revision,operation_id=uuid.uuid4(),action='NOTES',fields=dict(
            chief_complaint='PRIVATE_PLAN_CHIEF',examination='PRIVATE_PLAN_EXAM',history_review='UNAVAILABLE',history_id=None,
            history_assessment='尚未取得本人自述，相关情况保留未知。',history_discrepancy='',dentition='PERMANENT',observed_at=timezone.now().isoformat()))
        p=encounters.prepare_record(actor=self.doc,visit_id=visit.pk)
        return encounters.confirm_record(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
    def command(self,plan,action,**fields):
        plan.refresh_from_db()
        return plans.change_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk,expected_revision=plan.revision,
            operation_id=uuid.uuid4(),action=action,fields=fields)[0]
    def new_plan(self,**overrides):
        plan,_=plans.start_plan(actor=self.doc,visit_id=self.v.pk,operation_id=uuid.uuid4())
        self.command(plan,'NOTES',summary='PRIVATE_PLAN_SUMMARY',discussion_note='讨论可选方案，仍待患者本人决定。')
        values=dict(treatment_type=self.item.pk,service=self.service.pk,description='PRIVATE_PLAN_STEP',goal='PRIVATE_PLAN_GOAL',
            tooth=16,surface='MO',estimated_quantity='1',estimated_unit_price='100.00',estimate_note='',alternative_group='',charge_basis='PER_EXECUTION',requires_lab=False)
        values.update(overrides);self.command(plan,'ADD_STEP',**values)
        return plan
    def publish_plan(self,plan):
        p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        return plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
    def decision(self,step,decision='ACCEPTED',actor=None,note=''):
        actor=actor or self.patient_user
        p=plans.prepare_decision(actor=actor,step_id=step.pk,visit_id=self.v.pk if actor.pk==self.doc.pk else None,
            fields=dict(decision=decision,reference='SYNTHETIC-PATIENT-DISCUSSION' if actor.pk==self.doc.pk else '',note=note))
        return plans.confirm_decision(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0]
    def actual_fields(self,step=None,**overrides):
        data=dict(step_version=step.pk if step else None,treatment_type=self.item.pk,quantity='1',tooth=16,surface='MO',
            progress='COMPLETE',charge_mode='CHARGE',reason='' if step else '明确记录本次计划外实际已提供项目',observed_at=timezone.now().isoformat())
        data.update(overrides);return data
    def actual(self,step=None,visit=None,**values):
        p=executions.prepare_execution(actor=self.doc,visit_id=(visit or self.v).pk,fields=self.actual_fields(step,**values))
        return executions.confirm_execution(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]
    def review(self,visit=None):
        visit=visit or self.v;visit.refresh_from_db();visit.patient.refresh_from_db()
        review_allergies(actor=self.doc,visit_id=visit.pk,expected_version=visit.lock_version,patient_version=visit.patient.allergy_info_version,status='NO_KNOWN')
        visit.refresh_from_db()
    def another(self):
        visit=self.booking(start=self.t+timedelta(minutes=30))
        Visit.objects.filter(pk=visit.pk).update(status='CHECKED_IN',attended=True,attended_at=timezone.now()-timedelta(minutes=1))
        visit.refresh_from_db();self.clinical(visit);return visit
    def instruction(self,**extra):
        values=dict(service=self.service.pk,step_version=None,earliest_on=timezone.localdate(),latest_on=self.t.date()+timedelta(days=10),
            clinical_purpose='PRIVATE_NEXT_PURPOSE',booking_note='请安排本店同服务后续时段',completion_rule='EXAM_CONFIRMED')
        values.update(extra)
        p=next_visits.prepare_instruction(actor=self.doc,visit_id=self.v.pk,fields=values)
        return next_visits.confirm_instruction(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)[0]


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class TreatmentContinuityTests(PlanFixture,TransactionTestCase):
    def setUp(self):self.setup_plan()
    def test_plan_and_patient_acceptance_do_not_create_money_or_actual_work(self):
        plan=self.new_plan();version=self.publish_plan(plan);self.decision(version.steps.get())
        self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists());self.assertFalse(PerformedProcedure.objects.exists())
    def test_unknown_estimate_is_not_zero_and_alternatives_not_added(self):
        plan=self.new_plan(estimated_unit_price=None,alternative_group='OPTION-A')
        draft=PlanDraft.objects.get(plan=plan);values=dict(draft.payload['steps'][0]);values.pop('step_key');values['estimated_unit_price']='200.00'
        self.command(plan,'ADD_STEP',**values);total=estimate_totals(PlanDraft.objects.get(plan=plan).payload['steps'])
        self.assertIsNone(total['total']);self.assertTrue(total['choice_required']);self.assertEqual(total['alternative_groups']['OPTION-A'][0]['unknown_steps'],1)
        self.assertIsNone(self.publish_plan(plan).steps.first().estimated_unit_price)
    def test_two_alternative_steps_cannot_both_be_accepted(self):
        plan=self.new_plan(alternative_group='OPTION-A');raw=dict(PlanDraft.objects.get(plan=plan).payload['steps'][0]);raw.pop('step_key')
        self.command(plan,'ADD_STEP',**raw);a,b=list(self.publish_plan(plan).steps.all());self.decision(a)
        with self.assertRaises(RuleError):self.decision(b)
        self.decision(a,'DECLINED',note='明确改选另一方案');self.decision(b)
        self.assertEqual(plans.latest_decision(a).decision,'DECLINED');self.assertEqual(plans.latest_decision(b).decision,'ACCEPTED')
    def test_plan_versions_and_exact_decisions_are_retained(self):
        plan=self.new_plan();first=self.publish_plan(plan);old=first.steps.get();self.decision(old)
        self.command(plan,'BEGIN_AMEND',reason='后续检查明确了新的步骤讨论依据');self.command(plan,'NOTES',summary='PRIVATE_NEW_SUMMARY')
        newer=self.publish_plan(plan);step=newer.steps.get()
        self.assertEqual(step.step_id,old.step_id);self.assertEqual(newer.previous_id,first.pk);self.assertIsNone(plans.latest_decision(step))
        with self.assertRaises(RuleError):self.actual(old)
        with self.assertRaises(RuleError):self.actual(step)
        self.decision(step);self.actual(step);self.assertEqual(PlanDecision.objects.count(),2)
    def test_confirmation_replay_never_publishes_a_second_plan(self):
        plan=self.new_plan();p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        a,_=plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        b,replay=plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(a.pk,b.pk);self.assertEqual(PlanVersion.objects.count(),1)
    def test_stale_plan_preview_preserves_saved_changes(self):
        plan=self.new_plan();p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.command(plan,'NOTES',summary='PRIVATE_NEW_SAVED')
        with self.assertRaises(RuleError):plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload['summary'],'PRIVATE_NEW_SAVED');self.assertFalse(PlanVersion.objects.exists())
    def test_revoked_professional_scope_blocks_pending_plan_confirmation(self):
        plan=self.new_plan();p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.decide(self.authority,'REVOKE')
        with self.assertRaises(PermissionDenied):plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(PlanVersion.objects.exists())
    def test_patient_cannot_decide_for_other_patient(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get()
        other=UserAccount.objects.create_user(username='other_plan_patient');PatientAccess.objects.create(user=other,patient=self.p2);self.ctx(other,'PATIENT')
        with self.assertRaises(PlanStepVersion.DoesNotExist):self.decision(step,actor=other)
        self.assertFalse(PlanDecision.objects.exists())
    def test_frontdesk_and_manager_do_not_inherit_clinical_decision_authority(self):
        step=self.publish_plan(self.new_plan()).steps.get()
        for actor in (self.front,self.manager,self.tech):
            with self.subTest(role=actor._adc_workspace.role):
                with self.assertRaises(PermissionDenied):self.decision(step,actor=actor)
    def test_changed_payload_cannot_reuse_a_saved_draft_operation(self):
        plan=self.new_plan();plan.refresh_from_db();op=uuid.uuid4();values=dict(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk,expected_revision=plan.revision,operation_id=op,action='NOTES')
        plans.change_plan(**values,fields={'summary':'first saved'})
        with self.assertRaises(RuleError):plans.change_plan(**values,fields={'summary':'different unsaved'})
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload['summary'],'first saved')
    def test_one_actual_event_has_one_draft_charge_and_retry_returns_current(self):
        step=self.publish_plan(self.new_plan()).steps.get();self.decision(step)
        p=executions.prepare_execution(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(step))
        a,_=executions.confirm_execution(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        b,replay=executions.confirm_execution(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replay);self.assertEqual(a.pk,b.pk);self.assertEqual(TreatmentRecord.objects.count(),1);self.assertEqual(a.charge_line.line_amount,Decimal('100.00'))
        self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_structured_old_add_and_remove_cannot_bypass_actual_source(self):
        self.v.refresh_from_db()
        with self.assertRaises(RuleError):add_treatment(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,treatment_id=self.item.pk,quantity=Decimal('1'))
        actual=self.actual();self.v.refresh_from_db()
        with self.assertRaises(RuleError):remove_treatment(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,line_id=actual.charge_line_id,reason='尝试绕过实际执行来源')
        self.assertEqual(TreatmentRecord.objects.count(),1)
    def test_unplanned_actual_requires_explicit_reason(self):
        with self.assertRaises(RuleError):self.actual(reason='')
        self.assertFalse(TreatmentRecord.objects.exists());self.actual();self.assertEqual(PerformedProcedure.objects.count(),1)
    def test_plan_price_difference_requires_reason(self):
        step=self.publish_plan(self.new_plan(estimated_unit_price='90.00')).steps.get();self.decision(step)
        with self.assertRaises(RuleError):self.actual(step)
        self.actual(step,reason='已向本人说明目录价格与讨论估算的差异')
        self.assertEqual(TreatmentRecord.objects.get().line_amount,Decimal('100.00'))
    def test_patient_defer_and_decline_prevent_new_actual(self):
        step=self.publish_plan(self.new_plan()).steps.get()
        for decision in ('DEFERRED','DECLINED'):
            self.decision(step,decision,note='患者暂不选择此步骤')
            with self.assertRaises(RuleError):self.actual(step)
        self.assertFalse(PerformedProcedure.objects.exists())
    def test_completed_stable_step_is_not_recharged_from_new_version(self):
        plan=self.new_plan();old=self.publish_plan(plan).steps.get();self.decision(old);self.actual(old)
        self.command(plan,'BEGIN_AMEND',reason='补充讨论说明，保持原实际已完成步骤');new=self.publish_plan(plan).steps.get();self.decision(new)
        later=self.another()
        with self.assertRaises(RuleError):self.actual(new,visit=later)
        self.assertEqual(TreatmentRecord.objects.count(),1)
    def test_staged_no_charge_is_treated_care_not_no_treatment(self):
        step=self.publish_plan(self.new_plan(charge_basis='ON_COMPLETION')).steps.get();self.decision(step)
        self.actual(step,progress='PARTIAL',charge_mode='NO_CHARGE',reason='按已讨论的完成时计费步骤记录本次阶段')
        self.review();self.v.refresh_from_db()
        with self.assertRaises(RuleError):complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='NO_TREATMENT',reason='不能把实际已治疗写作未治疗')
        invoice=complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='TREATED')
        self.assertEqual(invoice.current_record_version.total_amount,Decimal('0.00'));self.assertEqual(invoice.current_record_version.outcome,'TREATED')
        self.assertFalse(TreatmentRecord.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_on_completion_partial_then_final_charge_across_visits(self):
        step=self.publish_plan(self.new_plan(charge_basis='ON_COMPLETION')).steps.get();self.decision(step)
        self.actual(step,progress='PARTIAL',charge_mode='NO_CHARGE',reason='本次先完成第一阶段，最终阶段完成时计费')
        later=self.another();actual=self.actual(step,visit=later)
        self.assertEqual(PerformedProcedure.objects.count(),2);self.assertEqual(TreatmentRecord.objects.count(),1);self.assertEqual(actual.charge_snapshot['line_amount'],'100.00')
    def test_no_charge_is_not_a_general_fee_waiver(self):
        with self.assertRaises(RuleError):self.actual(progress='PARTIAL',charge_mode='NO_CHARGE')
        step=self.publish_plan(self.new_plan()).steps.get();self.decision(step)
        with self.assertRaises(RuleError):self.actual(step,progress='PARTIAL',charge_mode='NO_CHARGE',reason='不可任意免除按次计费')
        self.assertFalse(PerformedProcedure.objects.exists())
    def test_on_completion_partial_cannot_charge_early(self):
        step=self.publish_plan(self.new_plan(charge_basis='ON_COMPLETION')).steps.get();self.decision(step)
        with self.assertRaises(RuleError):self.actual(step,progress='PARTIAL')
        self.assertFalse(TreatmentRecord.objects.exists())
    def test_void_draft_preserves_actual_and_original_charge_snapshot(self):
        actual=self.actual();original=actual.charge_line_id
        p=executions.prepare_void(actor=self.doc,visit_id=self.v.pk,performed_id=actual.pk,reason='核对发现本次项目误录，保留原执行及开单依据')
        row,_=executions.confirm_void(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        replay,again=executions.confirm_void(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(again);self.assertEqual(row.pk,replay.pk);self.assertEqual(row.state,'VOIDED');self.assertIsNone(row.charge_line_id)
        self.assertEqual(row.charge_snapshot['original_line'],original);self.assertEqual(row.charge_snapshot['line_amount'],'100.00');self.assertFalse(TreatmentRecord.objects.exists())
    def test_published_actual_cannot_be_voided_or_rewrite_financial_history(self):
        actual=self.actual();self.review();invoice=complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='TREATED')
        original=invoice.current_record_version_id
        p=executions.prepare_void(actor=self.doc,visit_id=self.v.pk,performed_id=actual.pk,reason='尝试撤回已经形成发布结算的原执行')
        with self.assertRaises(RuleError):executions.confirm_void(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        invoice.refresh_from_db();self.assertEqual(invoice.current_record_version_id,original);self.assertEqual(invoice.current_record_version.total_amount,Decimal('100.00'))
    def test_immutable_versions_decisions_actual_source_and_events(self):
        version=self.publish_plan(self.new_plan());decision=self.decision(version.steps.get());actual=self.actual(version.steps.get());event=PlanEvent.objects.first()
        for model,row,field,value in [(PlanVersion,version,'summary','silent rewrite'),(PlanDecision,decision,'decision','DECLINED'),(PerformedProcedure,actual,'quantity',Decimal('2')),(PlanEvent,event,'note','rewrite')]:
            with self.subTest(model=model.__name__):
                with self.assertRaises(DatabaseError),transaction.atomic():model.objects.filter(pk=row.pk).update(**{field:value})
    def test_concurrent_actual_confirmations_have_one_charge(self):
        step=self.publish_plan(self.new_plan()).steps.get();self.decision(step)
        proposals=[executions.prepare_execution(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(step))['proposal_token'] for _ in range(2)]
        gate=Barrier(2);uid=self.doc.pk;ctxid=self.doc._adc_workspace.pk
        def work(token):
            close_old_connections();actor=UserAccount.objects.get(pk=uid);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctxid)
            try:
                gate.wait(timeout=15);return executions.confirm_execution(actor=actor,proposal_token=token,confirmed=True)[0].pk
            except RuleError:return 'conflict'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,proposals))
        self.assertEqual(results.count('conflict'),1);self.assertEqual(PerformedProcedure.objects.count(),1);self.assertEqual(TreatmentRecord.objects.count(),1)
    def test_frontdesk_links_real_booking_without_closing_clinical_followup(self):
        instruction=self.instruction();later=self.booking(start=self.t+timedelta(hours=1))
        p=next_visits.prepare_link(actor=self.front,instruction_id=instruction.pk,visit_id=later.pk)
        first,_=next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        second,again=next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(again);self.assertEqual(first.pk,second.pk);instruction.refresh_from_db();self.assertEqual(instruction.state,'OPEN');self.assertEqual(Visit.objects.count(),2)
    def test_cancelled_link_returns_pending_coordination_and_keeps_original(self):
        instruction=self.instruction();later=self.booking(start=self.t+timedelta(hours=1))
        p=next_visits.prepare_link(actor=self.front,instruction_id=instruction.pk,visit_id=later.pk);next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        change_appointment(actor=self.front,visit_id=later.pk,expected_version=0,action='cancel',party='PATIENT',reason='本人明确取消本次后续安排')
        view=next_visits.instruction_booking_projection(instruction)
        self.assertTrue(view['needs_booking']);self.assertEqual(view['promises'][0]['current'].status,'CANCELLED');self.assertEqual(PlanAppointment.objects.count(),1)
    def test_wrong_patient_link_and_wrong_clinic_access_are_rejected(self):
        instruction=self.instruction();later=self.booking(patient=self.p2,start=self.t+timedelta(hours=1))
        with self.assertRaises(PermissionDenied):next_visits.prepare_link(actor=self.front,instruction_id=instruction.pk,visit_id=later.pk)
        self.ctx(self.front,'FRONT_DESK',self.b);self.assertFalse(next_visits.front_instructions(self.front).exists())
    def test_expired_window_and_revoked_frontdesk_preview_do_not_link(self):
        instruction=self.instruction(latest_on=timezone.localdate());later=self.booking(start=self.t+timedelta(hours=1))
        with self.assertRaises(RuleError):next_visits.prepare_link(actor=self.front,instruction_id=instruction.pk,visit_id=later.pk)
        row=self.instruction();p=next_visits.prepare_link(actor=self.front,instruction_id=row.pk,visit_id=later.pk)
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied):next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(PlanAppointment.objects.exists())
    def test_withdrawal_preserves_booked_promise(self):
        instruction=self.instruction();later=self.booking(start=self.t+timedelta(hours=1))
        p=next_visits.prepare_link(actor=self.front,instruction_id=instruction.pk,visit_id=later.pk);next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        p=next_visits.prepare_withdrawal(actor=self.doc,visit_id=self.v.pk,instruction_id=instruction.pk,reason='新检查明确后续安排需要重新制定')
        next_visits.confirm_instruction(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        later.refresh_from_db();self.assertEqual(later.status,'SCHEDULED');self.assertEqual(PlanAppointment.objects.count(),1)
    def test_booking_projection_does_not_include_clinical_purpose(self):
        row=self.instruction();projection=next_visits.instruction_booking_projection(next_visits.front_instructions(self.front).get(pk=row.pk))
        self.assertNotIn('clinical_purpose',projection);self.assertNotIn('PRIVATE_NEXT_PURPOSE',str(projection));self.assertIn('booking_note',projection)
    def test_actual_source_survives_independent_financial_correction(self):
        from care.corrections import request_line_correction,review_correction
        from care.progress import care_progress
        actual=self.actual();self.review();invoice=complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='TREATED')
        self.v.refresh_from_db();req=request_line_correction(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,line_id=actual.charge_line_id,
            quantity=Decimal('2'),unit_price=Decimal('100'),reason='核对账单数量误录，财务独立复核；临床原事实另行保留')
        finance=UserAccount.objects.create_user(username='c22_independent_finance');RoleAssignment.objects.create(user=finance,role='FINANCE',scope_kind='CHAIN');self.ctx(finance,'FINANCE')
        invoice=review_correction(actor=finance,request_id=req.pk,decision='approve',reason='独立核对原账单及指定数字更正')
        actual.refresh_from_db();self.assertEqual(actual.quantity,Decimal('1'));self.assertEqual(actual.charge_snapshot['line_amount'],'100.00')
        self.assertEqual(actual.charge_line.record_version.total_amount,Decimal('100.00'));self.assertEqual(invoice.current_record_version.total_amount,Decimal('200.00'))
        self.assertEqual(care_progress(self.doc,self.v.pk)['lines'][0].performed_source_id,actual.pk);self.assertFalse(CashEntry.objects.exists())
    def test_draft_step_update_keeps_lineage_but_cannot_reinterpret_actual_position(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get();self.decision(step);self.actual(step)
        self.command(plan,'BEGIN_AMEND',reason='补充后续讨论依据，原执行仍保留')
        values=dict(PlanDraft.objects.get(plan=plan).payload['steps'][0]);key=values.pop('step_key');values.update(sequence=1,tooth=17)
        with self.assertRaises(RuleError):self.command(plan,'UPDATE_STEP',**values)
        values.update(tooth=16,description='补充说明且保持原有实际位置');self.command(plan,'UPDATE_STEP',**values)
        new=self.publish_plan(plan).steps.get();self.assertEqual(str(new.step.step_key),key);self.assertEqual(step.tooth,new.tooth)
    def test_wrong_clinic_service_cannot_be_saved_even_in_draft(self):
        from scheduling.models import Department,BookingService
        dep=Department.objects.create(clinic=self.b,code='WRONG',name='异店科室');service=BookingService.objects.create(department=dep,code='WRONG',name='异店服务',duration_minutes=30)
        plan=self.new_plan();before=PlanDraft.objects.get(plan=plan).payload
        values=dict(before['steps'][0]);values.pop('step_key');values['service']=service.pk
        with self.assertRaises(RuleError):self.command(plan,'ADD_STEP',**values)
        self.assertEqual(PlanDraft.objects.get(plan=plan).payload,before)
    def test_revoked_self_access_prevents_saved_decision_confirmation(self):
        step=self.publish_plan(self.new_plan()).steps.get();p=plans.prepare_decision(actor=self.patient_user,step_id=step.pk,fields=dict(decision='ACCEPTED'))
        PatientAccess.objects.filter(user=self.patient_user).update(is_active=False)
        with self.assertRaises((PermissionDenied,RuleError)):plans.confirm_decision(actor=self.patient_user,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(PlanDecision.objects.exists())
    def test_defer_after_actual_preview_prevents_stale_charge(self):
        step=self.publish_plan(self.new_plan()).steps.get();self.decision(step);p=executions.prepare_execution(actor=self.doc,visit_id=self.v.pk,fields=self.actual_fields(step))
        self.decision(step,'DEFERRED',note='本人决定暂不提供本步骤')
        with self.assertRaises(RuleError):executions.confirm_execution(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(PerformedProcedure.objects.exists());self.assertFalse(TreatmentRecord.objects.exists())
    def test_published_no_charge_actual_is_protected_at_database_boundary(self):
        step=self.publish_plan(self.new_plan(charge_basis='ON_COMPLETION')).steps.get();self.decision(step)
        actual=self.actual(step,progress='PARTIAL',charge_mode='NO_CHARGE',reason='按已讨论的分次完成规则提供本阶段')
        self.review();complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,outcome='TREATED')
        with self.assertRaises(DatabaseError),transaction.atomic():PerformedProcedure.objects.filter(pk=actual.pk).update(state='VOIDED',revision=1)
        actual.refresh_from_db();self.assertEqual(actual.state,'ACTIVE')
    def test_instruction_follows_real_reschedule_without_rewriting_original_link(self):
        from scheduling.services import reschedule
        row=self.instruction();later=self.booking(start=self.t+timedelta(hours=1))
        p=next_visits.prepare_link(actor=self.front,instruction_id=row.pk,visit_id=later.pk);link,_=next_visits.confirm_link(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        new=reschedule(actor=self.front,visit_id=later.pk,expected_version=0,new_slot_id=self.slot1.pk,start=self.t+timedelta(hours=2),end=self.t+timedelta(hours=2,minutes=30),reason='本人明确改期，保留原临床指示',service_id=self.service.pk)
        projected=next_visits.instruction_booking_projection(row);self.assertEqual(projected['promises'][0]['current'].pk,new.pk)
        link.refresh_from_db();self.assertEqual(link.visit_id,later.pk);self.assertFalse(projected['needs_booking'])
    def test_confirmed_plan_retains_original_service_definition_after_catalogue_change(self):
        plan=self.new_plan();step=self.publish_plan(plan).steps.get();original_name=self.service.name
        self.service.name='新的当前目录名称';self.service.duration_minutes=45;self.service.save(update_fields=['name','duration_minutes'])
        from clinical.plan_selectors import self_plan_details
        details=self_plan_details(self.patient_user,plan.pk);shown=details['steps'][0]
        self.assertEqual(shown.saved_service_name,original_name);self.assertEqual(shown.planned_duration,30);self.assertEqual(step.definition_snapshot['service']['name'],original_name)
    def test_service_definition_change_invalidates_plan_preview_without_creating_version(self):
        plan=self.new_plan();p=plans.prepare_plan(actor=self.doc,visit_id=self.v.pk,plan_id=plan.pk)
        self.service.name='预览后更改的服务名称';self.service.save(update_fields=['name'])
        with self.assertRaises(RuleError):plans.confirm_plan(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(PlanVersion.objects.exists());self.assertTrue(PlanDraft.objects.filter(plan=plan).exists())
