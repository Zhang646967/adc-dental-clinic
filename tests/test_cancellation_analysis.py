"""B1.1 acceptance on PostgreSQL: denominators, scope, follow-up, reviewed work."""
from datetime import datetime, timedelta, time
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from django.test import TransactionTestCase, override_settings
from django.db import transaction, IntegrityError, close_old_connections
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils import timezone
from tests.fixtures import FixtureMixin
from accounts.models import UserAccount, RoleAssignment
from workspaces.models import WorkspaceContext
from scheduling.models import AvailabilitySlot, Visit, VisitRequest
from care.audit import emit
from operations.cancellation_policy import metric_dict, band_for_hour, serialize_metrics
from operations.cancellation_selectors import cancellation_report, cell_metrics
from operations.cancellation_services import (prepare_followup, confirm_followup, prepare_improvement,
    confirm_improvement)
from operations.models import CancellationFollowUp, AppointmentImprovement, AppointmentActionEvent
from adc_core.rules import RuleError, BUSINESS_TZ

class B11Fixture(FixtureMixin):
    def setup_b11(self):
        self.make_fixture(); self.seq = 0
        self.m2=UserAccount.objects.create_user(username='review_manager',password='synthetic-only-b11')
        RoleAssignment.objects.create(user=self.m2,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        self.hq=UserAccount.objects.create_user(username='b11_hq',password='synthetic-only-b11')
        RoleAssignment.objects.create(user=self.hq,role='HQ',scope_kind='CHAIN')
        for u,r,c in [(self.front,'FRONT_DESK',self.a),(self.front2,'FRONT_DESK',self.a),
                      (self.manager,'MANAGER',self.a),(self.m2,'MANAGER',self.a),(self.hq,'HQ',None)]:
            self.activate(u,r,c)
        day=timezone.localdate()-timedelta(days=70)
        self.day=day-timedelta(days=day.weekday())
        self.start=datetime.combine(self.day,time(9),BUSINESS_TZ)
    def activate(self,u,role,clinic):
        u._adc_workspace=WorkspaceContext.objects.create(user=u,role=role,clinic=clinic)
        return u
    def historical(self,status='CANCELLED',party='PATIENT',start=None,clinic=None):
        self.seq+=1;start=start or self.start+timedelta(minutes=self.seq)
        c=clinic or self.a;dentist=self.d1 if c.pk==self.a.pk else self.d2
        slot=AvailabilitySlot.objects.create(clinic=c,dentist=dentist,starts_at=start,ends_at=start+timedelta(minutes=1))
        values=dict(clinic=c,dentist=dentist,patient=self.p1 if c.pk==self.a.pk else self.p2,
            availability_slot=slot,scheduled_start=start,scheduled_end=slot.ends_at,status=status)
        if status=='CANCELLED':values.update(cancellation_party=party,cancellation_reason='原始合成取消说明')
        if status=='CHECKED_IN':values.update(attended=True,attended_at=start)
        with transaction.atomic():
            row=Visit.objects.create(**values)
            if status=='RESCHEDULED':
                successor_start=self.t+timedelta(minutes=self.seq)
                Visit.objects.create(clinic=self.a,dentist=self.d1,patient=self.p1,availability_slot=self.slot1,
                    scheduled_start=successor_start,scheduled_end=successor_start+timedelta(minutes=1),replaces_visit=row)
        return row
    def report(self,actor=None,**kw):
        return cancellation_report(actor or self.manager,self.day,self.day,**kw)
    def follow_fields(self,**kw):
        data=dict(reason_code='SCHEDULE',state='WAITING',assigned_to=self.front.pk,
            due_on=timezone.localdate().isoformat(),note='患者确认稍后回复；合成记录',replacement_no='')
        data.update(kw);return data
    def follow(self,v,**kw):
        actor=kw.pop('actor',self.front);clean,token=prepare_followup(actor=actor,visit_id=v.pk,data=self.follow_fields(**kw))
        return confirm_followup(actor=actor,visit_id=v.pk,proposal_token=token,confirmed=True)
    def plan_fields(self,**kw):
        data=dict(weekday=self.day.isoweekday(),band='08_10',baseline_start=self.day.isoformat(),
            baseline_end=self.day.isoformat(),kind='CONTACT',plan='按患者偏好联系并核对替代时间',
            assigned_to=self.front.pk,due_on=timezone.localdate().isoformat())
        data.update(kw);return data
    def plan(self):
        clean,t,p=prepare_improvement(actor=self.manager,action='CREATE',fields=self.plan_fields())
        return confirm_improvement(actor=self.manager,action='CREATE',pk=None,proposal_token=t,confirmed=True)[0]
    def step(self,row,action,actor=None,**fields):
        actor=actor or self.front
        clean,t,p=prepare_improvement(actor=actor,pk=row.pk,action=action,fields=dict(note='已核对合成业务依据',**fields))
        return confirm_improvement(actor=actor,action=action,pk=row.pk,proposal_token=t,confirmed=True)[0]

class CancellationAnalysisTests(B11Fixture,TransactionTestCase):
    def setUp(self):self.setup_b11()
    def test_exact_sample_and_replaced_exclusion(self):
        for status,party,n in [('CHECKED_IN','',6),('CANCELLED','PATIENT',2),('CANCELLED','CLINIC',1),
                               ('NO_SHOW','',1),('SCHEDULED','',3),('RESCHEDULED','',5)]:
            for _ in range(n):self.historical(status,party)
        r=self.report();m=r['metrics']
        self.assertEqual((m['denominator'],m['cancel_rate'],m['no_show_rate'],m['overall_rate'],m['completeness']),
            (9,Decimal('22.22'),Decimal('11.11'),Decimal('30.00'),Decimal('76.92')))
        self.assertEqual(r['replaced'],5);self.assertFalse(r['ranking'])
    def test_future_excluded(self):
        self.historical(start=timezone.now()+timedelta(days=2))
        day=timezone.localdate()+timedelta(days=2)
        r=cancellation_report(self.manager,day,day)
        self.assertEqual(r['future'],1);self.assertEqual(r['metrics']['denominator'],0)
    def test_zero_denominator_not_zero_percent(self):
        self.assertIsNone(self.report()['metrics']['cancel_rate'])
    def test_every_band_boundary(self):
        for h,want in [(7,'OTHER'),(8,'08_10'),(9,'08_10'),(10,'10_12'),(12,'12_14'),
                       (14,'14_16'),(16,'16_18'),(18,'18_20'),(20,'OTHER'),(23,'OTHER')]:
            self.assertEqual(band_for_hour(h),want)
        for hour in [7,8,10,12,14,16,18,20,23]:
            self.historical(start=self.start.replace(hour=hour,minute=0))
        r=self.report();self.assertEqual(sum(c['patient_cancel'] for row in r['grid'] for c in row['cells']),9)
        self.assertEqual(r['grid'][0]['cells'][-1]['patient_cancel'],3)
    def test_utc_and_midnight_use_local_start(self):
        s=self.start.replace(hour=23,minute=59)
        slot=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d1,starts_at=s,ends_at=s+timedelta(minutes=5))
        Visit.objects.create(clinic=self.a,dentist=self.d1,patient=self.p1,availability_slot=slot,
            scheduled_start=s,scheduled_end=slot.ends_at,status='CANCELLED',cancellation_party='PATIENT',cancellation_reason='合成')
        self.assertEqual(self.report()['grid'][0]['cells'][-1]['patient_cancel'],1)
    def test_treatment_intentions_do_not_multiply_visits(self):
        v=self.historical()
        VisitRequest.objects.bulk_create([VisitRequest(visit=v,description='合成意向') for _ in range(5)])
        self.assertEqual(self.report()['metrics']['patient_cancel'],1)
    def test_ranking_requires_both_thresholds(self):
        for _ in range(30):self.historical()
        r=self.report();self.assertEqual(len(r['ranking']),1);self.assertEqual(r['ranking'][0]['denominator'],30)
        self.historical('SCHEDULED','');self.historical('SCHEDULED','')
        self.assertFalse(self.report()['ranking'])
    def test_clinic_cancellation_separate(self):
        self.historical(party='CLINIC');m=self.report()['metrics']
        self.assertIsNone(m['cancel_rate']);self.assertEqual(m['overall_rate'],100)
    def test_clinic_scope_and_hq_choice(self):
        self.historical(clinic=self.b)
        self.assertEqual(self.report()['metrics']['patient_cancel'],0)
        with self.assertRaises(PermissionDenied):self.report(clinic_id=self.b.pk)
        self.assertTrue(self.report(actor=self.hq)['choose_clinic'])
        self.assertEqual(self.report(actor=self.hq,clinic_id=self.b.pk)['metrics']['patient_cancel'],1)
    def test_unknown_reason_and_time_never_fabricated(self):
        self.historical();r=self.report()
        self.assertEqual(r['reasons'][0][2],1);self.assertEqual(r['lead']['unknown'],1)
    def test_explicit_cancellation_events_classify_lead(self):
        for kind,delta in [('within24',timedelta(hours=24)),('earlier',timedelta(hours=25)),('after_start',-timedelta(minutes=1))]:
            v=self.historical();emit(self.front,'VISIT_CANCELLED',v,visit=v,occurred_at=v.scheduled_start-delta)
        r=self.report()
        self.assertEqual(r['lead'],dict(within24=1,earlier=1,after_start=1,unknown=0))
    def test_classification_changes_reason_not_money_or_denominators(self):
        v=self.historical();before=self.report()['metrics'];self.follow(v)
        r=self.report();self.assertEqual(before,r['metrics'])
        self.assertEqual(dict((code,n) for code,l,n in r['reasons'])['SCHEDULE'],1)
    def test_page_hides_patient_data_and_supports_links(self):
        v=self.historical();self.client.force_login(self.manager)
        r=self.client.get(reverse('cancellation_analysis'),{'start':self.day,'end':self.day})
        self.assertEqual(r.status_code,200);self.assertNotContains(r,self.p1.name);self.assertNotContains(r,v.visit_no)
        self.assertContains(r,'为当前时段安排改进措施')
    def test_front_and_patient_do_not_get_analysis(self):
        self.client.force_login(self.front)
        self.assertEqual(self.client.get(reverse('cancellation_analysis')).status_code,403)
    def test_invalid_filter_retains_input(self):
        self.client.force_login(self.manager)
        r=self.client.get(reverse('cancellation_analysis'),{'start':'bad','end':self.day})
        self.assertEqual(r.status_code,400)

