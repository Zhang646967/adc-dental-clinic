"""Real Django/PostgreSQL acceptance scenarios. Must run in the Docker gate."""
from datetime import timedelta
from unittest.mock import patch
from django.test import TransactionTestCase,Client,override_settings
from django.urls import reverse
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from accounts.models import RoleAssignment,UserAccount
from adc_core.rules import RuleError
from scheduling.models import Visit
from scheduling.services import create_appointment
from portal.services import public_options
from tests.test_v04 import V04Fixture
from workspaces.context import SESSION_KEY,token_for
from workspaces.models import WorkspaceContext
from coordination.models import WaitRequest,WaitOffer,SchedulePlan
from coordination import services as co

class V07Fixture(V04Fixture):
 def setup07(self):self.set_up_v04();self.c=Client()
 def ctx(self,c=None):return WorkspaceContext.objects.get(pk=(c or self.c).session[SESSION_KEY])
 def post(self,name,data=None,args=None,c=None):
  c=c or self.c;payload=dict(data or {});payload['workspace_token']=token_for(self.ctx(c))
  return c.post(reverse(name,args=args),payload)
 def login(self,user,role=None,clinic=None,c=None):
  c=c or self.c;c.force_login(user);s=c.session;s.pop(SESSION_KEY,None);s.save();c.get(reverse('select_role'))
  if role:self.assertEqual(self.post('activate_role',{'role':role},c=c).status_code,302)
  if clinic:self.assertEqual(self.post('activate_clinic',{'clinic':clinic.pk},c=c).status_code,302)
  return c
 def join(self,actor=None,**kwargs):
  return co.join_waitlist(actor=actor or self.pa,clinic_id=self.a.pk,earliest=self.t,latest=self.t+timedelta(hours=2),**kwargs)
 def offered(self):
  e=self.join();p=co.create_plan(actor=self.manager,clinic_id=self.a.pk);co.publish_plan(actor=self.manager,plan_id=p.pk)
  return e,p,WaitOffer.objects.get(request=e)

