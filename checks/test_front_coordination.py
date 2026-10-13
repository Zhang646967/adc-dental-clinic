"""Pure rule and source contracts only; never report these as Django tests."""
import ast
import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from scheduling.availability_rules import Impact, AvailabilityError, assess_relations
from scheduling.front_coordination_rules import (assessment, visit_instruction,
    offer_instruction, relation_anomalies, safe_page, origin_id)
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2031,1,1,0,0,tzinfo=timezone.utc)
START = NOW+timedelta(days=1); END = START+timedelta(hours=4)
SLOT = dict(slot_id=7,clinic_id=1,dentist_id=2,is_active=True,
    clinic_active=True,dentist_active=True,starts_at=START.isoformat(),ends_at=END.isoformat())
CLEAR = Impact(0,0,0,0,0,0,False)

def visit(status='SCHEDULED', **kw):
    return dict(id=11,availability_slot_id=7,patient_id=1,clinic_id=1,dentist_id=2,
        scheduled_start=START.isoformat(),scheduled_end=(START+timedelta(minutes=30)).isoformat(),status=status,**kw)
def offer(**kw):
    o = dict(id=21,slot_id=7,request_id=31,request__clinic_id=1,request__patient_id=1,
        request__state='BOOKED',state='ACCEPTED',visit_id=11,starts_at=START.isoformat(),
        ends_at=(START+timedelta(minutes=30)).isoformat(),expires_at=(START-timedelta(minutes=30)).isoformat())
    o.update(kw);return o

def assess(i=CLEAR, slot=SLOT, **kw):return assessment(slot,i,NOW,clinical_count=kw.pop('clinical_count',0),**kw)

