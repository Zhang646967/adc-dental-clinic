"""Executable reference rules, not evidence of Django/PostgreSQL behavior."""
import ast
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from guidance.result_rules import WaitFact, OfferFact, VisitFact, assess_wait
ROOT=Path(__file__).resolve().parents[1]

class ResultRuleTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,9,27,7,tzinfo=timezone.utc)
        self.start=self.now+timedelta(days=1)
        self.visit=VisitFact(17,'V-DEMO',1,2,3,self.start,self.start+timedelta(minutes=30),'SCHEDULED')
        self.offer=OfferFact(4,'PENDING',3,2,self.start,self.visit.end,self.now+timedelta(minutes=15))
        self.wait=WaitFact(1,1,2,'OFFERED',self.start,self.start+timedelta(hours=2),(self.offer,))
    def code(self,w=None,now=None): return assess_wait(w or self.wait,now or self.now).code
    def booked(self,**visit_changes):
        return replace(self.wait,state='BOOKED',offers=(replace(self.offer,state='ACCEPTED',visit=replace(self.visit,**visit_changes)),))
    def test_pending_before_expiry(self):self.assertEqual(self.code(),'NEEDS_CONFIRMATION')
    def test_expiry_exact_boundary(self):self.assertEqual(self.code(now=self.offer.expires),'OFFER_EXPIRED')
    def test_expiry_after_boundary(self):self.assertEqual(self.code(now=self.offer.expires+timedelta(seconds=1)),'OFFER_EXPIRED')
    def test_waiting_no_offer(self):self.assertEqual(self.code(replace(self.wait,state='WAITING',offers=())),'WAITING')
    def test_window_passed(self):self.assertEqual(self.code(replace(self.wait,state='WAITING',offers=()),self.wait.latest),'WINDOW_PASSED')
    def test_withdrawn(self):self.assertEqual(self.code(replace(self.wait,state='WITHDRAWN',offers=())),'WITHDRAWN')
    def test_booked_found(self):self.assertEqual(self.code(self.booked()),'BOOKING_FOUND')
    def test_expiry_does_not_erase_accepted_booking(self):self.assertEqual(self.code(self.booked(),self.start+timedelta(days=3)),'BOOKING_FOUND')
    def test_later_cancellation_not_still_booked(self):self.assertEqual(self.code(self.booked(status='CANCELLED')),'BOOKING_CANCELLED')
    def test_later_reschedule(self):self.assertEqual(self.code(self.booked(status='RESCHEDULED')),'BOOKING_REPLACED')
    def test_check_in_not_treatment(self):self.assertEqual(self.code(self.booked(status='CHECKED_IN')),'CHECKED_IN')
    def test_completion_not_payment(self):
        result=assess_wait(self.booked(status='COMPLETED'),self.now)
        self.assertEqual(result.code,'VISIT_COMPLETED');self.assertIn('不检查账单金额或付款',result.explanation)
    def test_no_treatment_closed(self):self.assertEqual(self.code(self.booked(status='CLOSED_NO_TREATMENT')),'VISIT_CLOSED')
    def test_no_show(self):self.assertEqual(self.code(self.booked(status='NO_SHOW')),'BOOKING_NO_SHOW')
    def test_unknown_visit_state(self):self.assertEqual(self.code(self.booked(status='HACK')),'INCONSISTENT')
    def test_unknown_request_state(self):self.assertEqual(self.code(replace(self.wait,state='HACK')),'INCONSISTENT')
    def test_missing_visit(self):self.assertEqual(self.code(replace(self.wait,state='BOOKED',offers=(replace(self.offer,state='ACCEPTED'),))),'INCONSISTENT')
    def test_missing_accepted_offer(self):self.assertEqual(self.code(replace(self.wait,state='BOOKED',offers=())),'INCONSISTENT')
    def test_missing_pending_offer(self):self.assertEqual(self.code(replace(self.wait,offers=())),'INCONSISTENT')
    def test_wrong_patient(self):self.assertEqual(self.code(self.booked(patient_id=9)),'INCONSISTENT')
    def test_wrong_visit_clinic(self):self.assertEqual(self.code(self.booked(clinic_id=9)),'INCONSISTENT')
    def test_wrong_visit_dentist(self):self.assertEqual(self.code(self.booked(dentist_id=9)),'INCONSISTENT')
    def test_wrong_visit_time(self):self.assertEqual(self.code(self.booked(start=self.start+timedelta(hours=1))),'INCONSISTENT')
    def test_duplicate_accepted(self):
        w=self.booked();self.assertEqual(self.code(replace(w,offers=w.offers*2)),'INCONSISTENT')
    def test_two_pending(self):self.assertEqual(self.code(replace(self.wait,offers=(self.offer,self.offer))),'INCONSISTENT')
    def test_pending_and_accepted(self):self.assertEqual(self.code(replace(self.booked(),offers=(self.offer,self.booked().offers[0]))),'INCONSISTENT')
    def test_accepted_but_request_waiting(self):self.assertEqual(self.code(replace(self.booked(),state='WAITING')),'INCONSISTENT')
    def test_withdrawn_but_pending(self):self.assertEqual(self.code(replace(self.wait,state='WITHDRAWN')),'INCONSISTENT')
    def test_pending_with_visit(self):self.assertEqual(self.code(replace(self.wait,offers=(replace(self.offer,visit=self.visit),))),'INCONSISTENT')
    def test_offer_outside_window(self):self.assertEqual(self.code(replace(self.wait,latest=self.start+timedelta(minutes=5))),'INCONSISTENT')
    def test_offer_wrong_clinic(self):self.assertEqual(self.code(replace(self.wait,offers=(replace(self.offer,clinic_id=8),))),'INCONSISTENT')
    def test_timezone_naive_rejected(self):self.assertEqual(self.code(replace(self.wait,earliest=self.start.replace(tzinfo=None))),'INCONSISTENT')
    def test_end_before_start(self):self.assertEqual(self.code(replace(self.wait,latest=self.start-timedelta(hours=1))),'INCONSISTENT')
    def test_offer_expiry_after_start(self):self.assertEqual(self.code(replace(self.wait,offers=(replace(self.offer,expires=self.start+timedelta(minutes=1)),))),'INCONSISTENT')
    def test_impossible_extra_rows(self):self.assertEqual(self.code(replace(self.wait,offers=(self.offer,)*4)),'INCONSISTENT')
    def test_evaluation_does_not_mutate(self):
        before=repr(self.booked());assess_wait(self.booked(),self.now);self.assertEqual(before,repr(self.booked()))
    def test_id_is_exact_saved_visit_not_latest_appointment(self):
        r=assess_wait(self.booked(),self.now);self.assertEqual(r.target_id,17);self.assertEqual(r.visit.number,'V-DEMO')
    def test_refuses_unfiltered_offer_states(self):self.assertEqual(self.code(replace(self.wait,offers=(replace(self.offer,state='DECLINED'),))),'INCONSISTENT')

