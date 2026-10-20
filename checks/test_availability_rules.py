"""Executable pure requirements checks; not ORM/HTTP or row-lock evidence."""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4
from scheduling.availability_rules import (CONTRACT, MAX_RELATIONS, AvailabilityError, Impact,
    positive_id, interval, parse_time, overlaps, display_time, digest, assess_relations,
    block_reasons, validate_action, validate_replacement, validate_payload)
ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,10,8,8,tzinfo=timezone.utc)
START=NOW+timedelta(days=1)
END=START+timedelta(hours=4)
SLOT={'slot_id':7,'clinic_id':1,'dentist_id':2,'starts_at':START.isoformat(),'ends_at':END.isoformat(),
      'is_active':True,'clinic_active':True,'dentist_active':True}
def visit(state='SCHEDULED',**more):
    return dict(id=11,clinic_id=1,dentist_id=2,scheduled_start=START.isoformat(),
        scheduled_end=(START+timedelta(minutes=30)).isoformat(),status=state,lock_version=0)|more

def offer(state='PENDING',**more):
    return {'id':5,'request_id':4,'request__clinic_id':1,'request__state':'OFFERED',
        'starts_at':START.isoformat(),'ends_at':(START+timedelta(minutes=30)).isoformat(),
        'expires_at':(NOW+timedelta(minutes=15)).isoformat(),'state':state,'visit_id':None}|more

def assess(v=(),o=(),slot=None,**kwargs):
    return assess_relations(slot=slot or SLOT,visits=v,offers=o,now=NOW,**kwargs)