class WorkspaceAcceptanceTests(V07Fixture,TransactionTestCase):
 def setUp(self):self.setup07()
 def test_login_success_activates_single_role(self):
  self.front.set_password('test-password-1234');self.front.save(update_fields=['password'])
  r=self.c.post(reverse('login'),{'username':self.front.username,'password':'test-password-1234'})
  self.assertEqual(r.status_code,302);self.assertEqual(r.url,reverse('frontdesk_home'));self.assertEqual(self.ctx().role,'FRONT_DESK');self.assertIsNone(self.ctx().clinic_id)
 def test_uninitialized_session_requires_activation(self):
  self.login(self.manager);self.assertEqual(self.c.get(reverse('manager_home')).url,reverse('select_role'))
 def test_role_choices_from_database(self):
  self.login(self.manager);r=self.c.get(reverse('select_role'));self.assertContains(r,'诊所主管');self.assertNotContains(r,'value="FINANCE"')
 def test_ungranted_role_denied(self):
  self.login(self.manager);self.assertEqual(self.post('activate_role',{'role':'FINANCE'}).status_code,403)
 def test_manager_enters_then_selects_clinic(self):
  self.login(self.manager,'MANAGER');self.assertIsNone(self.ctx().clinic_id);self.assertContains(self.c.get(reverse('manager_home')),self.a.name)
 def test_no_clinic_means_no_operational_data(self):
  self.login(self.manager,'MANAGER');self.assertEqual(self.c.get(reverse('operations_dashboard')).status_code,302)
 def test_clinic_choices_exclude_ungranted_store(self):
  self.login(self.manager,'MANAGER');r=self.c.get(reverse('manager_home'));self.assertNotContains(r,self.b.name)
 def test_ungranted_clinic_post_denied(self):
  self.login(self.manager,'MANAGER');self.assertEqual(self.post('activate_clinic',{'clinic':self.b.pk}).status_code,403)
 def test_select_clinic_and_dashboard(self):
  self.login(self.manager,'MANAGER',self.a);self.assertEqual(self.ctx().clinic_id,self.a.pk);self.assertContains(self.c.get(reverse('manager_home')),'排程建议')
 def test_role_switch_clears_scope(self):
  self.manager.dentist=self.d2;self.manager.save(update_fields=['dentist']);RoleAssignment.objects.create(user=self.manager,role='DENTIST',scope_kind='SELF_DENTIST')
  self.login(self.manager,'MANAGER',self.a);self.post('activate_role',{'role':'DENTIST'});self.assertIsNone(self.ctx().clinic_id)
 def test_clinic_switch_keeps_role(self):
  RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
  self.login(self.manager,'MANAGER',self.a);self.post('activate_clinic',{'clinic':self.b.pk});self.assertEqual(self.ctx().role,'MANAGER');self.assertEqual(self.ctx().clinic_id,self.b.pk)
 def test_revoked_role_invalidates_old_page(self):
  self.login(self.manager,'MANAGER',self.a);RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
  self.assertEqual(self.c.get(reverse('manager_home')).url,reverse('select_role'))
 def test_old_tab_token_rejected(self):
  self.login(self.front,'FRONT_DESK',self.a);old=token_for(self.ctx());self.post('activate_clinic',{'clinic':self.b.pk})
  r=self.c.post(reverse('waitlist_join'),{'workspace_token':old});self.assertEqual(r.status_code,409);self.assertFalse(WaitRequest.objects.exists())
 def test_forged_context_rejected(self):
  self.login(self.manager,'MANAGER',self.a);self.assertEqual(self.c.post(reverse('schedule_plans'),{'confirmed':'on','workspace_token':'forged'}).status_code,409)
 def test_technical_role_has_no_business_bypass(self):
  self.login(self.tech,'SYSADMIN');self.assertEqual(self.c.get(reverse('patients')).status_code,403)
 def test_patient_not_auto_promoted_to_staff(self):
  self.login(self.pa,'PATIENT');self.assertEqual(self.c.get(reverse('doctor_home')).status_code,403)
 def test_context_is_same_role_scope_binding(self):
  RoleAssignment.objects.create(user=self.front,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
  self.login(self.front,'MANAGER');self.assertEqual(self.post('activate_clinic',{'clinic':self.a.pk}).status_code,403)
 def test_no_grants_empty_selection(self):
  u=UserAccount.objects.create_user(username='none');self.login(u);self.assertContains(self.c.get(reverse('select_role')),'尚未')
 def test_wrong_role_guide_is_404(self):
  self.login(self.pa,'PATIENT');self.assertEqual(self.c.get(reverse('guide_task',args=['manager-plan'])).status_code,404)
 def test_guide_is_readonly(self):
  self.login(self.pa,'PATIENT');r=self.c.get(reverse('guide_task',args=['patient-book']));self.assertEqual(r.status_code,200);self.assertFalse(Visit.objects.exists())
 def test_context_change_clears_running_guide(self):
  self.login(self.front,'FRONT_DESK',self.a);self.c.get(reverse('patients')+'?guide=front-create&step=1')
  self.assertIn('adc_guide',self.c.session);self.post('activate_clinic',{'clinic':self.b.pk})
  self.assertNotContains(self.c.get(reverse('frontdesk_home')),'guide-panel')
 def test_active_role_narrows_service_access(self):
  self.login(self.front,'FRONT_DESK',self.a);u=UserAccount.objects.get(pk=self.front.pk);u._adc_workspace=self.ctx()
  with self.assertRaises(PermissionDenied):self.book(actor=u,slot_id=self.slot2.pk)
 def test_missing_context_on_post_is_not_mutation(self):
  self.login(self.front,'FRONT_DESK',self.a);self.assertEqual(self.c.post(reverse('visit_create'),{}).status_code,409)
 def test_readonly_allows_role_and_scope_selection(self):
  with override_settings(ADC_READ_ONLY=True):self.login(self.manager,'MANAGER',self.a)
 def test_ai_result_is_manual_guide(self):
  self.login(self.pa,'PATIENT')
  r=self.c.post(reverse('assistant_api',args=['patient']),data='{"message":"我想预约","consent":false}',content_type='application/json',HTTP_X_ADC_WORKSPACE=token_for(self.ctx()))
  self.assertEqual(r.status_code,200);self.assertEqual(r.json()['guide_id'],'patient-book');self.assertFalse(r.json()['actions_executed'])
 def test_ai_rechecks_switched_context(self):
  from assistants.services import respond
  self.login(self.pa,'PATIENT');u=UserAccount.objects.get(pk=self.pa.pk);u._adc_workspace=self.ctx()
  def switch(*args):
   WorkspaceContext.objects.filter(pk=u._adc_workspace.pk).update(revision=u._adc_workspace.revision+1);return 'book'
  with override_settings(AI_MODE='remote'),patch('assistants.provider.classify',side_effect=switch):
   with self.assertRaises(PermissionDenied):respond(user=u,audience='patient',message='预约',consent=True)

class WaitlistAcceptanceTests(V07Fixture,TransactionTestCase):
 def setUp(self):self.setup07()
 def test_join_is_not_booking(self):self.join();self.assertFalse(Visit.objects.exists())
 def test_duplicate_active_request_rejected(self):
  self.join()
  with self.assertRaises(RuleError):self.join()
 def test_staff_can_register_same_rule(self):
  e=self.join(actor=self.front,patient_no=self.p1.patient_no);self.assertEqual(e.patient_id,self.p1.pk)
 def test_patient_cannot_select_other_identity(self):
  e=self.join(patient_no=self.p2.patient_no);self.assertEqual(e.patient_id,self.p1.pk)
 def test_future_range_required(self):
  with self.assertRaises(RuleError):co.join_waitlist(actor=self.pa,clinic_id=self.a.pk,earliest=timezone.now()-timedelta(hours=1),latest=self.t)
 def test_plan_is_advisory(self):
  self.join();p=co.create_plan(actor=self.manager,clinic_id=self.a.pk);self.assertTrue(p.suggestions);self.assertFalse(Visit.objects.exists());self.assertFalse(WaitOffer.objects.exists())
 def test_publish_creates_hold_not_booking(self):
  e,p,o=self.offered();self.assertEqual(o.state,'PENDING');self.assertFalse(Visit.objects.exists())
 def test_accept_creates_one_booking_and_is_idempotent(self):
  e,p,o=self.offered();a=co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True);b=co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True)
  self.assertEqual(a.visit_id,b.visit_id);self.assertEqual(Visit.objects.count(),1)
 def test_other_patient_cannot_accept_offer(self):
  e,p,o=self.offered()
  with self.assertRaises(PermissionDenied):co.answer_offer(actor=self.pb,offer_id=o.pk,accept=True)
 def test_manager_cannot_confirm_for_patient(self):
  e,p,o=self.offered()
  with self.assertRaises(PermissionDenied):co.answer_offer(actor=self.manager,offer_id=o.pk,accept=True)
 def test_front_can_confirm_explicitly(self):
  e,p,o=self.offered();co.answer_offer(actor=self.front,offer_id=o.pk,accept=True);self.assertEqual(Visit.objects.count(),1)
 def test_hold_blocks_regular_booking(self):
  e,p,o=self.offered()
  with self.assertRaises(RuleError):self.book(patient_no=self.p2.patient_no,start=o.starts_at,end=o.ends_at)
 def test_hold_is_hidden_from_public_availability(self):
  e,p,o=self.offered();opts=public_options(self.pb,clinic_id=self.a.pk,day=o.starts_at.astimezone(timezone.get_current_timezone()).date())
  # Exact candidate test uses the service representation below; reject held cell.
  self.assertFalse(any(x['slot'].pk==o.slot_id and x['start']==o.starts_at for x in opts))
 def test_decline_reopens_request_without_booking(self):
  e,p,o=self.offered();co.answer_offer(actor=self.pa,offer_id=o.pk,accept=False);e.refresh_from_db();self.assertEqual(e.state,'WAITING');self.assertFalse(Visit.objects.exists())
 def test_withdraw_revokes_offer(self):
  e,p,o=self.offered();co.withdraw(actor=self.pa,entry_id=e.pk);o.refresh_from_db();self.assertEqual(o.state,'REVOKED')
 def test_expired_offer_cannot_accept(self):
  e,p,o=self.offered();WaitOffer.objects.filter(pk=o.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
  with self.assertRaises(RuleError):co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True)
 def test_recycle_expired_request(self):
  e,p,o=self.offered();WaitOffer.objects.filter(pk=o.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
  self.assertEqual(co.expire_clinic_offers(actor=self.manager,clinic_id=self.a.pk),1);e.refresh_from_db();self.assertEqual(e.state,'WAITING')
 def test_old_plan_refuses_publish(self):
  self.join();p=co.create_plan(actor=self.manager,clinic_id=self.a.pk);SchedulePlan.objects.filter(pk=p.pk).update(created_at=timezone.now()-timedelta(minutes=16))
  with self.assertRaises(RuleError):co.publish_plan(actor=self.manager,plan_id=p.pk)
 def test_changed_request_refuses_publish(self):
  e=self.join();p=co.create_plan(actor=self.manager,clinic_id=self.a.pk);co.withdraw(actor=self.pa,entry_id=e.pk)
  with self.assertRaises(RuleError):co.publish_plan(actor=self.manager,plan_id=p.pk)
  self.assertFalse(WaitOffer.objects.exists())
 def test_conflicting_booking_blocks_publish(self):
  self.join();p=co.create_plan(actor=self.manager,clinic_id=self.a.pk);row=p.suggestions[0]
  from datetime import datetime
  self.book(patient_no=self.p2.patient_no,start=datetime.fromisoformat(row['start']),end=datetime.fromisoformat(row['end']))
  with self.assertRaises(RuleError):co.publish_plan(actor=self.manager,plan_id=p.pk)
  self.assertFalse(WaitOffer.objects.exists())
 def test_publication_retry_does_not_duplicate(self):
  e,p,o=self.offered();co.publish_plan(actor=self.manager,plan_id=p.pk);self.assertEqual(WaitOffer.objects.count(),1)
 def test_audit_failure_rolls_back_offer_acceptance(self):
  e,p,o=self.offered()
  with patch('coordination.services.emit',side_effect=RuntimeError('synthetic failure')):
   with self.assertRaises(RuntimeError):co.answer_offer(actor=self.pa,offer_id=o.pk,accept=True)
  o.refresh_from_db();self.assertEqual(o.state,'PENDING');self.assertFalse(Visit.objects.exists())
 def test_readonly_disallows_join(self):
  with override_settings(ADC_READ_ONLY=True):
   with self.assertRaises(PermissionDenied):self.join()
 def test_patient_only_sees_own_waitlist(self):
  self.join();self.login(self.pb,'PATIENT');self.assertNotContains(self.c.get(reverse('waitlist')),self.p1.name)
 def test_manager_page_does_not_display_patient_name(self):
  self.join();self.login(self.manager,'MANAGER',self.a);r=self.c.get(reverse('waitlist'));self.assertEqual(r.status_code,200);self.assertNotContains(r,self.p1.name)
 def test_plan_and_offer_templates_render(self):
  e,p,o=self.offered();self.login(self.manager,'MANAGER',self.a);self.assertEqual(self.c.get(reverse('schedule_plan',args=[p.pk])).status_code,200)
  self.login(self.pa,'PATIENT');self.assertEqual(self.c.get(reverse('wait_offer',args=[o.pk])).status_code,200)
