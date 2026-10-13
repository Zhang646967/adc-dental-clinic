"""Framework-independent evidence. No Django or database execution claimed."""
import ast,itertools,json,re,unittest
from pathlib import Path
from datetime import datetime,timedelta
from coordination.solver import maximum_matching,overlaps
from workspaces.rules import ROLES,CLINIC_ROLES,matches_context
from guidance.catalog import GUIDES,choose_guide
from assistants.protocol import local_intent,parse_decision,AIProtocolError
R=Path(__file__).resolve().parents[1]
def brute(ids,edges):
 def search(n,used):
  if n==len(ids):return 0
  return max([search(n+1,used)]+[1+search(n+1,used|{c}) for c in edges.get(ids[n],[]) if c not in used])
 return search(0,set())
class MatchingChecks(unittest.TestCase):
 def test_all_512_three_by_three_graphs(self):
  # 512 graph instances, reported as ONE test method, not 512 business tests.
  for mask in range(512):
   e={i:[j for j in range(3) if mask&(1<<(i*3+j))] for i in range(3)}
   r=maximum_matching(range(3),e)
   self.assertEqual(len(r.pairs),brute(tuple(range(3)),e),mask)
   self.assertEqual(len({v for _,v in r.pairs}),len(r.pairs))
 def test_augmenting_path_improves_naive_greedy(self):
  r=maximum_matching([1,2],{1:['a','b'],2:['a']});self.assertEqual(dict(r.pairs),{1:'b',2:'a'})
 def test_earlier_matched_request_retained(self):
  r=maximum_matching([1,2,3],{1:['a'],2:['a'],3:['a']});self.assertEqual(r.pairs,((1,'a'),))
 def test_empty(self):self.assertFalse(maximum_matching([] ,{}).pairs)
 def test_unassigned(self):self.assertEqual(maximum_matching([1,2],{}).unassigned,(1,2))
 def test_duplicate_request_rejected(self):
  with self.assertRaises(ValueError):maximum_matching([1,1],{})
 def test_request_limit(self):
  with self.assertRaises(ValueError):maximum_matching(range(61),{})
 def test_edge_limit(self):
  with self.assertRaises(ValueError):maximum_matching(range(60),{i:range(201) for i in range(60)})
 def test_duplicate_cell_ignored(self):self.assertEqual(len(maximum_matching([1],{1:['a','a']}).pairs),1)
 def test_deterministic(self):self.assertEqual(maximum_matching([1,2],{1:[2,1],2:[1,2]}),maximum_matching([1,2],{1:[2,1],2:[1,2]}))
 def test_explicit_bounded_optimality_label(self):self.assertEqual(maximum_matching([],{}).status,'OPTIMAL_FOR_ENUMERATED_GRAPH')
 def test_adjacent_not_overlapping(self):self.assertFalse(overlaps(1,2,2,3))
 def test_partial_overlap(self):self.assertTrue(overlaps(1,3,2,4))
 def test_containment_overlap(self):self.assertTrue(overlaps(1,5,2,3))
class WorkspaceGuideChecks(unittest.TestCase):
 def test_seven_role_types_not_clinic_variants(self):self.assertEqual(len(ROLES),7);self.assertFalse(any('店' in k for k in ROLES))
 def test_only_two_clinic_roles(self):self.assertEqual(set(CLINIC_ROLES),{'MANAGER','FRONT_DESK'})
 def test_current_context_payload(self):self.assertTrue(matches_context({'key':'k','uid':1,'role':'MANAGER','clinic':2,'revision':3},'k',1,'MANAGER',2,3))
 def test_scope_switch_invalidates_payload(self):self.assertFalse(matches_context({'key':'k','uid':1,'role':'MANAGER','clinic':2,'revision':3},'k',1,'MANAGER',4,4))
 def test_role_switch_invalidates_payload(self):self.assertFalse(matches_context({'key':'k','uid':1,'role':'MANAGER','clinic':2,'revision':3},'k',1,'DENTIST',None,4))
 def test_guide_ids_unique_and_nonempty(self):self.assertTrue(GUIDES);self.assertTrue(all(k==g.key and len(g.steps)>=2 for k,g in GUIDES.items()))
 def test_guide_roles_defined(self):self.assertTrue(all(set(g.roles)<=set(ROLES) for g in GUIDES.values()))
 def test_guide_routes_declared_without_model_urls(self):
  # Walk actual include() declarations instead of a historical four-file list.
  from adc_core.route_manifest import named_routes
  names=set(named_routes(R))
  self.assertTrue(all(s.route in names for g in GUIDES.values() for s in g.steps))
 def test_clinical_not_instruction_guide(self):self.assertIsNone(choose_guide('PATIENT','clinical'))
 def test_patient_cannot_get_manager_plan(self):self.assertIsNone(choose_guide('PATIENT','planning'))
 def test_manager_plan_is_role_specific(self):self.assertEqual(choose_guide('MANAGER','planning'),'manager-plan')
 def test_switch_guide(self):self.assertEqual(choose_guide('DENTIST','help','切换身份'),'switch-role')
 def test_accessible_display_choice(self):self.assertEqual(choose_guide('PATIENT','accessibility'),'display-mode')
 def test_waitlist_keyword_before_cancellation(self):self.assertEqual(local_intent('退出候补','patient'),'waitlist')
 def test_manager_schedule_classification(self):self.assertEqual(local_intent('生成排程','staff'),'planning')
 def test_medical_query_not_waitlist(self):self.assertEqual(local_intent('牙痛要怎么排队','patient'),'clinical')
 def test_provider_cannot_emit_url(self):
  with self.assertRaises(AIProtocolError):parse_decision(json.dumps({'intent':'help','confidence':1,'url':'/admin/'}),'patient')
 def test_step_ui_never_clicks_business_controls(self):
  js=(R/'static/guidance.js').read_text();self.assertNotIn('.submit(',js);self.assertNotIn('.click()',js)
 def test_migration_history_present(self):
  self.assertTrue((R/'care/migrations/0003_correction_publication_guard.py').exists());self.assertTrue((R/'workspaces/migrations/0001_initial.py').exists())
 def test_post_forms_have_context_token(self):
  for folder in ('workspaces','coordination'):
   for f in (R/'templates'/folder).rglob('*.html'):
    s=f.read_text()
    if 'method="post"' in s:self.assertIn('{% workspace_token %}',s,str(f))