class AvailabilityRulesTests(unittest.TestCase):
    def test_empty_future_slot_is_clear(self):self.assertTrue(assess().clear)
    def test_scheduled_visit_blocks(self):self.assertEqual(assess([visit()]).blocking_visits,1)
    def test_checked_in_visit_blocks(self):self.assertFalse(assess([visit('CHECKED_IN')]).clear)
    def test_closed_visits_conservatively_protected(self):
        for state in ('COMPLETED','CLOSED_NO_TREATMENT'):
            with self.subTest(state=state):self.assertFalse(assess([visit(state)]).clear)
    def test_cancelled_noshow_and_rescheduled_are_retained_nonblocking_history(self):
        impact=assess([visit(s,id=i) for i,s in enumerate(('CANCELLED','NO_SHOW','RESCHEDULED'),1)])
        self.assertTrue(impact.clear);self.assertEqual(impact.visit_count,3)
    def test_pending_valid_offer_blocks(self):self.assertEqual(assess(o=[offer()]).effective_offers,1)
    def test_exact_offer_expiry_is_no_longer_effective(self):
        a=assess(o=[offer(expires_at=NOW.isoformat())]);self.assertTrue(a.clear);self.assertEqual(a.expired_pending,1)
    def test_expired_pending_not_implicitly_recycled(self):
        row=offer(expires_at=(NOW-timedelta(seconds=1)).isoformat());old=dict(row)
        self.assertTrue(assess(o=[row]).clear);self.assertEqual(row,old)
    def test_declined_revoked_expired_are_nonblocking_history(self):
        for st in ('DECLINED','REVOKED','EXPIRED'):
            with self.subTest(st=st):self.assertTrue(assess(o=[offer(state=st)]).clear)
    def test_accepted_cancelled_visit_keeps_conversion_history(self):
        a=assess([visit('CANCELLED')],[offer('ACCEPTED',visit_id=11)])
        self.assertTrue(a.clear);self.assertEqual((a.visit_count,a.offer_count),(1,1))
    def test_accepted_live_visit_still_blocks(self):self.assertFalse(assess([visit()],[offer('ACCEPTED',visit_id=11)]).clear)
    def test_accepted_offer_without_matching_visit_fails_closed(self):self.assertEqual(assess(o=[offer('ACCEPTED',visit_id=99)]).anomalies,1)
    def test_nonaccepted_offer_with_visit_is_anomaly(self):self.assertFalse(assess([visit('CANCELLED')],[offer(visit_id=11)]).clear)
    def test_pending_request_state_mismatch_fails_closed(self):self.assertFalse(assess(o=[offer(**{'request__state':'BOOKED'})]).clear)
    def test_wrong_clinic_visit_is_anomaly(self):self.assertEqual(assess([visit('CANCELLED',clinic_id=9)]).anomalies,1)
    def test_wrong_dentist_visit_is_anomaly(self):self.assertEqual(assess([visit('CANCELLED',dentist_id=9)]).anomalies,1)
    def test_out_of_bounds_history_is_not_ignored(self):
        self.assertFalse(assess([visit('CANCELLED',scheduled_start=(START-timedelta(minutes=1)).isoformat())]).clear)
    def test_offer_wrong_clinic_is_anomaly(self):self.assertFalse(assess(o=[offer('EXPIRED',**{'request__clinic_id':9})]).clear)
    def test_truncation_cannot_prove_no_promises(self):self.assertTrue(assess(visit_count=MAX_RELATIONS+1).too_many)
    def test_input_count_mismatch_fails_closed(self):self.assertTrue(assess(o=[offer('EXPIRED')],offer_count=2).too_many)
    def test_original_already_started_blocks_even_empty(self):
        slot=SLOT|{'starts_at':NOW.isoformat()};self.assertTrue(block_reasons(slot,assess(slot=slot),NOW))
    def test_inactive_original_cannot_be_revived(self):self.assertTrue(block_reasons(SLOT|{'is_active':False},assess(),NOW))
    def test_inactive_dentist_can_stop_empty_future_but_cannot_replace(self):
        s=SLOT|{'dentist_active':False}
        validate_replacement(s,assess(),NOW,action='deactivate')
        with self.assertRaises(AvailabilityError):validate_replacement(s,assess(),NOW,action='replace',start=END,end=END+timedelta(hours=1))
    def test_unchanged_interval_is_rejected(self):
        with self.assertRaises(AvailabilityError):validate_replacement(SLOT,assess(),NOW,action='replace',start=START,end=END)
    def test_adjustment_permits_new_interval_overlapping_original(self):
        validate_replacement(SLOT,assess(),NOW,action='replace',start=START+timedelta(hours=1),end=END)
    def test_stopping_cannot_smuggle_new_times(self):
        with self.assertRaises(AvailabilityError):validate_replacement(SLOT,assess(),NOW,action='deactivate',start=START,end=END)
    def test_naive_times_rejected_by_domain(self):
        with self.assertRaises(AvailabilityError):interval(START.replace(tzinfo=None),END,NOW)
    def test_new_start_must_be_strictly_future(self):
        with self.assertRaises(AvailabilityError):interval(NOW,END,NOW)
    def test_new_end_must_be_later(self):
        for e in (START,START-timedelta(minutes=1)):
            with self.subTest(end=e),self.assertRaises(AvailabilityError):interval(START,e,NOW)
    def test_second_precision_not_silently_rounded(self):
        with self.assertRaises(AvailabilityError):interval(START+timedelta(seconds=1),END,NOW)
    def test_equivalent_timezone_instants(self):
        a=START.astimezone(timezone(timedelta(hours=8)));self.assertEqual(interval(a,END,NOW)[0],START)
    def test_half_open_adjacent_is_not_overlap(self):self.assertFalse(overlaps(START,END,END,END+timedelta(hours=1)))
    def test_positive_length_overlap(self):self.assertTrue(overlaps(START,END,START+timedelta(minutes=1),END+timedelta(hours=1)))
    def test_display_time_is_beijing(self):self.assertEqual(display_time(NOW),'2026年10月08日 16:00')
    def test_invalid_action_and_reason_are_rejected(self):
        for action,reason in [('delete','PLAN_CHANGED'),('replace','untrusted'),('restore','PLAN_CHANGED')]:
            with self.subTest(action=action),self.assertRaises(AvailabilityError):validate_action(action,reason)
    def test_snapshot_order_is_canonical_but_changes_are_visible(self):
        self.assertEqual(digest({'a':1,'b':2}),digest({'b':2,'a':1}))
        self.assertNotEqual(digest({'a':1,'cursor':2}),digest({'a':1,'cursor':3}))
    def test_state_hash_is_not_clock_dependent(self):self.assertEqual(digest(SLOT),digest(dict(SLOT)))
    def test_positive_ids_reject_booleans_and_strings(self):
        for x in (True,'7',0,-1,1.5):
            with self.subTest(x=x),self.assertRaises(AvailabilityError):positive_id(x)
    def test_parse_requires_timezone(self):
        with self.assertRaises(AvailabilityError):parse_time('2026-10-09T08:00')
    def test_input_facts_not_mutated(self):
        s=dict(SLOT);v=visit();o=offer();before=repr((s,v,o));assess([v],[o],slot=s);self.assertEqual(repr((s,v,o)),before)