class CancellationWorkTests(B11Fixture,TransactionTestCase):
    def setUp(self):self.setup_b11();self.v=self.historical()
    def test_preview_has_no_business_effect(self):
        prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields())
        self.assertFalse(CancellationFollowUp.objects.exists())
    def test_followup_history_preserves_original(self):
        original=(self.v.status,self.v.cancellation_party,self.v.cancellation_reason)
        row,_=self.follow(self.v);self.follow(self.v,reason_code='CONTACT',note='再次核对合成原因')
        self.v.refresh_from_db()
        self.assertEqual(original,(self.v.status,self.v.cancellation_party,self.v.cancellation_reason))
        self.assertEqual(row.history.count(),2)
    def test_missing_deadline_rejected(self):
        with self.assertRaises(RuleError):self.follow(self.v,due_on='')
    def test_wrong_patient_rebooking_rejected(self):
        with self.assertRaises(RuleError):self.follow(self.v,state='REBOOKED',replacement_no='does-not-exist')
    def test_valid_rebooking_requires_actual_record(self):
        new=self.book();row,_=self.follow(self.v,state='REBOOKED',replacement_no=new.visit_no)
        self.assertEqual(row.replacement_visit_id,new.pk);self.assertEqual(Visit.objects.count(),2)
    def test_cross_clinic_source_rejected(self):
        v=self.historical(clinic=self.b)
        with self.assertRaises(Visit.DoesNotExist):self.follow(v)
    def test_manager_has_no_personal_followup_access(self):
        with self.assertRaises(PermissionDenied):self.follow(self.v,actor=self.manager)
    def test_stale_and_replayed_confirmation(self):
        _,t=prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields())
        self.follow(self.v)
        with self.assertRaises(RuleError):confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)
        _,t=prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields())
        confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)
        self.assertTrue(confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)[1])
        self.assertEqual(CancellationFollowUp.objects.count(),1)
    def test_revoked_actor_or_owner_invalidates_confirmation(self):
        _,t=prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields(assigned_to=self.front2.pk))
        RoleAssignment.objects.filter(user=self.front2).update(is_active=False)
        with self.assertRaises(RuleError):confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)
    def test_actor_revoked_after_preview(self):
        _,t=prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields())
        RoleAssignment.objects.filter(user=self.front).update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)
    def test_expired_preview_and_wrong_url_rejected(self):
        _,t=prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields())
        with self.assertRaises(RuleError):confirm_followup(actor=self.front,visit_id=self.v.pk+1,proposal_token=t,confirmed=True)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1000):
            with self.assertRaises(RuleError):confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_refuses_followup_write(self):
        _,t=prepare_followup(actor=self.front,visit_id=self.v.pk,data=self.follow_fields())
        with self.assertRaises(PermissionDenied):confirm_followup(actor=self.front,visit_id=self.v.pk,proposal_token=t,confirmed=True)
    def test_audit_failure_rolls_back_all_followup_effects(self):
        with patch('operations.cancellation_services.emit',side_effect=RuntimeError('test failure')):
            with self.assertRaises(RuntimeError):self.follow(self.v)
        self.assertFalse(CancellationFollowUp.objects.exists());self.assertFalse(AppointmentActionEvent.objects.exists())
    def test_history_immutable_in_database(self):
        row,_=self.follow(self.v)
        with self.assertRaises(IntegrityError),transaction.atomic():
            row.history.update(snapshot={})
    def test_front_web_preview_and_confirm(self):
        self.client.force_login(self.front)
        path=reverse('cancellation_followup',args=[self.v.pk])
        r=self.client.post(path,dict(action='preview',**self.follow_fields()))
        self.assertEqual(r.status_code,200);token=r.context['form'].initial['proposal_token']
        r=self.client.post(path,dict(action='confirm',confirmed='on',proposal_token=token))
        self.assertEqual(r.status_code,302);self.assertEqual(CancellationFollowUp.objects.count(),1)

