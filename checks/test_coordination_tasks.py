"""Developer-level pure policies/source contracts, NOT real ORM/HTTP tests."""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import unittest
from coordination.task_rules import (TaskError, ACTIVE_STATES, STATES, ACTIONS, REASONS,
    ACTION_REASONS, CONTRACT, review_gate, validate_step, validate_options, validate_payload)
from scheduling.availability_rules import Impact
ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2031,1,1,0,0,tzinfo=timezone.utc)
SLOT=dict(is_active=True,booking_paused=True,starts_at=(NOW+timedelta(days=1)).isoformat())
EMPTY=Impact(0,0,0,0,0,0,False)

def task(state='IN_PROGRESS',owner=7):
    return dict(state=state,assignee_id=None if state=='OPEN' else owner,revision=1,
                submitted_by_id=owner if state in ('READY','CLOSED') else None,
                submitted_digest='a'*64 if state in ('READY','CLOSED') else '')

class TaskPolicyTests(unittest.TestCase):
    def step(self,t,action,**kw):
        d=dict(action=action,actor_id=7,role='FRONT_DESK',slot=SLOT,impact=EMPTY,now=NOW,observation_digest='a'*64)
        d.update(kw);return validate_step(t,**d)
    def test_open_paused_future(self): self.assertEqual(self.step(None,'open',role='MANAGER'),'OPEN')
    def test_open_requires_pause(self):
        with self.assertRaisesRegex(TaskError,'暂停'):self.step(None,'open',role='MANAGER',slot=SLOT|{'booking_paused':False})
    def test_open_requires_future(self):
        with self.assertRaises(TaskError):self.step(None,'open',role='MANAGER',slot=SLOT|{'starts_at':NOW.isoformat()})
    def test_open_existing_promises_allowed(self):
        self.assertEqual(self.step(None,'open',role='MANAGER',impact=Impact(4,4,2,2,0,0,False)),'OPEN')
    def test_open_duplicates_fail(self):
        with self.assertRaises(TaskError):self.step(None,'open',role='MANAGER',another_active=True)
    def test_open_bad_relation_fails(self):
        with self.assertRaises(TaskError):self.step(None,'open',role='MANAGER',impact=Impact(0,0,0,0,0,1,False))
    def test_open_truncated_fails(self):
        with self.assertRaises(TaskError):self.step(None,'open',role='MANAGER',impact=Impact(1001,0,0,0,0,0,True))
    def test_front_can_open(self):
        self.assertEqual(self.step(None,'open'),'OPEN')
    def test_front_claims_self(self):self.assertEqual(self.step(task('OPEN'),'claim'),'IN_PROGRESS')
    def test_second_claim_fails(self):
        with self.assertRaises(TaskError):self.step(task(),'claim')
    def test_manager_cannot_claim(self):
        with self.assertRaises(TaskError):self.step(task('OPEN'),'claim',role='MANAGER')
    def test_owner_can_report(self):self.assertEqual(self.step(task(),'progress'),'IN_PROGRESS')
    def test_nonowner_cannot_report(self):
        with self.assertRaises(TaskError):self.step(task(),'progress',actor_id=8)
    def test_report_does_not_clear_promises(self):
        t=task();i=Impact(3,3,1,1,0,0,False)
        self.assertEqual(self.step(t,'progress',impact=i),'IN_PROGRESS')
        with self.assertRaises(TaskError):self.step(t,'submit',impact=i)
    def test_owner_release(self):self.assertEqual(self.step(task(),'release'),'OPEN')
    def test_nonowner_cannot_release(self):
        with self.assertRaises(TaskError):self.step(task(),'release',actor_id=8)
    def test_owner_submits_fresh_clear(self):self.assertEqual(self.step(task(),'submit'),'READY')
    def test_same_account_review_forbidden(self):
        with self.assertRaisesRegex(TaskError,'不能切换身份'):self.step(task('READY'),'approve',role='MANAGER')
    def test_other_manager_review(self):self.assertEqual(self.step(task('READY'),'approve',role='MANAGER',actor_id=8),'CLOSED')
    def test_approve_requires_ready(self):
        with self.assertRaises(TaskError):self.step(task(),'approve',role='MANAGER',actor_id=8)
    def test_approve_detects_changes_after_submission(self):
        with self.assertRaisesRegex(TaskError,'变化'):self.step(task('READY'),'approve',role='MANAGER',actor_id=8,observation_digest='b'*64)
    def test_approve_rejects_owner_mismatch(self):
        with self.assertRaises(TaskError):self.step(task('READY')|{'submitted_by_id':9},'approve',role='MANAGER',actor_id=8)
    def test_return_ready_to_queue(self):self.assertEqual(self.step(task('READY'),'return',role='MANAGER'),'OPEN')
    def test_return_inprogress_to_queue(self):self.assertEqual(self.step(task(),'return',role='MANAGER'),'OPEN')
    def test_return_open_rejected(self):
        with self.assertRaises(TaskError):self.step(task('OPEN'),'return',role='MANAGER')
    def test_cancel_from_each_active_state(self):
        for s in ACTIVE_STATES:
            with self.subTest(s=s):self.assertEqual(self.step(task(s),'cancel',role='MANAGER'),'CANCELLED')
    def test_cancel_ended_unpaused_allowed(self):
        self.assertEqual(self.step(task(),'cancel',role='MANAGER',slot=SLOT|{'is_active':False,'booking_paused':False,'starts_at':NOW.isoformat()}),'CANCELLED')
    def test_terminal_cannot_mutate(self):
        for s in ('CLOSED','CANCELLED'):
            for a in ACTIONS:
                with self.subTest(s=s,a=a),self.assertRaises(TaskError):self.step(task(s),a,role='MANAGER')
    def test_revision_overflow(self):
        with self.assertRaises(TaskError):self.step(task()|{'revision':2**31-1},'progress')
    def test_unknown_role_rejected(self):
        for role in ('DENTIST','SYSADMIN','HQ','PATIENT'):
            with self.subTest(role=role),self.assertRaises(TaskError):self.step(task(),'progress',role=role)
    def test_policies_do_not_mutate_input(self):
        t=task('READY');before=deepcopy(t);self.step(t,'approve',role='MANAGER',actor_id=8);self.assertEqual(t,before)
    def test_review_gate_requires_pause(self):self.assertFalse(review_gate(SLOT|{'booking_paused':False},EMPTY,NOW).clear)
    def test_review_gate_protects_care(self):self.assertFalse(review_gate(SLOT,Impact(1,1,0,0,0,0,False),NOW).clear)
    def test_review_gate_effective_hold(self):self.assertFalse(review_gate(SLOT,Impact(0,0,1,1,0,0,False),NOW).clear)
    def test_review_gate_expired_hold_not_occupying(self):self.assertTrue(review_gate(SLOT,Impact(0,0,1,0,1,0,False),NOW).clear)
    def test_review_gate_closed_source_blocked(self):self.assertFalse(review_gate(SLOT|{'is_active':False},EMPTY,NOW).clear)
    def test_review_gate_anomaly_failclosed(self):self.assertFalse(review_gate(SLOT,Impact(0,0,0,0,0,1,False),NOW).clear)
    def test_review_gate_cutoff_failclosed(self):self.assertFalse(review_gate(SLOT,Impact(1001,0,0,0,0,0,True),NOW).clear)
    def test_time_requires_timezone(self):
        with self.assertRaises(ValueError):review_gate(SLOT,EMPTY,NOW.replace(tzinfo=None))
    def test_progress_explicit_kind_and_id(self):validate_options('progress','NO_RESPONSE',target_kind='visit',target_id=4)
    def test_help_no_patient_required(self):validate_options('progress','NEED_HELP')
    def test_no_contact_claim_without_target(self):
        with self.assertRaises(TaskError):validate_options('progress','NO_RESPONSE')
    def test_reject_false_identifier(self):
        for x in (False,0,-2,'3','https://bad.invalid/3'):
            with self.subTest(x=x),self.assertRaises(TaskError):validate_options('progress','NO_RESPONSE',target_kind='offer',target_id=x)
    def test_no_arbitrary_reason_text(self):
        with self.assertRaises(TaskError):validate_options('progress','病史和电话号码',target_kind='visit',target_id=1)
    def test_claim_cannot_smuggle_target(self):
        with self.assertRaises(TaskError):validate_options('claim','TAKE_RESPONSIBILITY',target_kind='visit',target_id=1)
    def test_cannot_rename_purpose(self):
        with self.assertRaises(TaskError):validate_options('claim','TAKE_RESPONSIBILITY',purpose='REPLACE')
    def test_open_purpose_required(self):
        with self.assertRaises(TaskError):validate_options('open','PLAN_CHANGE')
    def test_all_actions_have_fixed_reasons(self):self.assertEqual(set(ACTIONS),set(ACTION_REASONS))

