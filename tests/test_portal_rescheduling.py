"""Patient decisions, shared resources, retained offers and actual PostgreSQL races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import connection,close_old_connections
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent,Invoice
from coordination.models import WaitRequest,WaitOffer
from coordination.services import join_waitlist,create_plan,publish_plan,answer_offer,withdraw
from operations.cancellation_selectors import followup_visits
from portal.models import PatientAccess,BookingReceipt
from portal import rescheduling as service
from portal.services import cancel_booking
from scheduling.models import Visit,VisitRequest
from scheduling.resource_models import ResourcePlan,ResourceClaim,ResourceBlock,BookingService
from scheduling.services import reschedule as front_reschedule
from tests.test_reception_resources import ResourceFixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext

class PatientRescheduleTests(ResourceFixture,TransactionTestCase):
    def setUp(self):
        self.resources()
        self.u=UserAccount.objects.create_user(username='self_reschedule',password='synthetic-reschedule')
        self.u2=UserAccount.objects.create_user(username='self_reschedule_2',password='synthetic-reschedule')
        self.access=PatientAccess.objects.create(user=self.u,patient=self.p1)
        PatientAccess.objects.create(user=self.u2,patient=self.p2)
        for u in (self.u,self.u2):u._adc_workspace=WorkspaceContext.objects.create(user=u,role='PATIENT')
        self.v=self.booking()
    def prepare(self,**kw):
        data=dict(actor=self.u,visit_id=self.v.pk,expected_version=0,slot_id=self.slot2.pk,
            start=self.t+timedelta(hours=1),reason='课程患者希望调整时间');data.update(kw)
        return service.prepare(**data)
    def confirm(self,p,**kw):
        data=dict(actor=self.u,visit_id=self.v.pk,proposal_token=p['proposal_token'],confirmed=True);data.update(kw)
        return service.confirm(**data)
    def offer(self,service=None):
        e=join_waitlist(actor=self.u,clinic_id=self.a.pk,earliest=self.t+timedelta(hours=1),
            latest=self.t+timedelta(hours=2),dentist_id=self.d2.pk,service_id=(service or self.service).pk)
        plan=create_plan(actor=self.front,clinic_id=self.a.pk);publish_plan(actor=self.front,plan_id=plan.pk)
        return WaitOffer.objects.select_related('request').get(request=e)
    def assert_original(self):
        self.v.refresh_from_db();self.assertEqual(self.v.status,'SCHEDULED');self.assertEqual(self.v.lock_version,0)
        self.assertTrue(ResourceClaim.objects.filter(plan__visit=self.v,active=True).exists())
        self.assertFalse(Visit.objects.filter(replaces_visit=self.v).exists())
        self.assertFalse(BookingReceipt.objects.exists())
    def race(self,*functions):
        barrier=Barrier(len(functions))
        def run(f):
            close_old_connections()
            try:
                with connection.cursor() as c:c.execute("SET lock_timeout='8s'")
                barrier.wait(timeout=8)
                try:return ('ok',f())
                except RuleError:return ('conflict',None)
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures=[pool.submit(run,f) for f in functions]
            return [f.result(timeout=30) for f in futures]
    def actor(self,u):
        actor=UserAccount.objects.get(pk=u.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=u._adc_workspace.pk)
        return actor
    def test_preview_has_no_business_effect(self):
        before=(Visit.objects.count(),ResourceClaim.objects.count(),AuditEvent.objects.count(),Invoice.objects.count())
        self.prepare();self.assertEqual(before,(Visit.objects.count(),ResourceClaim.objects.count(),AuditEvent.objects.count(),Invoice.objects.count()))
    def test_confirmation_retains_chain_and_requests(self):
        VisitRequest.objects.create(visit=self.v,description='课程诊疗意向')
        p=self.prepare();new,repeated=self.confirm(p)
        self.assertFalse(repeated);self.v.refresh_from_db();self.assertEqual(self.v.status,'RESCHEDULED')
        self.assertEqual(new.replaces_visit_id,self.v.pk);self.assertEqual(new.patient_id,self.p1.pk)
        self.assertEqual(list(new.requests.values_list('description',flat=True)),['课程诊疗意向'])
        self.assertFalse(ResourceClaim.objects.filter(plan__visit=self.v,active=True).exists())
        self.assertTrue(ResourceClaim.objects.filter(plan__visit=new,active=True).exists())
        self.assertTrue(ResourcePlan.objects.filter(visit=self.v).exists());self.assertFalse(Invoice.objects.exists())
    def test_exact_confirmation_replay_one_effect(self):
        p=self.prepare();a,_=self.confirm(p);b,repeated=self.confirm(p)
        self.assertTrue(repeated);self.assertEqual(a.pk,b.pk);self.assertEqual(BookingReceipt.objects.count(),1)
        self.assertEqual(AuditEvent.objects.filter(event_type='VISIT_RESCHEDULED').count(),1)
    def test_replay_does_not_revive_cancelled_successor(self):
        p=self.prepare();new,_=self.confirm(p);cancel_booking(actor=self.u,visit_id=new.pk,expected_version=0,reason='课程患者取消')
        result,repeated=self.confirm(p);self.assertTrue(repeated);self.assertEqual(result.status,'CANCELLED')
    def test_wrong_patient_rejected(self):
        with self.assertRaises(Visit.DoesNotExist):self.prepare(actor=self.u2)
        with self.assertRaises(RuleError):self.confirm(self.prepare(),actor=self.u2)
        self.assert_original()
    def test_foreign_clinic_destination_rejected(self):
        from scheduling.models import AvailabilitySlot
        other=AvailabilitySlot.objects.create(clinic=self.b,dentist=self.d1,starts_at=self.t+timedelta(days=2),ends_at=self.t+timedelta(days=2,hours=2))
        with self.assertRaises(AvailabilitySlot.DoesNotExist):self.prepare(slot_id=other.pk,start=other.starts_at)
        self.assert_original()
    def test_started_source_requires_front_desk(self):
        with patch('portal.rescheduling.timezone.now',return_value=self.t):
            with self.assertRaises(RuleError):self.prepare()
        self.assert_original()
    def test_non_scheduled_source_rejected(self):
        cancel_booking(actor=self.u,visit_id=self.v.pk,expected_version=0,reason='本人取消')
        with self.assertRaises(RuleError):self.prepare(expected_version=1)
    def test_unchanged_arrangement_rejected(self):
        with self.assertRaises(RuleError):self.prepare(slot_id=self.slot1.pk,start=self.t)
        self.assert_original()
    def test_conflict_after_preview_rolls_back_original_and_history(self):
        p=self.prepare();self.booking(patient=self.p2,slot=self.slot2,start=self.t+timedelta(hours=1))
        before=AuditEvent.objects.count()
        with self.assertRaises(RuleError):self.confirm(p)
        self.assertEqual(AuditEvent.objects.count(),before);self.assert_original()
    def test_own_physical_occupation_not_hidden_from_candidates(self):
        from scheduling.resource_models import ResourceBinding
        ResourceBinding.objects.filter(asset=self.chairs[1]).update(is_active=False)
        result=service.options(actor=self.u,visit_id=self.v.pk,day=self.t.date(),dentist_id=self.d1.pk)
        self.assertTrue(any(r['start']==self.t+timedelta(minutes=15) for r in result['rows']))
        new,_=self.confirm(self.prepare(slot_id=self.slot1.pk,start=self.t+timedelta(minutes=15)))
        self.assertEqual(new.scheduled_start,self.t+timedelta(minutes=15))
    def test_disabled_access_after_preview(self):
        p=self.prepare();PatientAccess.objects.filter(pk=self.access.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.confirm(p)
        self.assert_original()
    def test_disabled_account_after_preview(self):
        p=self.prepare();UserAccount.objects.filter(pk=self.u.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.confirm(p)
        self.assert_original()
    def test_workspace_switch_invalidates_confirmation(self):
        p=self.prepare();WorkspaceContext.objects.filter(pk=self.u._adc_workspace.pk).update(revision=1)
        with self.assertRaises(PermissionDenied):self.confirm(p)
        self.assert_original()
    def test_signature_tamper_and_expiry(self):
        p=self.prepare()
        with self.assertRaises(RuleError):self.confirm(p,proposal_token=p['proposal_token']+'a')
        import time
        with patch('django.core.signing.time.time',return_value=time.time()+1000):
            with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
    def test_explicit_confirmation_required(self):
        with self.assertRaises(RuleError):self.confirm(self.prepare(),confirmed=False)
        self.assert_original()
    def test_paused_destination_and_pause_resume_stale_preview(self):
        p=self.prepare();self.slot2.booking_paused=True;self.slot2.intake_revision+=1;self.slot2.save()
        with self.assertRaises(RuleError):self.confirm(p)
        self.slot2.booking_paused=False;self.slot2.intake_revision+=1;self.slot2.save()
        with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
    def test_service_change_after_preview_requires_repreview(self):
        p=self.prepare();self.service.duration_minutes=45;self.service.save()
        with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
        fresh=self.prepare();self.assertTrue(fresh['duration_changed']);new,_=self.confirm(fresh)
        self.assertEqual(new.scheduled_end-new.scheduled_start,timedelta(minutes=45))
    def test_maintenance_after_preview_preserves_original(self):
        p=self.prepare()
        for asset in self.chairs:self.maintain(asset)
        with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
    def test_closure_after_preview_preserves_original(self):
        p=self.prepare();ResourceBlock.objects.create(clinic=self.a,department=self.department,
            starts_at=self.t+timedelta(hours=1),ends_at=self.t+timedelta(hours=2),reason='课程临时关闭',recorded_by=self.manager)
        with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
    def test_shared_device_and_other_patient_hold_not_stolen(self):
        o=self.offer()
        with self.assertRaises(RuleError):self.prepare(start=o.starts_at)
        self.assert_original()
    def test_own_offer_replaces_in_one_transaction(self):
        o=self.offer();p=self.prepare(offer_id=o.pk);new,_=self.confirm(p);o.refresh_from_db();o.request.refresh_from_db()
        self.assertEqual(o.state,'ACCEPTED');self.assertEqual(o.visit_id,new.pk);self.assertEqual(o.request.state,'BOOKED')
        self.assertEqual(new.replaces_visit_id,self.v.pk);self.assertEqual(Visit.objects.count(),2)
        plan=ResourcePlan.objects.get(offer=o,is_current=True);self.assertEqual(plan.visit_id,new.pk)
        self.assertFalse(plan.claims.filter(active=True,kind='HOLD').exists());self.assertTrue(plan.claims.filter(active=True,kind='FIRM').exists())
        self.assertEqual(answer_offer(actor=self.u,offer_id=o.pk,accept=True).visit_id,new.pk)
        self.assertEqual(self.confirm(p)[0].pk,new.pk)
    def test_retained_offer_honors_pause_and_original_duration(self):
        o=self.offer();p=self.prepare(offer_id=o.pk)
        self.slot2.booking_paused=True;self.slot2.intake_revision+=1;self.slot2.save()
        self.service.duration_minutes=60;self.service.save()
        new,_=self.confirm(p);self.assertEqual(new.scheduled_end-new.scheduled_start,timedelta(minutes=30))
    def test_expired_offer_preserves_original(self):
        o=self.offer();p=self.prepare(offer_id=o.pk);WaitOffer.objects.filter(pk=o.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
    def test_withdrawn_offer_preserves_original(self):
        o=self.offer();p=self.prepare(offer_id=o.pk);withdraw(actor=self.u,entry_id=o.request_id)
        with self.assertRaises(RuleError):self.confirm(p)
        self.assert_original()
    def test_offer_accepted_as_booking_first_not_silently_relinked(self):
        o=self.offer();p=self.prepare(offer_id=o.pk);answer_offer(actor=self.u,offer_id=o.pk,accept=True)
        with self.assertRaises(RuleError):self.confirm(p)
        self.v.refresh_from_db();self.assertEqual(self.v.status,'SCHEDULED');self.assertFalse(Visit.objects.filter(replaces_visit=self.v).exists())
    def test_other_patient_offer_not_available(self):
        o=self.offer();v2=self.booking(patient=self.p2,slot=self.slot1,start=self.t+timedelta(hours=3))
        with self.assertRaises(WaitOffer.DoesNotExist):service.prepare(actor=self.u2,visit_id=v2.pk,
            expected_version=0,slot_id=o.slot_id,start=o.starts_at,reason='不能借用他人邀约',offer_id=o.pk)
    def test_offer_for_other_service_rejected(self):
        other=BookingService.objects.create(department=self.department,code='OTHER',name='不同服务',duration_minutes=30)
        other.dentists.set([self.d2]);o=self.offer(service=other)
        with self.assertRaises(RuleError):self.prepare(offer_id=o.pk)
        self.assert_original()
    def test_accepted_origin_offer_history_retained(self):
        o=self.offer();booked=answer_offer(actor=self.u,offer_id=o.pk,accept=True).visit
        p=self.prepare(visit_id=booked.pk,slot_id=self.slot1.pk,start=self.t+timedelta(hours=3))
        self.confirm(p,visit_id=booked.pk);o.refresh_from_db();self.assertEqual(o.visit_id,booked.pk);self.assertEqual(o.state,'ACCEPTED')
    def test_reschedule_not_cancel_followup_but_later_cancellation_is(self):
        new,_=self.confirm(self.prepare());self.assertFalse(followup_visits(self.front).filter(pk=self.v.pk).exists())
        cancel_booking(actor=self.u,visit_id=new.pk,expected_version=0,reason='本人之后取消')
        self.assertTrue(followup_visits(self.front).filter(pk=new.pk).exists())
        self.v.refresh_from_db();self.assertEqual(self.v.cancellation_reason,'')
    def test_http_search_preview_and_confirmation(self):
        c=WorkspaceClient();c.force_login(self.u);url=reverse('portal_reschedule',args=[self.v.pk])
        before=(Visit.objects.count(),ResourceClaim.objects.count());self.assertEqual(c.get(url).status_code,200)
        self.assertEqual(before,(Visit.objects.count(),ResourceClaim.objects.count()))
        p=c.post(url,dict(action='preview',expected_version=0,slot_id=self.slot2.pk,
            start=(self.t+timedelta(hours=1)).isoformat(),reason='患者网页改期'))
        self.assertContains(p,'核对后确认改期');self.assertEqual(Visit.objects.count(),1)
        r=c.post(url,dict(action='confirm',proposal_token=p.context['preview']['proposal_token'],confirmed='on'))
        self.assertEqual(r.status_code,302);self.assertEqual(Visit.objects.count(),2)
        self.assertContains(c.get(reverse('portal_visit',args=[self.v.pk])),'查看后继预约')
    def test_http_offer_selection_without_date_uses_retained_promise(self):
        o=self.offer();self.slot2.booking_paused=True;self.slot2.save()
        c=WorkspaceClient();c.force_login(self.u);r=c.get(reverse('portal_reschedule',args=[self.v.pk])+'?offer='+str(o.pk))
        self.assertContains(r,'将接受本人邀约');self.assertEqual(r.context['selection']['offer_id'],o.pk)
    def test_http_foreign_patient_and_active_roles(self):
        url=reverse('portal_reschedule',args=[self.v.pk]);c=WorkspaceClient();c.force_login(self.u2);self.assertEqual(c.get(url).status_code,404)
        for u in (self.front,self.manager,self.tech):
            c.force_login(u);self.assertEqual(c.get(url).status_code,403)
    def test_http_stale_confirmation_shows_saved_result_not_empty_form(self):
        c=WorkspaceClient();c.force_login(self.u);url=reverse('portal_reschedule',args=[self.v.pk])
        r=c.post(url,dict(action='confirm',proposal_token='bad',confirmed='on'))
        self.assertEqual(r.status_code,409);self.assertContains(r,'核对原预约与相关结果',status_code=409)
    def test_http_help_does_not_disclose_other_patient(self):
        c=WorkspaceClient();c.force_login(self.u2);r=c.get(reverse('portal_help')+'?visit='+str(self.v.pk))
        self.assertIsNone(r.context['help_visit']);self.assertNotContains(r,self.v.visit_no)
    def test_concurrent_repeat_returns_unique_successor(self):
        p=self.prepare()
        rows=self.race(*(lambda:self.confirm(p,actor=self.actor(self.u))[0].pk for _ in range(2)))
        self.assertEqual([r[0] for r in rows],['ok','ok']);self.assertEqual(rows[0][1],rows[1][1]);self.assertEqual(BookingReceipt.objects.count(),1)
    def test_two_patients_compete_for_one_doctor(self):
        v2=self.booking(patient=self.p2,slot=self.slot1,start=self.t+timedelta(hours=3))
        p=self.prepare();q=self.prepare(actor=self.u2,visit_id=v2.pk)
        rows=self.race(lambda:self.confirm(p,actor=self.actor(self.u))[0].pk,
            lambda:self.confirm(q,actor=self.actor(self.u2),visit_id=v2.pk)[0].pk)
        self.assertEqual(sum(r[0]=='ok' for r in rows),1);self.assertEqual(BookingReceipt.objects.count(),1)
        self.assertEqual(Visit.objects.filter(pk__in=[self.v.pk,v2.pk],status='SCHEDULED').count(),1)
    def test_frontdesk_and_patient_compete_for_original(self):
        p=self.prepare()
        def front():
            return front_reschedule(actor=self.actor(self.front),visit_id=self.v.pk,expected_version=0,
                new_slot_id=self.slot2.pk,start=self.t+timedelta(hours=2),end=self.t+timedelta(hours=2,minutes=30),
                reason='前台与患者竞争同一原约',service_id=self.service.pk).pk
        rows=self.race(lambda:self.confirm(p,actor=self.actor(self.u))[0].pk,front)
        self.assertEqual(sum(r[0]=='ok' for r in rows),1);self.assertEqual(Visit.objects.filter(replaces_visit=self.v).count(),1)
    def test_offer_acceptance_race_never_makes_third_booking(self):
        o=self.offer();p=self.prepare(offer_id=o.pk)
        rows=self.race(lambda:self.confirm(p,actor=self.actor(self.u))[0].pk,
            lambda:answer_offer(actor=self.actor(self.front),offer_id=o.pk,accept=True).visit_id)
        self.assertEqual(Visit.objects.count(),2);o.refresh_from_db()
        self.assertEqual(sum(r[0]=='ok' for r in rows)>=1,True)
        self.assertIn(o.visit_id,[r[1] for r in rows if r[0]=='ok'])
    def test_patient_queues_separate_current_from_retained_history(self):
        new,_=self.confirm(self.prepare());c=WorkspaceClient();c.force_login(self.u)
        r=c.get(reverse('portal_appointments'));self.assertEqual([v.pk for v in r.context['page']],[new.pk])
        h=c.get(reverse('portal_appointments')+'?queue=history');self.assertEqual([v.pk for v in h.context['page']],[self.v.pk])
    def test_linked_reception_waitlist_finishes_same_replacement(self):
        row=self.case(patient_no=self.p1.patient_no,dentist_id=self.d2.pk)
        row=self.step(row,'WAITLIST',earliest=(self.t+timedelta(hours=1)).isoformat(),latest=(self.t+timedelta(hours=2)).isoformat(),due_at=(timezone.now()+timedelta(hours=2)).isoformat(),note='保留原约，等待可接受的改期方案')
        p=create_plan(actor=self.front,clinic_id=self.a.pk);publish_plan(actor=self.front,plan_id=p.pk)
        o=WaitOffer.objects.get(request_id=row.wait_request_id);new,_=self.confirm(self.prepare(offer_id=o.pk))
        row.refresh_from_db();self.assertEqual(row.state,'BOOKED');self.assertEqual(row.visit_id,new.pk)
        self.assertTrue(row.communications.filter(kind='WAIT_ACCEPTED').exists())
    def test_prior_cancel_followup_retains_evidence_and_shows_later_successor(self):
        from operations.cancellation_services import prepare_followup,confirm_followup
        cancelled=self.booking(start=self.t+timedelta(hours=4));cancel_booking(actor=self.u,visit_id=cancelled.pk,expected_version=0,reason='原患者行程变化')
        replacement=self.booking(start=self.t+timedelta(hours=5))
        _,token=prepare_followup(actor=self.front,visit_id=cancelled.pk,data=dict(reason_code='SCHEDULE',state='REBOOKED',assigned_to=self.front.pk,due_on='',replacement_no=replacement.visit_no,note='已核对正式另约结果'))
        row,_=confirm_followup(actor=self.front,visit_id=cancelled.pk,proposal_token=token,confirmed=True)
        new,_=self.confirm(self.prepare(visit_id=replacement.pk,start=self.t+timedelta(hours=6)),visit_id=replacement.pk)
        row.refresh_from_db();self.assertEqual(row.replacement_visit_id,replacement.pk);self.assertEqual(row.history.count(),1)
        c=WorkspaceClient();c.force_login(self.front);r=c.get(reverse('cancellation_followup',args=[cancelled.pk]))
        self.assertContains(r,new.visit_no);self.assertContains(r,'原跟进关联的另约事实')
    def test_inactive_original_clinic_requires_assistance(self):
        self.a.is_active=False;self.a.save()
        with self.assertRaises(RuleError):self.prepare()
        self.assert_original()

from tests.fixtures import FixtureMixin
class LegacyPatientRescheduleTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.make_fixture();self.u=UserAccount.objects.create_user(username='legacy_self')
        PatientAccess.objects.create(user=self.u,patient=self.p1);self.u._adc_workspace=WorkspaceContext.objects.create(user=self.u,role='PATIENT')
        self.v=self.book()
    def prepare(self,start=None,slot=None):
        return service.prepare(actor=self.u,visit_id=self.v.pk,expected_version=0,slot_id=(slot or self.slot1).pk,
            start=start or self.t+timedelta(minutes=90),reason='保留原历史时长')
    def test_legacy_duration_preserved(self):
        p=self.prepare();new,_=service.confirm(actor=self.u,visit_id=self.v.pk,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(new.scheduled_end-new.scheduled_start,timedelta(hours=1));self.assertFalse(ResourcePlan.objects.exists())
    def test_legacy_grid_not_reinterpreted_as_new_resource_mode(self):
        with self.assertRaises(RuleError):self.prepare(start=self.t+timedelta(minutes=15))
    def test_legacy_fourteen_day_horizon(self):
        from scheduling.models import AvailabilitySlot
        s=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d1,starts_at=self.t+timedelta(days=15),ends_at=self.t+timedelta(days=15,hours=2))
        with self.assertRaises(RuleError):self.prepare(start=s.starts_at,slot=s)