class CoordinationRulesTests(unittest.TestCase):
    def test_clear_means_recheck_not_permission(self):
        r=assess();self.assertEqual(r.code,'RECHECK');self.assertTrue(r.can_ask_manager_to_recheck)
        self.assertIn('不是停用许可',r.explanation);self.assertIn('未暂停',r.explanation)
    def test_scheduled_promises_need_patient_intent(self):
        self.assertEqual(assess(Impact(1,1,0,0,0,0,False)).code,'COORDINATE')
    def test_pending_offer_is_a_promise(self):
        self.assertEqual(assess(Impact(0,0,1,1,0,0,False)).code,'COORDINATE')
    def test_expiry_not_recycling(self):
        r=offer_instruction('PENDING',expires_at=NOW,now=NOW)
        self.assertEqual(r['group'],'expiry');self.assertFalse(r['offer'])
        self.assertIn('不自动回收',r['instruction'])
    def test_one_microsecond_before_deadline_is_valid(self):
        self.assertTrue(offer_instruction('PENDING',expires_at=NOW+timedelta(microseconds=1),now=NOW)['offer'])
    def test_accepted_offer_ignores_old_deadline(self):
        r=offer_instruction('ACCEPTED',expires_at=NOW-timedelta(days=1),now=NOW)
        self.assertTrue(r['appointment']);self.assertFalse(r['offer']);self.assertEqual(r['group'],'history')
    def test_withdrawn_declined_expired_offer_no_write_path(self):
        for s in ('DECLINED','REVOKED','EXPIRED'):
            r=offer_instruction(s,expires_at=NOW,now=NOW)
            self.assertFalse(r['offer']);self.assertFalse(r['appointment'])
    def test_clinical_records_not_cancel_targets(self):
        for s in ('CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT'):
            r=visit_instruction(s,starts_at=START,now=NOW)
            self.assertFalse(r['reschedule']);self.assertEqual(r['group'],'care')
        self.assertEqual(assess(Impact(1,1,0,0,0,0,False),clinical_count=1).code,'CARE_PROTECTED')
    def test_historical_visits_are_not_open_promises(self):
        for s in ('CANCELLED','RESCHEDULED','NO_SHOW'):
            r=visit_instruction(s,starts_at=START,now=NOW)
            self.assertFalse(r['reschedule']);self.assertEqual(r['group'],'history')
    def test_started_scheduled_visit_does_not_mean_noshow(self):
        r=visit_instruction('SCHEDULED',starts_at=NOW,now=NOW)
        self.assertFalse(r['reschedule']);self.assertIn('不要仅因',r['instruction'])
    def test_inactive_and_started_not_clear(self):
        self.assertEqual(assess(slot=SLOT|{'is_active':False}).code,'INACTIVE')
        self.assertEqual(assessment(SLOT,CLEAR,START,clinical_count=0).code,'STARTED')
    def test_anomaly_has_priority_over_inactive_or_started(self):
        r=assessment(SLOT|{'is_active':False},Impact(0,0,0,0,0,1,False),END,clinical_count=0)
        self.assertEqual(r.code,'REVIEW');self.assertFalse(r.can_ask_manager_to_recheck)
    def test_truncation_never_proves_clear(self):
        self.assertEqual(assess(Impact(1001,0,0,0,0,0,True)).code,'REVIEW')
    def test_additional_identity_mismatch_never_clear(self):
        self.assertEqual(assess(additional_anomalies=1).code,'REVIEW')
    def test_accepted_to_exact_visit_is_valid(self):
        self.assertEqual(relation_anomalies(slot_id=7,visits=[visit()],offers=[offer()]),0)
    def test_accepted_different_patient_is_not_same_result(self):
        self.assertGreater(relation_anomalies(slot_id=7,visits=[visit()],offers=[offer(request__patient_id=2)]),0)
    def test_accepted_different_interval_is_not_same_result(self):
        self.assertGreater(relation_anomalies(slot_id=7,visits=[visit()],offers=[offer(starts_at=(START+timedelta(minutes=1)).isoformat())]),0)
    def test_equivalent_instants_are_same_link(self):
        plus8=timezone(timedelta(hours=8));o=offer(starts_at=START.astimezone(plus8).isoformat())
        self.assertEqual(relation_anomalies(slot_id=7,visits=[visit()],offers=[o]),0)
    def test_missing_or_foreign_visit_is_not_linked(self):
        self.assertGreater(relation_anomalies(slot_id=7,visits=[],offers=[offer()]),0)
        self.assertGreater(relation_anomalies(slot_id=7,visits=[visit()|{'availability_slot_id':8}],offers=[]),0)
    def test_request_state_is_checked(self):
        self.assertGreater(relation_anomalies(slot_id=7,visits=[visit()],offers=[offer(request__state='WAITING')]),0)
    def test_unknown_status_fails_not_guess(self):
        with self.assertRaises(AvailabilityError):visit_instruction('OTHER',starts_at=START,now=NOW)
        with self.assertRaises(AvailabilityError):offer_instruction('OTHER',expires_at=START,now=NOW)
    def test_naive_time_rejected(self):
        with self.assertRaises(AvailabilityError):offer_instruction('PENDING',expires_at=START.replace(tzinfo=None),now=NOW)
    def test_source_facts_unmodified(self):
        v=[visit()];o=[offer()];old=copy.deepcopy((v,o,SLOT));relation_anomalies(slot_id=7,visits=v,offers=o);assess()
        self.assertEqual((v,o,SLOT),old)
    def test_manager_policy_and_recheck_agree_for_valid_combinations(self):
        for state in ('SCHEDULED','CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT','CANCELLED','NO_SHOW','RESCHEDULED'):
            vs=[visit(state)];i=assess_relations(slot=SLOT,visits=vs,offers=[],now=NOW)
            r=assessment(SLOT,i,NOW,clinical_count=int(state in ('CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT')))
            self.assertEqual(r.can_ask_manager_to_recheck,i.clear,state)
    def test_paging_is_global_not_current_page_clear(self):
        self.assertEqual(safe_page('2',41),(2,20,3));self.assertEqual(safe_page('90',41),(3,40,3))
        for v in ('-1','x','9'*10000,'１２',''):
            self.assertEqual(safe_page(v,41),(1,0,3))
    def test_empty_paging_and_invalid_bounds(self):
        self.assertEqual(safe_page(None,0),(1,0,1))
        for n,size in ((-1,20),(1,0),(1,201)):
            with self.assertRaises(AvailabilityError):safe_page('1',n,size)
    def test_origin_is_id_not_url_or_unicode_digits(self):
        self.assertEqual(origin_id('7'),7)
        for raw in ('https://outside.example/','//evil/','7/../../','７','0',str(2**63),True,7,None,'9'*10000):
            self.assertIsNone(origin_id(raw))

