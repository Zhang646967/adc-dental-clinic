"""Pure contract tests; never counted as HTTP/PG validation."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
import unittest
from scheduling.intake_rules import (CONTRACT, IntakeError, validate_transition,
    require_new_admission, validate_reserved_offer, validate_payload)
from scheduling.availability_rules import digest
ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2031,1,1,1,tzinfo=timezone.utc)

class IntakePolicyTests(unittest.TestCase):
    def transition(self,**kw):
        data=dict(active=True,paused=False,ends_at=NOW+timedelta(hours=2),now=NOW,
            clinic_active=True,dentist_active=True,action='pause',reason='COORDINATION')
        data.update(kw);return validate_transition(**data)
    def test_pause(self):self.assertTrue(self.transition())
    def test_resume(self):self.assertFalse(self.transition(paused=True,action='resume',reason='READY_TO_REOPEN'))
    def test_inactive_cannot_pause_or_resume(self):
        for paused,action,reason in [(False,'pause','COORDINATION'),(True,'resume','READY_TO_REOPEN')]:
            with self.subTest(action=action),self.assertRaises(IntakeError):self.transition(active=False,paused=paused,action=action,reason=reason)
    def test_exact_end_is_history(self):
        with self.assertRaises(IntakeError):self.transition(ends_at=NOW)
    def test_past_end_is_history(self):
        with self.assertRaises(IntakeError):self.transition(ends_at=NOW-timedelta(seconds=1))
    def test_pause_can_reduce_intake_with_disabled_dentist(self):self.assertTrue(self.transition(dentist_active=False))
    def test_resume_requires_active_dentist(self):
        with self.assertRaises(IntakeError):self.transition(paused=True,dentist_active=False,action='resume',reason='READY_TO_REOPEN')
    def test_resume_requires_active_clinic(self):
        with self.assertRaises(IntakeError):self.transition(paused=True,clinic_active=False,action='resume',reason='READY_TO_REOPEN')
    def test_duplicate_action_rejected(self):
        with self.assertRaises(IntakeError):self.transition(paused=True)
    def test_bool_not_coerced(self):
        for field in ['active','paused','clinic_active','dentist_active']:
            with self.subTest(field=field),self.assertRaises(IntakeError):self.transition(**{field:1})
    def test_naive_time_rejected(self):
        with self.assertRaises(IntakeError):self.transition(now=NOW.replace(tzinfo=None))
    def test_reason_matches_action(self):
        with self.assertRaises(IntakeError):self.transition(reason='READY_TO_REOPEN')
    def test_unknown_action_rejected(self):
        with self.assertRaises(IntakeError):self.transition(action='cancel_all')
    def test_public_open(self):require_new_admission(active=True,paused=False)
    def test_public_paused(self):
        with self.assertRaises(IntakeError):require_new_admission(active=True,paused=True)
    def test_public_inactive(self):
        with self.assertRaises(IntakeError):require_new_admission(active=False,paused=False)
    def test_public_flag_not_coerced(self):
        with self.assertRaises(IntakeError):require_new_admission(active=True,paused='false')
    def test_timezone_equivalence(self):
        z=timezone(timedelta(hours=8));self.assertTrue(self.transition(now=NOW.astimezone(z)))

class PromiseRuleTests(unittest.TestCase):
    def data(self):
        start=NOW+timedelta(hours=1);end=start+timedelta(minutes=30)
        return dict(slot_id=1,patient_id=2,clinic_id=3,start=start,end=end,
            offer_slot_id=1,offer_patient_id=2,offer_clinic_id=3,offer_start=start,offer_end=end,
            expires_at=NOW+timedelta(minutes=10),now=NOW,offer_state='PENDING',request_state='OFFERED',visit_id=None)
    def test_matching_live_promise(self):self.assertTrue(validate_reserved_offer(**self.data()))
    def test_only_exact_scope(self):
        for field in ['offer_slot_id','offer_patient_id','offer_clinic_id']:
            with self.subTest(field=field),self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|{field:99}))
    def test_only_exact_times(self):
        for field in ['offer_start','offer_end']:
            data=self.data();data[field]+=timedelta(minutes=1)
            with self.subTest(field=field),self.assertRaises(IntakeError):validate_reserved_offer(**data)
    def test_expired_equal(self):
        with self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(expires_at=NOW)))
    def test_expired_past(self):
        with self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(expires_at=NOW-timedelta(seconds=1))))
    def test_terminal_offers_not_promise(self):
        for state in ['ACCEPTED','DECLINED','REVOKED','EXPIRED','garbage']:
            with self.subTest(state=state),self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(offer_state=state)))
    def test_inconsistent_request_not_promise(self):
        with self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(request_state='WAITING')))
    def test_existing_visit_not_promise(self):
        with self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(visit_id=2)))
    def test_expiry_after_start_rejected(self):
        with self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(expires_at=NOW+timedelta(days=1))))
    def test_bool_object_id_rejected(self):
        with self.assertRaises(IntakeError):validate_reserved_offer(**(self.data()|dict(slot_id=True)))

class PayloadTests(unittest.TestCase):
    def data(self,proposal=False):
        d=dict(contract=CONTRACT,kind='proposal' if proposal else 'state',actor=1,context=str(uuid4()),revision=1,clinic=2,slot=3,state='a'*64)
        if proposal:d.update(operation=str(uuid4()),action='pause',reason='COORDINATION')
        return d
    def test_state(self):validate_payload(self.data(),proposal=False)
    def test_proposal(self):validate_payload(self.data(True),proposal=True)
    def test_extra_key(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(allow_paused=True),proposal=False)
    def test_missing_key(self):
        d=self.data();del d['clinic']
        with self.assertRaises(IntakeError):validate_payload(d,proposal=False)
    def test_wrong_contract(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(contract='OTHER'),proposal=False)
    def test_wrong_kind(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(kind='proposal'),proposal=False)
    def test_bad_uuid(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(context='../other'),proposal=False)
    def test_bad_digest(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(state='A'*64),proposal=False)
    def test_negative_revision(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(revision=-1),proposal=False)
    def test_bool_id(self):
        with self.assertRaises(IntakeError):validate_payload(self.data()|dict(slot=True),proposal=False)
    def test_action_reason_pair(self):
        with self.assertRaises(IntakeError):validate_payload(self.data(True)|dict(action='resume'),proposal=True)
    def test_revision_distinguishes_aba(self):self.assertNotEqual(digest(dict(paused=False,revision=0)),digest(dict(paused=False,revision=2)))

class IntegrationContractTests(unittest.TestCase):
    def source(self,p):return (ROOT/p).read_text()
    def test_new_migration_is_additive(self):
        s=self.source('scheduling/migrations/0002_slot_intake_control.py')
        self.assertEqual(s.count('migrations.AddField('),2);self.assertNotIn('RemoveField(',s)
        self.assertIn('guard_reverse',s);self.assertIn("('scheduling', '0001_initial')",s)
    def test_model_has_separate_state(self):
        s=self.source('scheduling/models.py');self.assertIn('booking_paused = models.BooleanField(default=False)',s)
        self.assertIn('intake_revision = models.PositiveIntegerField(default=0)',s)
    def test_common_creation_checks_gate(self):
        s=self.source('scheduling/services.py');self.assertIn('require_new_admission(',s)
        self.assertLess(s.index('require_new_admission(active='),s.index('Visit.objects.create('))
    def test_exception_is_verified_not_a_boolean_bypass(self):
        s=self.source('scheduling/services.py');self.assertIn('validate_reserved_offer(',s)
        self.assertIn('require_owner_or_front(actor, promise.request)',s)
        self.assertNotIn('allow_paused',s)
    def test_accept_keeps_hold_until_commit(self):
        s=self.source('coordination/services.py');body=s[s.index('def answer_offer'):s.index('def expire_clinic_offers')]
        self.assertIn('honor_offer_id=o.pk',body);self.assertNotIn("o.state='REVOKED'",body)
    def test_plan_filters_and_rechecks(self):
        s=self.source('coordination/services.py');self.assertIn('booking_paused=False',s)
        self.assertIn('require_new_admission(active=s.is_active, paused=s.booking_paused)',s)
        self.assertIn("row.get('intake_revision', 0)",s)
    def test_portal_filters_and_revision(self):
        s=self.source('portal/services.py');self.assertEqual(s.count('booking_paused=False'),2)
        self.assertIn('revision != slot.intake_revision',s)
    def test_front_slots_excludes_paused(self):self.assertIn('booking_paused=False',self.source('scheduling/selectors.py'))
    def test_only_frontdesk_routes(self):
        s=self.source('workspaces/middleware.py')
        self.assertIn("'intake_change':{'FRONT_DESK'}",s);self.assertIn("'intake_confirm':{'FRONT_DESK'}",s)
    def test_pause_does_not_write_other_records(self):
        s=self.source('scheduling/intake_services.py')
        for name in ['Visit.objects','WaitOffer.objects','Patient.objects','Invoice.objects','WaitRequest.objects']:self.assertNotIn(name,s)
        self.assertIn("update_fields=['booking_paused','intake_revision']",s)
    def test_atomic_audited_context(self):
        s=self.source('scheduling/intake_services.py');self.assertIn('@transaction.atomic',s)
        self.assertIn('lock_clinic_grant(actor',s);self.assertIn('event = emit(',s)
    def test_replacement_inherits_pause(self):self.assertIn('booking_paused=slot.booking_paused',self.source('scheduling/availability_services.py'))
    def test_snapshot_includes_new_dimension(self):
        s=self.source('scheduling/availability_services.py');self.assertIn("'intake_revision': slot.intake_revision",s)
        self.assertIn("'SLOT_INTAKE_PAUSED'",s)
    def test_no_http_offer_bypass_parameter(self):
        for q in ROOT.rglob('*views.py'):
            self.assertNotIn('honor_offer_id',q.read_text())
    def test_confirm_forms_have_tokens(self):
        for name in ['intake_change.html','intake_confirm.html']:
            s=self.source('templates/scheduling/'+name)
            self.assertIn('{% csrf_token %}',s);self.assertIn('{% workspace_token %}',s)
            self.assertIn('method="post"',s);self.assertIn('尚未保存' if name=='intake_confirm.html' else '尚不保存',s)
    def test_manual_guide_real_route(self):
        from guidance.catalog import GUIDES,choose_guide
        self.assertEqual(GUIDES['front-intake'].roles,('FRONT_DESK',))
        self.assertEqual(choose_guide('FRONT_DESK','overview','暂停接收新预约'),'front-intake')
    def test_no_unexpected_dependencies(self):
        tree=ast.parse(self.source('scheduling/intake_rules.py'))
        imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
        self.assertFalse(any(x and x.startswith(('django','requests','openai')) for x in imports))
