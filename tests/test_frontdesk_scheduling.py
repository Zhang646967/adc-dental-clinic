"""B1.3.1 PostgreSQL/HTTP/concurrency business acceptance."""
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import connection,transaction,IntegrityError,close_old_connections
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from care.models import AuditEvent,Invoice
from coordination.models import WaitRequest,WaitOffer,SchedulePlan,CoordinationTask
from coordination.services import create_plan,publish_plan,answer_offer
from coordination.task_services import inspect_task,prepare_task,confirm_task,list_tasks
from scheduling.calendar import calendar_context,free_intervals
from scheduling.models import AvailabilitySlot,Visit
from scheduling.resource_models import Department,TreatmentRoom,ResourceBlock,ResourceBinding,ResourceClaim,ResourcePlan
from scheduling.slot_creation import prepare_slot_creation,confirm_slot_creation
from scheduling.intake_services import inspect_intake,prepare_intake,confirm_intake
from scheduling.services import change_appointment
from tests.test_reception_resources import ResourceFixture
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext
from adc_core.rules import RuleError

class FrontSchedulingTests(ResourceFixture,TransactionTestCase):
    def setUp(self):self.resources()
    def calendar(self,**kw):
        return calendar_context(actor=self.front,day=self.t.date(),mode='day',**kw)
    def rows(self,**kw):return [r for d in self.calendar(**kw)['days'] for r in d['rows']]
    def slot_preview(self,**kw):
        d=dict(actor=self.front,clinic_id=self.a.pk,dentist_id=self.d1.pk,start=self.t+timedelta(days=2),end=self.t+timedelta(days=2,hours=8));d.update(kw)
        return prepare_slot_creation(**d)
    def commit_slot(self,p,actor=None):return confirm_slot_creation(actor=actor or self.front,proposal_token=p['proposal_token'],confirmed=True)
    def offer(self):
        from coordination.services import join_waitlist
        e=join_waitlist(actor=self.front,clinic_id=self.a.pk,patient_no=self.p1.patient_no,earliest=self.t,latest=self.t+timedelta(hours=2),service_id=self.service.pk)
        p=create_plan(actor=self.front,clinic_id=self.a.pk);publish_plan(actor=self.front,plan_id=p.pk)
        return WaitOffer.objects.get(request=e)
    def task(self,action,t=None,actor=None,**kw):
        actor=actor or self.front
        _,token=inspect_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None)
        reasons={'open':'PLAN_CHANGE','claim':'TAKE_RESPONSIBILITY','progress':'NEED_HELP','submit':'FACTS_RECHECKED','approve':'REVIEW_CONFIRMED'}
        p=prepare_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None,state_token=token,action=action,
            reason=reasons[action],purpose='REPLACE' if action=='open' else '',**kw)
        r=confirm_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None,proposal_token=p['proposal_token'],confirmed=True)
        return CoordinationTask.objects.get(pk=r.task_id)
    def pause(self):
        _,s=inspect_intake(actor=self.front,slot_id=self.slot1.pk)
        p=prepare_intake(actor=self.front,slot_id=self.slot1.pk,state_token=s,action='pause',reason='COORDINATION')
        confirm_intake(actor=self.front,slot_id=self.slot1.pk,proposal_token=p['proposal_token'],confirmed=True)
    def test_slot_preview_does_not_write(self):
        before=(AvailabilitySlot.objects.count(),AuditEvent.objects.count());self.slot_preview()
        self.assertEqual(before,(AvailabilitySlot.objects.count(),AuditEvent.objects.count()))
    def test_slot_confirmation_replay_one_effect(self):
        p=self.slot_preview();a,repeated=self.commit_slot(p);b,repeated=self.commit_slot(p)
        self.assertTrue(repeated);self.assertEqual(a.pk,b.pk);self.assertEqual(AuditEvent.objects.filter(event_type='SLOT_CREATED').count(),1)
    def test_slot_foreign_clinic_rejected(self):
        with self.assertRaises(RuleError):self.slot_preview(clinic_id=self.b.pk)
    def test_slot_cross_clinic_doctor_conflict(self):
        AvailabilitySlot.objects.create(clinic=self.b,dentist=self.d1,starts_at=self.t+timedelta(days=2),ends_at=self.t+timedelta(days=2,hours=1))
        with self.assertRaises(RuleError):self.slot_preview()
    def test_slot_revoked_grant_after_preview(self):
        p=self.slot_preview();RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.commit_slot(p)
    def test_slot_context_switch_invalidates_preview(self):
        p=self.slot_preview();WorkspaceContext.objects.filter(pk=self.front._adc_workspace.pk).update(revision=1)
        with self.assertRaises(PermissionDenied):self.commit_slot(p)
    def test_slot_late_conflict_no_partial_audit(self):
        p=self.slot_preview();self.commit_slot(self.slot_preview(actor=self.front2),actor=self.front2)
        with self.assertRaises(RuleError):self.commit_slot(p)
        self.assertEqual(AuditEvent.objects.filter(event_type='SLOT_CREATED').count(),1)
    def test_slot_http_two_steps_and_no_get_write(self):
        c=WorkspaceClient();c.force_login(self.front);url=reverse('slot_create');before=AvailabilitySlot.objects.count()
        self.assertEqual(c.get(url).status_code,200)
        p=c.post(url,dict(clinic=self.a.pk,dentist=self.d1.pk,start=timezone.localtime(self.t+timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),end=timezone.localtime(self.t+timedelta(days=2,hours=8)).strftime('%Y-%m-%dT%H:%M')))
        self.assertContains(p,'确认新增出诊安排');self.assertEqual(AvailabilitySlot.objects.count(),before)
        r=c.post(url,dict(proposal_token=p.context['preview']['proposal_token'],confirmed='on'))
        self.assertEqual(r.status_code,302);self.assertEqual(AvailabilitySlot.objects.count(),before+1)
    def test_all_seven_roles_calendar_boundary(self):
        accounts={'FRONT_DESK':self.front,'MANAGER':self.manager,'SYSADMIN':self.tech}
        for role in ('DENTIST','HQ','FINANCE','PATIENT'):
            u=UserAccount.objects.create_user(username='calendar_'+role,password='synthetic-pass',dentist=self.d1 if role=='DENTIST' else None)
            if role=='PATIENT':
                from portal.models import PatientAccess
                PatientAccess.objects.create(user=u,patient=self.p1)
            else:RoleAssignment.objects.create(user=u,role=role,scope_kind='SELF_DENTIST' if role=='DENTIST' else 'CHAIN')
            accounts[role]=u
        for role,u in accounts.items():
            c=WorkspaceClient();c.force_login(u)
            self.assertEqual(c.get(reverse('schedule_calendar')).status_code,200 if role=='FRONT_DESK' else 403,role)
    def test_manager_has_no_scheduling_writes(self):
        c=WorkspaceClient();c.force_login(self.manager)
        for url in [reverse('slot_create'),reverse('availability_list'),reverse('schedule_plans')]:self.assertEqual(c.get(url).status_code,403)
        with self.assertRaises(PermissionDenied):create_plan(actor=self.manager,clinic_id=self.a.pk)
    def test_assigned_front_grant_not_active_front_role(self):
        RoleAssignment.objects.create(user=self.front,role='MANAGER',scope_kind='CLINIC',clinic=self.a)
        self.front._adc_workspace=WorkspaceContext.objects.create(user=self.front,role='MANAGER',clinic=self.a)
        with self.assertRaises(PermissionDenied):self.calendar()
    def test_week_starts_monday(self):
        d=calendar_context(actor=self.front,day=self.t.date(),mode='week')
        self.assertEqual(d['first'].weekday(),0);self.assertEqual(len(d['days']),7)
    def test_day_query_no_business_effects(self):
        before=(Visit.objects.count(),ResourceClaim.objects.count(),Invoice.objects.count(),AuditEvent.objects.count())
        self.calendar(service=self.service)
        self.assertEqual(before,(Visit.objects.count(),ResourceClaim.objects.count(),Invoice.objects.count(),AuditEvent.objects.count()))
    def test_calendar_excludes_other_clinic(self):
        AvailabilitySlot.objects.filter(pk=self.slot2.pk).update(clinic=self.b)
        self.assertEqual([r['slot'].pk for r in self.rows()],[self.slot1.pk])
    def test_filter_dentist(self):self.assertEqual([r['slot'].dentist_id for r in self.rows(dentist_id=self.d1.pk)],[self.d1.pk])
    def test_booking_reduces_available_window(self):
        self.booking();r=self.rows()[0]
        self.assertEqual(r['windows'][0]['start'],self.t+timedelta(minutes=30));self.assertEqual(len(r['events']),1)
    def test_cancelled_booking_shown_without_blocking(self):
        v=self.booking();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',reason='课程取消',party='PATIENT')
        r=self.rows()[0];self.assertEqual(r['windows'][0]['start'],self.t);self.assertEqual(r['events'][0]['label'],'已取消')
    def test_expired_invitation_does_not_block(self):
        o=self.offer();WaitOffer.objects.filter(pk=o.pk).update(expires_at=timezone.now()-timedelta(seconds=1))
        r=next(r for r in self.rows() if r['slot'].pk==o.slot_id)
        self.assertEqual(r['windows'][0]['start'],self.t);self.assertEqual(r['events'][0]['label'],'邀约到期，待回收')
    def test_effective_invitation_blocks(self):
        o=self.offer();r=next(r for r in self.rows() if r['slot'].pk==o.slot_id)
        self.assertEqual(r['windows'][0]['start'],o.ends_at)
    def test_accepted_invitation_not_double_counted(self):
        o=self.offer();answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        r=next(r for r in self.rows() if r['slot'].pk==o.slot_id)
        self.assertEqual(len(r['events']),1);self.assertEqual(r['events'][0]['kind'],'visit')
    def test_paused_slot_has_no_service_suggestion(self):
        self.pause();r=next(r for r in self.rows(service=self.service) if r['slot'].pk==self.slot1.pk)
        self.assertTrue(r['windows']);self.assertFalse(r['candidates'])
    def test_service_duration_preserved(self):
        self.service.duration_minutes=45;self.service.save()
        for row in self.rows(service=self.service):
            for candidate in row['candidates']:self.assertEqual(candidate['end']-candidate['start'],timedelta(minutes=45))
    def test_department_closed_no_suggestions(self):
        self.department.hours.all().delete()
        self.assertFalse(any(r['candidates'] for r in self.rows(service=self.service)))
    def test_ineligible_doctor_no_suggestions(self):
        self.service.dentists.remove(self.d1)
        r=next(r for r in self.rows(service=self.service) if r['slot'].pk==self.slot1.pk)
        self.assertFalse(r['service_eligible']);self.assertFalse(r['candidates'])
    def test_maintenance_inventory_and_suggestions(self):
        for a in self.chairs:self.maintain(a)
        self.assertFalse(any(r['candidates'] for r in self.rows(service=self.service)))
        self.assertTrue(all(x['asset'].state=='MAINTENANCE' for x in self.calendar()['inventory']))
    def test_midday_unaligned_gap_suggestion_stays_inside_free_window(self):
        # Existing manual bookings need not be aligned to quarter-hour boundaries.
        from scheduling.models import Visit
        Visit.objects.create(visit_no='SYN-ODD',clinic=self.a,dentist=self.d1,patient=self.p1,availability_slot=self.slot1,
            scheduled_start=self.t,scheduled_end=self.t+timedelta(minutes=37))
        r=next(r for r in self.rows(service=self.service) if r['slot'].pk==self.slot1.pk)
        self.assertGreaterEqual(r['candidates'][0]['start'],self.t+timedelta(minutes=37))
    def test_query_budget_does_not_grow_per_slot(self):
        with CaptureQueriesContext(connection) as small:self.calendar(service=self.service)
        from registry.models import Dentist
        for i in range(3,27):
            d=Dentist.objects.create(employee_no='CAL'+str(i),name='课程医师',date_of_birth=self.d1.date_of_birth,home_address='合成',phone='000',email='cal@example.invalid')
            self.service.dentists.add(d)
            AvailabilitySlot.objects.create(clinic=self.a,dentist=d,starts_at=self.t,ends_at=self.t+timedelta(hours=8))
        with CaptureQueriesContext(connection) as large:self.calendar(service=self.service)
        self.assertLessEqual(len(large),len(small)+2)
    def test_calendar_real_template_and_invalid_filter(self):
        c=WorkspaceClient();c.force_login(self.front)
        self.assertContains(c.get(reverse('schedule_calendar'),{'day':self.t.date(),'mode':'week','service':self.service.pk}),'日周排班')
        self.assertEqual(c.get(reverse('schedule_calendar'),{'day':'bad'}).status_code,400)
    def test_no_contact_or_clinical_text_in_calendar(self):
        v=self.booking();v.chief_complaint='不应进入排班的病史';v.save()
        c=WorkspaceClient();c.force_login(self.front)
        r=c.get(reverse('schedule_calendar'),{'day':self.t.date(),'mode':'day'})
        self.assertNotContains(r,'不应进入排班的病史');self.assertNotContains(r,self.p1.name)
    def test_front_task_deadline_and_overdue(self):
        self.pause();deadline=timezone.now()+timedelta(minutes=10);t=self.task('open',due_at=deadline)
        self.assertEqual(t.created_by_id,self.front.pk);self.assertEqual(t.due_at,deadline)
        with patch('coordination.task_services.timezone.now',return_value=deadline+timedelta(minutes=1)):
            d,_=inspect_task(actor=self.front,slot_id=self.slot1.pk,task_id=t.pk)
            self.assertTrue(d['overdue'])
    def test_past_deadline_rejected(self):
        self.pause()
        with self.assertRaises(RuleError):self.task('open',due_at=timezone.now()-timedelta(seconds=1))
        self.assertFalse(CoordinationTask.objects.exists())
    def test_deadline_rechecked_on_confirmation(self):
        self.pause();_,s=inspect_task(actor=self.front,slot_id=self.slot1.pk)
        deadline=timezone.now()+timedelta(minutes=5)
        p=prepare_task(actor=self.front,slot_id=self.slot1.pk,task_id=None,state_token=s,action='open',reason='PLAN_CHANGE',purpose='REPLACE',due_at=deadline)
        with patch('coordination.task_services.timezone.now',return_value=deadline+timedelta(seconds=1)),self.assertRaises(RuleError):
            confirm_task(actor=self.front,slot_id=self.slot1.pk,task_id=None,proposal_token=p['proposal_token'],confirmed=True)
    def test_task_clear_review_preserves_original_schedule(self):
        self.pause();t=self.task('claim',self.task('open'))
        # Existing business reason vocabularies are used rather than free text.
        from coordination.task_rules import ACTION_REASONS
        for action,actor in [('submit',self.front),('approve',self.manager)]:
            _,state=inspect_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk)
            p=prepare_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk,state_token=state,action=action,reason=ACTION_REASONS[action][0])
            result=confirm_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk,proposal_token=p['proposal_token'],confirmed=True)
            t.refresh_from_db()
        self.assertEqual(t.state,'CLOSED');self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active);self.assertTrue(self.slot1.booking_paused)
    def test_old_schedule_draft_rejected_without_effects(self):
        o=self.offer();p=o.plan
        # Published replay stays readable; a separately retained old draft is obsolete.
        old=SchedulePlan.objects.create(clinic=self.a,created_by=self.manager,suggestions=p.suggestions,metadata={})
        with self.assertRaisesRegex(RuleError,'旧版本'):publish_plan(actor=self.front,plan_id=old.pk)
        self.assertEqual(WaitOffer.objects.count(),1)
    def test_database_rejects_foreign_binding(self):
        other=Department.objects.create(clinic=self.b,code='OTHER',name='乙科');room=TreatmentRoom.objects.create(department=other,code='B',name='乙诊室')
        with self.assertRaises(IntegrityError),transaction.atomic():ResourceBinding.objects.filter(asset=self.chairs[0]).update(room=room)
    def test_database_rejects_shared_chair(self):
        with self.assertRaises(IntegrityError),transaction.atomic():ResourceBinding.objects.filter(asset=self.chairs[0]).update(room=None,shared=True)
    def test_database_rejects_foreign_block(self):
        for target in [dict(department=self.department),dict(room=self.room),dict(asset=self.chairs[0])]:
            with self.assertRaises(IntegrityError),transaction.atomic():ResourceBlock.objects.create(clinic=self.b,starts_at=self.t,ends_at=self.t+timedelta(hours=1),reason='跨店误关联',recorded_by=self.manager,**target)
    def test_database_rejects_same_clinic_wrong_department_plan(self):
        v=self.booking();other=Department.objects.create(clinic=self.a,code='OTHER',name='其他科');room=TreatmentRoom.objects.create(department=other,code='OTHER',name='其他诊室')
        with self.assertRaises(IntegrityError),transaction.atomic():ResourcePlan.objects.create(visit=v,service=self.service,room=room,snapshot={},reason='错误科室',recorded_by=self.front,is_current=False)
    def test_database_rejects_partial_claim_interval(self):
        v=self.booking();p=v.resource_plans.get(is_current=True)
        with self.assertRaises(IntegrityError),transaction.atomic():ResourceClaim.objects.create(plan=p,asset=self.chairs[1],starts_at=self.t,ends_at=self.t+timedelta(minutes=15),kind='FIRM')
    def test_database_rejects_mismatched_dual_source(self):
        o=self.offer();v=self.booking(patient=self.p2,slot=self.slot2,start=self.t+timedelta(hours=2))
        with self.assertRaises(IntegrityError),transaction.atomic():ResourcePlan.objects.create(visit=v,offer=o,service=self.service,room=self.room,snapshot={},reason='错误来源',recorded_by=self.front,is_current=False)
    def test_resource_offer_transfer_uses_same_source_interval(self):
        o=self.offer();o=answer_offer(actor=self.front,offer_id=o.pk,accept=True)
        p=o.resource_plans.get(is_current=True);self.assertEqual(p.visit_id,o.visit_id)
        for claim in p.claims.all():self.assertEqual((claim.starts_at,claim.ends_at,claim.kind),(o.starts_at,o.ends_at,'FIRM'))
    def test_database_calendar_indexes_present(self):
        with connection.cursor() as cur:
            cur.execute("SELECT indexname FROM pg_indexes WHERE indexname IN ('slot_clinic_start_idx','offer_slot_state_exp_idx')")
            self.assertEqual(len(cur.fetchall()),2)
    def test_parallel_slot_confirmation_returns_one_result(self):
        p=self.slot_preview();barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.front.pk);actor._adc_workspace=WorkspaceContext.objects.get(pk=self.front._adc_workspace.pk)
                barrier.wait(10);return self.commit_slot(p,actor=actor)[0].pk
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run) for _ in range(2)];ids=[j.result(20) for j in jobs]
        self.assertEqual(ids[0],ids[1]);self.assertEqual(AuditEvent.objects.filter(event_type='SLOT_CREATED').count(),1)