class CoordinationSourceContracts(unittest.TestCase):
    def test_routes_are_front_only(self):
        tree=ast.parse((ROOT/'workspaces/middleware.py').read_text())
        node=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROUTES' for t in n.targets))
        mapping={ast.literal_eval(k):ast.literal_eval(v) for k,v in zip(node.keys,node.values) if ast.literal_eval(k) in ('front_coordination_list','front_coordination_detail')}
        for n in ('front_coordination_list','front_coordination_detail'):self.assertEqual(mapping[n],{'FRONT_DESK'})
    def test_new_views_are_get_only_and_not_cached(self):
        tree=ast.parse((ROOT/'scheduling/front_coordination_views.py').read_text())
        for name in ('listing','detail'):
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            decorators={ast.unparse(x) for x in node.decorator_list}
            self.assertTrue({'login_required','never_cache','require_GET'}<=decorators)
    def test_new_selector_has_no_business_mutation_or_network(self):
        src=(ROOT/'scheduling/front_coordination_selectors.py').read_text();tree=ast.parse(src)
        for call in [ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)]:
            self.assertFalse(call.endswith(('.save','.delete','.create','.bulk_create','.bulk_update','.update_or_create')))
            if call.endswith('.update'):self.assertEqual(call,'base.update')
        literals={n.value for n in ast.walk(tree) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
        for field in ('chief_complaint','special_needs','phone','billing_address','home_address'):
            self.assertNotIn(field,literals)
        calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
        self.assertFalse({'requests.post','requests.get','emit'} & calls)
    def test_scope_check_precedes_slot_lock_and_reauthorizes(self):
        src=(ROOT/'scheduling/front_coordination_selectors.py').read_text();node=next(n for n in ast.parse(src).body if isinstance(n,ast.FunctionDef) and n.name=='read_coordination_slot');s=ast.unparse(node)
        self.assertLess(s.index('clinic_id=ctx.clinic_id'),s.index('lock_slots('))
        self.assertIn('_reauthorize(actor, original)',s);self.assertIn('transaction.atomic',[ast.unparse(x) for x in node.decorator_list])
    def test_new_queries_do_not_gain_post_permission(self):
        from adc_core.read_only_policy import allowed_in_read_only
        for n in ('front_coordination_list','front_coordination_detail'):
            self.assertTrue(allowed_in_read_only('GET',n));self.assertFalse(allowed_in_read_only('POST',n))
    def test_only_typed_origin_no_user_supplied_return_url(self):
        src=(ROOT/'scheduling/front_coordination_links.py').read_text()
        self.assertIn('visit.clinic_id != ctx.clinic_id',src)
        self.assertIn('availability_slot_id=sid',src)
        self.assertNotIn('request.GET',src);self.assertNotIn('redirect(',src)
    def test_no_submission_in_coordination_templates(self):
        for f in ('front_coordination_list.html','front_coordination_detail.html','front_coordination_error.html'):
            s=(ROOT/'templates/scheduling'/f).read_text()
            self.assertNotIn('method="post"',s);self.assertNotIn('onclick=',s)
        detail=(ROOT/'templates/scheduling/front_coordination_detail.html').read_text()
        self.assertIn('不暂停接收新预约',detail);self.assertIn('重新核对当前状态',detail)
    def test_guide_is_local_role_scoped_and_routes_exist(self):
        from guidance.catalog import GUIDES, choose_guide
        from adc_core.route_manifest import named_routes
        guide=GUIDES['front-coordination'];self.assertEqual(guide.roles,('FRONT_DESK',))
        self.assertEqual(choose_guide('FRONT_DESK','overview','出诊调整怎么协调'),'front-coordination')
        for step in guide.steps:self.assertIn(step.route,named_routes(ROOT))
    def test_source_booking_commands_unchanged(self):
        # Contract is enforced by package comparison in addition to these interfaces.
        src=(ROOT/'scheduling/front_coordination_views.py').read_text()
        for name in ('create_appointment','change_appointment','reschedule(','answer_offer(','confirm_availability_change'):
            self.assertNotIn(name,src)

if __name__=='__main__':unittest.main()