class TaskPayloadTests(unittest.TestCase):
    def payload(self,proposal=False):
        d=dict(contract=CONTRACT,kind='state',actor=2,role='MANAGER',context=str(uuid4()),context_revision=1,clinic=1,slot=4,task=None,state='a'*64)
        if proposal:d.update(kind='proposal',operation=str(uuid4()),action='open',reason='PLAN_CHANGE',purpose='REPLACE',target_kind='',target_id=None,due_at=(NOW+timedelta(hours=2)).isoformat())
        return d
    def test_valid_state(self):validate_payload(self.payload(),proposal=False)
    def test_valid_proposal(self):validate_payload(self.payload(True),proposal=True)
    def test_extra_fields_fail(self):
        with self.assertRaises(TaskError):validate_payload(self.payload(True)|{'ignore_booking_pause':True},proposal=True)
    def test_missing_fields_fail(self):
        p=self.payload();p.pop('role')
        with self.assertRaises(TaskError):validate_payload(p,proposal=False)
    def test_no_client_status(self):
        with self.assertRaises(TaskError):validate_payload(self.payload(True)|{'state_after':'CLOSED'},proposal=True)
    def test_context_type_strict(self):
        with self.assertRaises(TaskError):validate_payload(self.payload()|{'context_revision':True},proposal=False)
    def test_object_id_strict(self):
        with self.assertRaises(ValueError):validate_payload(self.payload()|{'task':True},proposal=False)
    def test_bad_digest(self):
        with self.assertRaises(TaskError):validate_payload(self.payload()|{'state':'x'},proposal=False)
    def test_bad_contract(self):
        with self.assertRaises(TaskError):validate_payload(self.payload()|{'contract':'old'},proposal=False)
    def test_cannot_swap_token_kind(self):
        with self.assertRaises(TaskError):validate_payload(self.payload(True),proposal=False)
    def test_open_cannot_target_existing_task(self):
        with self.assertRaises(TaskError):validate_payload(self.payload(True)|{'task':1},proposal=True)