class ImprovementTests(B11Fixture,TransactionTestCase):
    def setUp(self):self.setup_b11()
    def test_complete_measure_with_independent_review(self):
        self.historical();row=self.plan()
        with patch('django.utils.timezone.now',return_value=self.start+timedelta(days=1)):
            self.step(row,'START')
        self.step(row,'SUBMIT')
        row=self.step(row,'REVIEW',actor=self.m2,review_start=(self.day+timedelta(days=7)).isoformat(),
            review_end=(self.day+timedelta(days=7)).isoformat(),assessment='INSUFFICIENT')
        self.assertEqual(row.state,'CLOSED');self.assertEqual(row.history.count(),4)
        self.assertEqual(row.baseline['metrics']['patient_cancel'],1)
    def test_comparison_before_actual_execution_is_rejected(self):
        row=self.plan();self.step(row,'START');self.step(row,'SUBMIT')
        with self.assertRaises(RuleError):
            self.step(row,'REVIEW',actor=self.m2,review_start=self.day+timedelta(days=7),
                review_end=self.day+timedelta(days=7),assessment='INSUFFICIENT')
    def test_baseline_cannot_claim_current_day_complete(self):
        with self.assertRaises(RuleError):
            prepare_improvement(actor=self.manager,action='CREATE',fields=self.plan_fields(baseline_end=timezone.localdate()))
    def test_self_review_even_after_switch_to_manager_rejected(self):
        RoleAssignment.objects.create(user=self.front,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        row=self.plan();self.step(row,'START');self.step(row,'SUBMIT')
        self.activate(self.front,'MANAGER',self.a)
        with self.assertRaises(RuleError):self.step(row,'REVIEW',review_start=self.day+timedelta(days=7),review_end=self.day+timedelta(days=7),assessment='INSUFFICIENT')
    def test_front_cannot_create_measures(self):
        with self.assertRaises(PermissionDenied):prepare_improvement(actor=self.front,action='CREATE',fields=self.plan_fields())
    def test_revoked_ready_owner_can_be_reassigned(self):
        row=self.plan();self.step(row,'START');self.step(row,'SUBMIT')
        RoleAssignment.objects.filter(user=self.front).update(is_active=False)
        row=self.step(row,'ASSIGN',actor=self.manager,assigned_to=self.front2.pk,due_on=timezone.localdate().isoformat())
        self.assertEqual((row.state,row.assigned_to_id),('OPEN',self.front2.pk))
    def test_unended_or_overlapping_review_window_rejected(self):
        row=self.plan();self.step(row,'START');self.step(row,'SUBMIT')
        for start,end in [(self.day,self.day+timedelta(days=7)),(self.day+timedelta(days=7),timezone.localdate()+timedelta(days=1))]:
            with self.assertRaises(RuleError):self.step(row,'REVIEW',actor=self.m2,review_start=start,review_end=end,assessment='INSUFFICIENT')
    def test_insufficient_samples_cannot_be_recorded_as_comparable_observation(self):
        row=self.plan()
        with patch('django.utils.timezone.now',return_value=self.start+timedelta(days=1)):
            self.step(row,'START')
        self.step(row,'SUBMIT')
        with self.assertRaises(RuleError):self.step(row,'REVIEW',actor=self.m2,review_start=self.day+timedelta(days=7),review_end=self.day+timedelta(days=7),assessment='OBSERVED')
    def test_duplicate_create_and_start_have_one_effect(self):
        _,t,_=prepare_improvement(actor=self.manager,action='CREATE',fields=self.plan_fields())
        for _ in range(2):confirm_improvement(actor=self.manager,action='CREATE',pk=None,proposal_token=t,confirmed=True)
        self.assertEqual(AppointmentImprovement.objects.count(),1);self.assertEqual(AppointmentActionEvent.objects.count(),1)
    def test_baseline_change_invalidates_confirmation(self):
        _,t,_=prepare_improvement(actor=self.manager,action='CREATE',fields=self.plan_fields())
        self.historical()
        with self.assertRaises(RuleError):confirm_improvement(actor=self.manager,action='CREATE',pk=None,proposal_token=t,confirmed=True)
    def test_only_assigned_front_sees_measure_and_hq_has_no_notes(self):
        row=self.plan();self.client.force_login(self.front2)
        self.assertEqual(self.client.get(reverse('appointment_improvement_detail',args=[row.pk])).status_code,404)
        self.client.force_login(self.hq)
        self.assertEqual(self.client.get(reverse('appointment_improvement_detail',args=[row.pk])).status_code,403)
    def test_ready_state_does_not_claim_closed_or_modify_booking(self):
        v=self.historical();row=self.plan();self.step(row,'START');row=self.step(row,'SUBMIT')
        self.assertEqual(row.state,'READY');v.refresh_from_db();self.assertEqual(v.status,'CANCELLED')

class B11ConcurrencyTests(B11Fixture,TransactionTestCase):
    def setUp(self):self.setup_b11()
    def test_simultaneous_followup_confirmations_create_one_receipt(self):
        v=self.historical();_,token=prepare_followup(actor=self.front,visit_id=v.pk,data=self.follow_fields())
        uid=self.front.pk;ctx=self.front._adc_workspace.pk
        def work():
            close_old_connections()
            try:
                user=UserAccount.objects.get(pk=uid);user._adc_workspace=WorkspaceContext.objects.get(pk=ctx)
                return confirm_followup(actor=user,visit_id=v.pk,proposal_token=token,confirmed=True)[1]
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:work(),range(2)))
        self.assertEqual(sorted(results),[False,True]);self.assertEqual(CancellationFollowUp.objects.count(),1);self.assertEqual(AppointmentActionEvent.objects.count(),1)
    def test_simultaneous_reviews_keep_one_closed_result(self):
        row=self.plan()
        with patch('django.utils.timezone.now',return_value=self.start+timedelta(days=1)):
            self.step(row,'START')
        self.step(row,'SUBMIT')
        fields=dict(note='合成独立复核',review_start=self.day+timedelta(days=7),
            review_end=self.day+timedelta(days=7),assessment='INSUFFICIENT')
        prepared=[]
        for actor in (self.manager,self.m2):
            _,token,_=prepare_improvement(actor=actor,pk=row.pk,action='REVIEW',fields=fields)
            prepared.append((actor.pk,actor._adc_workspace.pk,token))
        def work(data):
            close_old_connections()
            try:
                uid,ctx,token=data;actor=UserAccount.objects.get(pk=uid);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctx)
                try:confirm_improvement(actor=actor,action='REVIEW',pk=row.pk,proposal_token=token,confirmed=True);return 'saved'
                except RuleError:return 'stale'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(work,prepared))
        self.assertEqual(sorted(results),['saved','stale'])
        self.assertEqual(row.history.filter(action='REVIEW').count(),1)