class ResultArchitectureTests(unittest.TestCase):
    def test_new_modules_have_no_business_write_calls(self):
        for file in ('result_rules.py','result_selectors.py','result_views.py'):
            tree=ast.parse((ROOT/'guidance'/file).read_text())
            methods={n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)}
            self.assertFalse(methods & {'save','create','delete','update_or_create','bulk_create','bulk_update','get_or_create'},file)
    def test_adapter_projects_no_sensitive_fields(self):
        text=(ROOT/'guidance/result_selectors.py').read_text()
        self.assertNotIn('__clinical_note',text);self.assertNotIn('__allergy',text);self.assertNotIn('__password',text)
    def test_view_context_rechecked_after_read(self):
        text=(ROOT/'guidance/result_views.py').read_text()
        self.assertLess(text.index('fact = load_wait_fact'),text.index('_still_owns(request, fact)  #'))
        self.assertIn('@never_cache',text);self.assertIn('@require_POST',text)
    def test_navigation_has_explicit_check(self):
        self.assertIn('guide_result_wait',(ROOT/'templates/coordination/waitlist.html').read_text())
        self.assertIn('核对这条候补是否已转预约',(ROOT/'templates/coordination/waitlist.html').read_text())
    def test_route_default_not_open_to_managers(self):
        tree=ast.parse((ROOT/'workspaces/middleware.py').read_text())
        assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROUTES' for t in n.targets))
        value=next(v for k,v in zip(assignment.value.keys,assignment.value.values) if isinstance(k,ast.Constant) and k.value=='guide_result_wait')
        self.assertEqual(ast.literal_eval(value),{'PATIENT','FRONT_DESK'})

if __name__=='__main__': unittest.main()