class TaskSourceContracts(unittest.TestCase):
    def text(self,p):return (ROOT/p).read_text()
    def test_pure_rules_import_no_framework(self):
        tree=ast.parse(self.text('coordination/task_rules.py'))
        modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any(m.startswith(('django','requests','psycopg')) for m in modules))
    def test_task_commands_do_not_write_clinical_or_source(self):
        s=self.text('coordination/task_services.py');tree=ast.parse(s)
        self.assertNotIn('from scheduling.services import',s);self.assertNotIn('from coordination.services import',s)
        for n in ast.walk(tree):
            if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('save','delete','update'):
                root=ast.unparse(n.func.value)
                self.assertNotIn(root,('slot','visit','offer','patient','invoice'))
    def test_confirm_is_atomic_and_uses_grant_and_slot_lock(self):
        s=self.text('coordination/task_services.py');self.assertIn('lock_clinic_grant(actor',s);self.assertIn('slot = lock_slots([slot_id])',s)
        tree=ast.parse(s);fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='confirm_task')
        self.assertIn('transaction.atomic',[ast.unparse(n) for n in fn.decorator_list])
    def test_new_routes_explicit(self):
        from adc_core.route_manifest import named_routes
        self.assertEqual(len([n for n in named_routes(ROOT) if n.startswith('coordination_task_')]),6)
    def test_new_queries_do_not_read_raw_contacts(self):
        s=self.text('coordination/task_facts.py')
        for f in ('phone','email','billing_address','chief_complaint','special_needs','date_of_birth'):self.assertNotIn(f,s)
    def test_guarded_migration_adds_and_protects_history(self):
        s=self.text('coordination/migrations/0002_coordination_tasks.py')
        for text in ('coord_task_one_active_slot','coord_task_separate_review','coordination_task_history_guard','guard_reverse','NEW.revision <> OLD.revision + 1'):self.assertIn(text,s)
    def test_migration_matches_model_field_names(self):
        tree=ast.parse(self.text('coordination/models.py'));c=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CoordinationTask')
        names=[n.targets[0].id for n in c.body if isinstance(n,ast.Assign)]
        s=''.join(p.read_text() for p in sorted((ROOT/'coordination/migrations').glob('0*.py')))
        for n in names:self.assertTrue('('+repr(n)+',' in s or 'name='+repr(n) in s,n)
    def test_readonly_does_not_allow_task_posts(self):
        s=self.text('adc_core/middleware.py');self.assertNotIn('coordination_task_confirm',s)
    def test_confirmation_has_both_tokens_and_no_get_save(self):
        s=self.text('templates/coordination/tasks/confirm.html')
        for x in ('{% csrf_token %}','{% workspace_token %}','method="post"','尚未保存'):self.assertIn(x,s)
    def test_history_is_sanitized_for_manager(self):
        s=self.text('coordination/task_services.py');self.assertIn("identity['role']=='FRONT_DESK'",s)
        self.assertIn("row['target']",s)
    def test_guides_are_reviewed_role_limited(self):
        from guidance.catalog import GUIDES,choose_guide
        self.assertEqual(choose_guide('MANAGER','overview','协调任务'),'manager-task')
        self.assertEqual(choose_guide('FRONT_DESK','overview','受理任务'),'front-task')
        self.assertEqual(GUIDES['manager-task'].roles,('MANAGER',))
    def test_downstream_migration_test_restores_all_leaves(self):
        self.assertIn('final_targets=executor.loader.graph.leaf_nodes()',self.text('tests/test_v09_intake.py'))

    def test_navigation_cards_not_inside_title_block(self):
        for name in ('availability_detail','front_coordination_detail'):
            s=self.text('templates/scheduling/'+name+'.html')
            if '{% block title %}' in s:
                title=s.split('{% block title %}',1)[1].split('{% endblock %}',1)[0]
                self.assertNotIn('<section',title)
                self.assertNotIn('<a ',title)

    def test_clinical_intent_never_replaced_by_task_keyword(self):
        from guidance.catalog import choose_guide
        self.assertIsNone(choose_guide('FRONT_DESK','clinical','协调任务要怎么用药'))