class AvailabilityPayloadTests(unittest.TestCase):
    def payload(self,proposal=True):
        p={'contract':CONTRACT,'kind':'proposal' if proposal else 'state','actor':2,'context':str(uuid4()),
            'revision':3,'clinic':1,'slot':7,'state':'a'*64}
        if proposal:p.update(operation=str(uuid4()),action='replace',reason='PLAN_CHANGED',start=START.isoformat(),end=END.isoformat())
        return p
    def test_valid_state_and_proposal(self):
        for proposal in (False,True):
            p=self.payload(proposal);self.assertEqual(validate_payload(p,proposal=proposal),p)
    def test_extra_authority_fields_rejected(self):
        p=self.payload()|{'dentist':99}
        with self.assertRaises(AvailabilityError):validate_payload(p,proposal=True)
    def test_missing_state_rejected(self):
        p=self.payload();p.pop('state')
        with self.assertRaises(AvailabilityError):validate_payload(p,proposal=True)
    def test_state_token_cannot_act_as_confirmation(self):
        with self.assertRaises(AvailabilityError):validate_payload(self.payload(False),proposal=True)
    def test_future_unknown_contract_rejected(self):
        with self.assertRaises(AvailabilityError):validate_payload(self.payload()|{'contract':'other'},proposal=True)
    def test_invalid_uuid_revision_and_hash_rejected(self):
        for key,value in [('context','x'),('operation','x'),('revision',True),('state','z'*64)]:
            with self.subTest(key=key),self.assertRaises(AvailabilityError):validate_payload(self.payload()|{key:value},proposal=True)
    def test_stop_proposal_has_no_new_interval(self):
        p=self.payload()|{'action':'deactivate','start':None,'end':None};validate_payload(p,proposal=True)
        with self.assertRaises(AvailabilityError):validate_payload(p|{'start':START.isoformat()},proposal=True)

class AvailabilitySourceContracts(unittest.TestCase):
    def setUp(self):self.source=(ROOT/'scheduling/availability_services.py').read_text();self.tree=ast.parse(self.source)
    def test_atomic_confirm_and_shared_slot_protocol(self):
        node=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='confirm_availability_change')
        self.assertIn('transaction.atomic',[ast.unparse(n) for n in node.decorator_list])
        self.assertIn('lock_clinic_grant(',self.source);self.assertIn('lock_slots([slot_id])',self.source)
    def test_no_business_record_deletion(self):self.assertNotIn('.delete(',self.source)
    def test_original_slot_only_active_flag_written(self):
        self.assertIn("slot.save(update_fields=['is_active'])",self.source)
        for field in ('starts_at','ends_at','dentist_id','clinic_id'):self.assertNotIn('slot.'+field+' =',self.source)
    def test_no_patient_or_offer_writes(self):
        calls=[ast.unparse(n.func) for n in ast.walk(self.tree) if isinstance(n,ast.Call)]
        self.assertNotIn('Visit.objects.create',calls);self.assertNotIn('WaitOffer.objects.create',calls)
        self.assertFalse(any(x.endswith('.update') for x in calls))
    def test_scope_first_before_source_lock(self):
        n=next(n for n in self.tree.body if isinstance(n,ast.FunctionDef) and n.name=='_owned_slot')
        s=ast.unparse(n);self.assertLess(s.index('clinic_id=ctx.clinic_id'),s.index('lock_slots('))
    def test_new_routes_are_frontdesk_only(self):
        from adc_core.route_manifest import named_routes
        routes=named_routes(ROOT)
        for key in ('availability_list','availability_detail','availability_change','availability_confirm'):self.assertIn(key,routes)
        tree=ast.parse((ROOT/'workspaces/middleware.py').read_text())
        node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROUTES' for t in n.targets))
        mapping={ast.literal_eval(k):ast.literal_eval(v) for k,v in zip(node.keys,node.values) if ast.literal_eval(k).startswith('availability_')}
        for key in ('availability_list','availability_detail','availability_change','availability_confirm'):self.assertEqual(mapping[key],{'FRONT_DESK'})
    def test_confirm_requires_post_and_csrf_present(self):
        s=(ROOT/'scheduling/availability_views.py').read_text();self.assertIn('@require_POST\ndef confirm',s)
        t=(ROOT/'templates/scheduling/availability_confirm.html').read_text();self.assertIn('{% csrf_token %}',t);self.assertIn('{% workspace_token %}',t)
        self.assertNotIn('csrf_exempt',s)
    def test_new_mutations_not_readonly_allowlisted(self):
        from adc_core.read_only_policy import allowed_in_read_only
        for name in ('availability_change','availability_confirm'):
            self.assertFalse(allowed_in_read_only('POST',name))
    def test_guide_is_role_scoped(self):
        from guidance.catalog import GUIDES
        self.assertEqual(GUIDES['front-availability'].roles,('FRONT_DESK',))
    def test_service_snapshot_contains_no_patient_fields(self):
        for word in ('patient_no','phone','email','chief_complaint','date_of_birth'):self.assertNotIn(word,self.source)

if __name__=='__main__':unittest.main()
