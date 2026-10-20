"""SU-31 real Django/PostgreSQL tests. Authored; execution is reported separately.

Use real middleware, ORM, shared locks and existing write commands. Failure
injection targets a query or rule/clock only, never replaces ORM with a fake.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import connection, close_old_connections, DatabaseError
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from care.models import AuditEvent, Invoice
from coordination.models import WaitRequest, WaitOffer, SchedulePlan
from coordination.services import answer_offer
from patients.models import Patient
from scheduling.models import AvailabilitySlot, Visit
from scheduling.services import create_appointment, change_appointment, reschedule
from scheduling.front_coordination_selectors import (read_coordination_slot,
    list_coordination_slots, require_front_coordination)
from scheduling.front_coordination_links import visit_return_slot, offer_return_slot, visit_chain_context
from tests.fixtures import FixtureMixin
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext

class FrontCoordinationTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.make_fixture()
        for user,role in ((self.front,'FRONT_DESK'),(self.front2,'FRONT_DESK'),(self.manager,'MANAGER')):
            user._adc_workspace=WorkspaceContext.objects.create(user=user,role=role,clinic=self.a,revision=1)
    def read(self, **kw):
        return read_coordination_slot(actor=self.front,slot_id=self.slot1.pk,**kw)
    def client_front(self, csrf=False):
        c=WorkspaceClient(enforce_csrf_checks=csrf);c.force_login(self.front);return c
    def make_offer(self):
        e=WaitRequest.objects.create(patient=self.p1,clinic=self.a,preferred_dentist=self.d1,
            earliest=self.t,latest=self.t+timedelta(hours=4),created_by=self.front,state='OFFERED')
        p=SchedulePlan.objects.create(clinic=self.a,created_by=self.manager,state='PUBLISHED',published_at=timezone.now())
        return WaitOffer.objects.create(request=e,plan=p,slot=self.slot1,starts_at=self.t+timedelta(hours=1),
            ends_at=self.t+timedelta(hours=1,minutes=30),expires_at=timezone.now()+timedelta(minutes=10))
    def business_state(self):
        return {m.__name__:list(m.objects.order_by('pk').values()) for m in
            (Patient,Visit,WaitRequest,WaitOffer,AvailabilitySlot,Invoice,AuditEvent,RoleAssignment)}
    def test_empty_future_gives_recheck_not_completion(self):
        r=self.read();self.assertEqual(r['assessment'].code,'RECHECK')
        self.assertEqual(r['visits'],[]);self.assertIn('未暂停',r['assessment'].explanation)
    def test_projection_writes_no_business_records(self):
        self.book();self.make_offer();before=self.business_state();self.read()
        self.assertEqual(self.business_state(),before)
    def test_only_exact_source_visits_are_returned(self):
        v=self.book();other=create_appointment(actor=self.front2,patient_no=self.p2.patient_no,
            slot_id=self.slot1.pk,start=self.t+timedelta(hours=2),end=self.t+timedelta(hours=3))
        rows=self.read()['visits'];self.assertEqual({r['id'] for r in rows},{v.pk,other.pk})
    def test_cross_clinic_and_missing_targets_are_indistinguishable(self):
        errors=[]
        for sid in (self.slot2.pk,999999):
            with self.assertRaises(PermissionDenied) as ctx:read_coordination_slot(actor=self.front,slot_id=sid)
            errors.append(str(ctx.exception))
        self.assertEqual(errors[0],errors[1])
    def test_list_does_not_borrow_second_clinic_grant(self):
        r=list_coordination_slots(actor=self.front);self.assertEqual([s['id'] for s in r['rows']],[self.slot1.pk])
    def test_manager_cannot_access_patient_projection(self):
        with self.assertRaises(PermissionDenied):read_coordination_slot(actor=self.manager,slot_id=self.slot1.pk)
    def test_assigned_front_role_does_not_override_active_manager(self):
        RoleAssignment.objects.create(user=self.front,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        self.front._adc_workspace=WorkspaceContext.objects.create(user=self.front,role='MANAGER',clinic=self.a,revision=1)
        with self.assertRaises(PermissionDenied):self.read()
    def test_superuser_does_not_bypass(self):
        self.tech._adc_workspace=WorkspaceContext.objects.create(user=self.tech,role='SYSADMIN',revision=1)
        with self.assertRaises(PermissionDenied):read_coordination_slot(actor=self.tech,slot_id=self.slot1.pk)
    def test_no_workspace_rejected(self):
        del self.front._adc_workspace
        with self.assertRaises(PermissionDenied):self.read()
    def test_old_workspace_revision_rejected(self):
        WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(revision=2)
        with self.assertRaises(PermissionDenied):self.read()
    def test_revoked_grant_rejected(self):
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.read()
    def test_suspended_actor_rejected(self):
        UserAccount.objects.filter(pk=self.front.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.read()
    def test_disabled_clinic_rejected(self):
        type(self.a).objects.filter(pk=self.a.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.read()
    def test_pending_offer_is_effective_and_cannot_show_clear(self):
        self.make_offer();r=self.read();self.assertEqual(r['assessment'].code,'COORDINATE')
        self.assertEqual(r['impact'].effective_offers,1);self.assertTrue(r['offers'][0]['offer'])
    def test_offer_expiry_is_live_and_query_does_not_recycle(self):
        o=self.make_offer()
        with patch('scheduling.front_coordination_selectors.timezone.now',return_value=o.expires_at):r=self.read()
        self.assertEqual(r['impact'].effective_offers,0);self.assertEqual(r['impact'].expired_pending,1)
        self.assertEqual(r['assessment'].code,'RECHECK');o.refresh_from_db();self.assertEqual(o.state,'PENDING')
    def test_accepted_is_not_a_second_hold(self):
        o=self.make_offer();answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        with patch('scheduling.front_coordination_selectors.timezone.now',return_value=o.expires_at+timedelta(hours=1)):r=self.read()
        self.assertEqual(r['impact'].blocking_visits,1);self.assertEqual(r['impact'].effective_offers,0)
        self.assertEqual(r['offers'][0]['visit_id'],r['visits'][0]['id']);self.assertTrue(r['offers'][0]['appointment'])
    def test_cancelled_visit_preserves_accepted_history(self):
        o=self.make_offer();answer_offer(actor=self.front,offer_id=o.pk,accept=True);o.refresh_from_db()
        change_appointment(actor=self.front,visit_id=o.visit_id,expected_version=0,action='cancel',party='PATIENT',reason='合成测试')
        r=self.read();self.assertEqual(r['assessment'].code,'RECHECK')
        self.assertTrue(r['offers'][0]['appointment']);self.assertEqual(r['visits'][0]['group'],'history')
    def test_checked_in_record_protected(self):
        v=self.book();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        r=self.read();self.assertEqual(r['assessment'].code,'CARE_PROTECTED');self.assertFalse(r['visits'][0]['reschedule'])
    def test_new_booking_after_read_invalidates_informal_clear(self):
        self.assertEqual(self.read()['assessment'].code,'RECHECK');self.book()
        self.assertEqual(self.read()['assessment'].code,'COORDINATE')
    def test_no_patient_names_or_contact_clinical_fields_in_projection(self):
        v=self.book(chief_complaint='私密测试主诉',special_needs='私密测试备注');r=self.read()
        text=repr(r);self.assertNotIn(self.p1.name,text);self.assertNotIn('私密测试主诉',text);self.assertNotIn('私密测试备注',text)
        self.assertEqual(r['visits'][0]['patient_no'],self.p1.patient_no)
    def test_link_anomaly_suppresses_identifiers_and_deep_links(self):
        self.book()
        with patch('scheduling.front_coordination_selectors.relation_anomalies',return_value=1):r=self.read()
        self.assertTrue(r['unsafe']);self.assertEqual(r['visits'],[]);self.assertNotIn(self.p1.patient_no,repr(r))
    def test_pagination_never_mistakes_page_two_for_empty_source(self):
        for n in range(21):
            Visit.objects.create(patient=self.p1,dentist=self.d1,clinic=self.a,availability_slot=self.slot1,
                scheduled_start=self.t,scheduled_end=self.t+timedelta(minutes=30),status='CANCELLED',
                cancellation_party='CLINIC',cancellation_reason='合成历史')
        v=self.book(start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2))
        r=self.read(visit_page='2');self.assertEqual(r['visit_count'],22);self.assertEqual(len(r['visits']),2)
        self.assertEqual(r['impact'].blocking_visits,1);self.assertEqual(r['assessment'].code,'COORDINATE')
    def test_effective_offer_join_does_not_multiply_appointment_count(self):
        self.book();self.make_offer();r=list_coordination_slots(actor=self.front)
        self.assertEqual(r['rows'][0]['scheduled_count'],1);self.assertTrue(r['rows'][0]['has_effective_offer'])
    def test_inactive_slot_remains_queryable_but_not_clear(self):
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(is_active=False)
        self.assertEqual(self.read()['assessment'].code,'INACTIVE')
    def test_explicit_id_lookup_includes_history(self):
        AvailabilitySlot.objects.filter(pk=self.slot1.pk).update(starts_at=timezone.now()-timedelta(days=2),ends_at=timezone.now()-timedelta(days=1))
        self.assertEqual(list_coordination_slots(actor=self.front)['rows'],[])
        self.assertEqual(list_coordination_slots(actor=self.front,slot_id=self.slot1.pk)['rows'][0]['id'],self.slot1.pk)
    def test_readonly_instance_allows_get_not_write(self):
        self.book()
        with override_settings(ADC_READ_ONLY=True):
            self.assertEqual(self.read()['assessment'].code,'COORDINATE')
            c=self.client_front();r=c.get(reverse('front_coordination_detail',args=[self.slot1.pk]));self.assertEqual(r.status_code,200)
            self.assertNotContains(r,'进入原改期流程')
            self.assertEqual(c.post(reverse('front_coordination_detail',args=[self.slot1.pk]),{}).status_code,403)
    def test_http_list_and_detail_render_real_templates(self):
        self.book();c=self.client_front();self.assertContains(c.get(reverse('front_coordination_list')),'按出诊协调预约')
        r=c.get(reverse('front_coordination_detail',args=[self.slot1.pk]));self.assertContains(r,'重新核对当前状态')
        self.assertIn('no-store',r.headers['Cache-Control'])
    def test_invalid_filter_does_not_display_all_slots(self):
        r=self.client_front().get(reverse('front_coordination_list'),{'slot_id':'not-an-id'})
        self.assertContains(r,'请更正查询条件');self.assertEqual(r.context['rows'],[])
    def test_foreign_slot_http_denied(self):
        self.assertEqual(self.client_front().get(reverse('front_coordination_detail',args=[self.slot2.pk])).status_code,403)
    def test_query_post_not_allowed_even_with_workspace_token(self):
        self.assertEqual(self.client_front().post(reverse('front_coordination_detail',args=[self.slot1.pk]),{}).status_code,405)
    def test_temporary_read_failure_does_not_mean_business_failure(self):
        c=self.client_front()
        with patch('scheduling.front_coordination_views.read_coordination_slot',side_effect=DatabaseError('synthetic read outage')):
            r=c.get(reverse('front_coordination_detail',args=[self.slot1.pk]))
        self.assertEqual(r.status_code,503);self.assertContains(r,'不代表刚才的改期或取消失败',status_code=503)
    def test_original_visit_has_safe_return_link(self):
        v=self.book();c=self.client_front();r=c.get(reverse('visit_detail',args=[v.pk]),{'coord_slot':self.slot1.pk})
        self.assertContains(r,reverse('front_coordination_detail',args=[self.slot1.pk]))
    def test_foreign_origin_does_not_gain_navigation_or_permission(self):
        v=self.book()
        self.assertIsNone(visit_return_slot(self.front,str(self.slot2.pk),v))
        self.assertIsNone(visit_return_slot(self.front,'https://outside.example',v))
    def test_cancel_success_retains_origin_and_query_reflects_actual_state(self):
        v=self.book();c=self.client_front();url=reverse('visit_detail',args=[v.pk])+'?coord_slot='+str(self.slot1.pk)
        r=c.post(url,{'expected_version':v.lock_version,'action':'cancel','party':'PATIENT','reason':'合成测试患者确认'})
        self.assertEqual(r.status_code,302);self.assertIn('coord_slot='+str(self.slot1.pk),r.url)
        self.assertEqual(self.read()['assessment'].code,'RECHECK')
    def test_reschedule_uses_existing_command_and_returns_to_original_source(self):
        v=self.book();new_slot=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d1,
            starts_at=self.t+timedelta(days=2),ends_at=self.t+timedelta(days=2,hours=4))
        c=self.client_front();url=reverse('visit_reschedule',args=[v.pk])+'?coord_slot='+str(self.slot1.pk)
        r=c.post(url,{'expected_version':0,'slot':new_slot.pk,'start':new_slot.starts_at.isoformat(),
            'end':(new_slot.starts_at+timedelta(minutes=30)).isoformat(),'reason':'合成患者同意改期'})
        self.assertEqual(r.status_code,200)
        self.assertFalse(Visit.objects.filter(replaces_visit=v).exists())
        r=c.post(url,{'action':'confirm','proposal_token':r.context['preview']['proposal_token'],'confirmed':'on'})
        self.assertEqual(r.status_code,302);new=Visit.objects.get(replaces_visit=v)
        self.assertEqual(visit_return_slot(self.front,str(self.slot1.pk),new),self.slot1.pk)
        self.assertEqual(self.read()['assessment'].code,'RECHECK')
        self.assertContains(c.get(r.url),'返回出诊 #'+str(self.slot1.pk))
    def test_original_rescheduled_detail_links_to_authorized_successor(self):
        v=self.book();new_slot=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d1,
            starts_at=self.t+timedelta(days=2),ends_at=self.t+timedelta(days=2,hours=4))
        new=reschedule(actor=self.front,visit_id=v.pk,expected_version=0,new_slot_id=new_slot.pk,
            start=new_slot.starts_at,end=new_slot.starts_at+timedelta(minutes=30),reason='合成患者同意')
        v.refresh_from_db();chain=visit_chain_context(self.front,v,self.slot1.pk)
        self.assertEqual(chain['coordination_successor']['visit_no'],new.visit_no)
        self.assertEqual(visit_chain_context(self.front,new,self.slot1.pk)['coordination_predecessor']['visit_no'],v.visit_no)
        self.assertContains(self.client_front().get(reverse('visit_detail',args=[v.pk])),new.visit_no)
    def test_manager_receives_no_direct_chain_identity(self):
        v=self.book();self.assertEqual(visit_chain_context(self.manager,v),
            {'coordination_predecessor':None,'coordination_successor':None})
    def test_offer_accept_returns_to_origin_with_exact_new_visit(self):
        o=self.make_offer();c=self.client_front();url=reverse('wait_offer',args=[o.pk])+'?coord_slot='+str(self.slot1.pk)
        r=c.post(url,{'action':'accept','confirmed':'on'});self.assertEqual(r.status_code,302)
        self.assertEqual(r.url,reverse('front_coordination_detail',args=[self.slot1.pk]))
        data=self.read();self.assertEqual(data['offers'][0]['visit_id'],data['visits'][0]['id'])
    def test_unrelated_offer_origin_is_ignored(self):
        o=self.make_offer();self.assertIsNone(offer_return_slot(self.front,str(self.slot2.pk),o))
    def test_http_manager_still_sees_counts_not_front_detail(self):
        self.book();c=WorkspaceClient();c.force_login(self.manager)
        self.assertEqual(c.get(reverse('front_coordination_detail',args=[self.slot1.pk])).status_code,403)
        r=c.get(reverse('availability_detail',args=[self.slot1.pk]));self.assertEqual(r.status_code,403)
        r=c.get(reverse('visits'));self.assertEqual(r.status_code,200);self.assertNotContains(r,self.p1.patient_no)

class CoordinationReadLockTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql');self.make_fixture()
        for user in (self.front,self.front2):
            user._adc_workspace=WorkspaceContext.objects.create(user=user,role='FRONT_DESK',clinic=self.a,revision=1)
    def test_projection_holds_shared_slot_lock_only_until_read_finishes(self):
        from scheduling.coordination import lock_slots
        locked,release,writer_ready=Event(),Event(),Event();pid=[]
        def actor(uid,cid):
            u=UserAccount.objects.get(pk=uid);u._adc_workspace=WorkspaceContext.objects.get(pk=cid);return u
        def synchronized_slots(ids):
            slots=lock_slots(ids);locked.set()
            if not release.wait(10):raise AssertionError('read synchronization timeout')
            return slots
        def reader():
            close_old_connections()
            try:return read_coordination_slot(actor=actor(self.front.pk,self.front._adc_workspace.pk),slot_id=self.slot1.pk)
            finally:close_old_connections()
        def writer():
            close_old_connections()
            try:
                u=actor(self.front2.pk,self.front2._adc_workspace.pk)
                with connection.cursor() as c:c.execute('SELECT pg_backend_pid()');pid.append(c.fetchone()[0])
                writer_ready.set()
                return create_appointment(actor=u,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,
                    start=self.t,end=self.t+timedelta(minutes=30)).pk
            finally:close_old_connections()
        with patch('scheduling.front_coordination_selectors.lock_slots',side_effect=synchronized_slots):
            with ThreadPoolExecutor(max_workers=2) as pool:
                a=pool.submit(reader)
                try:
                    self.assertTrue(locked.wait(5));b=pool.submit(writer);self.assertTrue(writer_ready.wait(5))
                    waiting=False;deadline=monotonic()+3
                    while monotonic()<deadline:
                        with connection.cursor() as c:
                            c.execute('SELECT wait_event_type FROM pg_stat_activity WHERE pid=%s',[pid[0]])
                            row=c.fetchone()
                        if row and row[0]=='Lock':waiting=True;break
                        sleep(.03)
                    self.assertTrue(waiting,'writer should be blocked on the shared slot lock')
                finally:release.set()
                before=a.result(timeout=10);b.result(timeout=10)
        self.assertEqual(before['assessment'].code,'RECHECK')
        after=read_coordination_slot(actor=self.front,slot_id=self.slot1.pk)
        self.assertEqual(after['assessment'].code,'COORDINATE')
