"""B1.2/B1.3 resource contention and telephone business facts, on PostgreSQL."""
from datetime import time,timedelta
from concurrent.futures import ThreadPoolExecutor
from django.test import TransactionTestCase
from django.db import transaction,IntegrityError,close_old_connections
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext
from accounts.models import RoleAssignment
from equipment.models import EquipmentAsset
from scheduling.models import AvailabilitySlot,Visit
from scheduling.resource_models import *
from scheduling.resources import choose_bundle,ResourceCalendar
from scheduling.services import create_appointment,change_appointment
from scheduling.booking import prepare_booking,confirm_booking
from scheduling.resource_config import prepare_config,confirm_config
from reception.services import prepare_case,confirm_case
from reception.models import ReceptionCase
from adc_core.rules import RuleError

class ResourceFixture(FixtureMixin):
    def resources(self):
        self.make_fixture()
        for u,r in [(self.front,'FRONT_DESK'),(self.front2,'FRONT_DESK'),(self.manager,'MANAGER')]:
            u._adc_workspace=WorkspaceContext.objects.create(user=u,role=r,clinic=self.a)
        self.t=timezone.localtime(self.t).replace(hour=9,minute=0,second=0,microsecond=0)
        for slot,clinic in [(self.slot1,self.a),(self.slot2,self.a)]:
            slot.clinic=clinic;slot.starts_at=self.t;slot.ends_at=self.t+timedelta(hours=8);slot.save()
        self.policy=ResourcePolicy.objects.create(clinic=self.a,state='ENABLED')
        self.department=Department.objects.create(clinic=self.a,code='GENERAL',name='综合科')
        DepartmentHours.objects.create(department=self.department,weekday=self.t.weekday(),opens_at=time(8),closes_at=time(18))
        self.room=TreatmentRoom.objects.create(department=self.department,code='ROOM1',name='课程双椅诊室')
        self.service=BookingService.objects.create(department=self.department,code='GENERAL',name='课程诊查',duration_minutes=30)
        self.service.dentists.set([self.d1,self.d2])
        self.chairs=[]
        for i in range(2):
            asset=self.asset('SYNTHETIC-CHAIR-'+str(i),'CHAIR')
            ResourceBinding.objects.create(asset=asset,room=self.room);self.chairs.append(asset)
    def asset(self,code,category):
        from equipment.services import prepare_registration,confirm_equipment
        preview=prepare_registration(actor=self.manager,asset_code=code,name='课程合成设备'+code,category=category,location='课程合成诊室',
            acquired_on=timezone.localdate(),acquisition_cost=None,next_service_due=None,note='明确标注的课程合成设备，成本未知')
        return confirm_equipment(actor=self.manager,proposal_token=preview['proposal_token'],confirmed=True)[0]
    def maintain(self,asset):
        from equipment.services import prepare_change,confirm_equipment
        p=prepare_change(actor=self.manager,asset_id=asset.pk,kind='MAINTENANCE',performed_on=timezone.localdate(),cost=None,next_service_due=None,note='课程设备送修')
        return confirm_equipment(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
    def booking(self,patient=None,slot=None,start=None,**kw):
        start=start or self.t
        return create_appointment(actor=kw.pop('actor',self.front),patient_no=(patient or self.p1).patient_no,
            slot_id=(slot or self.slot1).pk,start=start,end=start+timedelta(minutes=self.service.duration_minutes),service_id=self.service.pk,**kw)
    def reception_fields(self,**kw):
        d=dict(caller_name='课程来电者',relationship='本人',contact='合成联系电话',patient_hint='课程新患者',owner=self.front.pk,
            due_at=(timezone.now()+timedelta(hours=2)).isoformat(),state='CONTACT',note='第一次来电，尚待核实',patient_no='',service_id=self.service.pk,dentist_id=None,preferred_day=self.t.date().isoformat())
        d.update(kw);return d
    def case(self,**kw):
        p=prepare_case(actor=self.front,action='CREATE',fields=self.reception_fields(**kw))
        return confirm_case(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)[0]
    def step(self,row,action,**fields):
        row.refresh_from_db();p=prepare_case(actor=self.front,case_id=row.pk,expected_revision=row.revision,action=action,fields=fields)
        return confirm_case(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)[0]

class ResourceAdmissionTests(ResourceFixture,TransactionTestCase):
    def setUp(self):self.resources()
    def test_parallel_chairs_same_room(self):
        v=self.booking();w=self.booking(patient=self.p2,slot=self.slot2)
        self.assertEqual(ResourcePlan.objects.count(),2)
        self.assertEqual({p.room_id for p in ResourcePlan.objects.all()},{self.room.pk})
        self.assertEqual(ResourceClaim.objects.filter(active=True).values('asset_id').distinct().count(),2)
    def test_shared_device_contention(self):
        asset=self.asset('SHARED','IMAGING')
        ResourceBinding.objects.create(asset=asset,shared=True)
        ServiceRequirement.objects.create(service=self.service,category='IMAGING',quantity=1)
        self.booking()
        with self.assertRaises(RuleError):self.booking(patient=self.p2,slot=self.slot2)
        self.assertEqual(Visit.objects.count(),1);self.assertEqual(ResourceClaim.objects.count(),2)
    def test_mismatched_duration_rejected(self):
        with self.assertRaises(RuleError):create_appointment(actor=self.front,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,
            start=self.t,end=self.t+timedelta(minutes=15),service_id=self.service.pk)
        self.assertFalse(Visit.objects.exists())
    def test_preparing_blocks_all_new_bookings(self):
        self.policy.state='PREPARING';self.policy.save()
        with self.assertRaises(RuleError):self.booking()
    def test_old_writer_cannot_bypass_service(self):
        with self.assertRaises(RuleError):self.book(start=self.t,end=self.t+timedelta(minutes=30))
    def test_closed_department_and_blocks(self):
        DepartmentHours.objects.all().delete()
        with self.assertRaises(RuleError):self.booking()
    def test_provider_eligibility(self):
        self.service.dentists.remove(self.d1)
        with self.assertRaises(RuleError):self.booking()
    def test_maintenance_unavailable(self):
        for asset in self.chairs:self.maintain(asset)
        with self.assertRaises(RuleError):self.booking()
    def test_cancel_releases_claims(self):
        v=self.booking();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='cancel',party='PATIENT',reason='课程患者明确取消')
        self.assertFalse(ResourceClaim.objects.filter(active=True).exists())
        self.booking()
    def test_expired_hold_cannot_block_future_booking(self):
        from coordination.models import WaitRequest,SchedulePlan,WaitOffer
        from scheduling.resources import claim_locked
        e=WaitRequest.objects.create(patient=self.p2,clinic=self.a,earliest=self.t,latest=self.slot1.ends_at,service=self.service,created_by=self.front)
        p=SchedulePlan.objects.create(clinic=self.a,created_by=self.manager)
        o=WaitOffer.objects.create(request=e,plan=p,slot=self.slot2,starts_at=self.t,ends_at=self.t+timedelta(minutes=30),expires_at=timezone.now()-timedelta(seconds=1))
        b=choose_bundle(slot=self.slot2,start=o.starts_at,end=o.ends_at,service_id=self.service.pk)
        with transaction.atomic():claim_locked(actor=self.front,snapshot=b,start=o.starts_at,end=o.ends_at,offer=o)
        self.booking()
        self.assertFalse(ResourceClaim.objects.filter(kind='HOLD',active=True).exists())
    def test_postgres_exclusion_enforces_real_asset(self):
        v=self.booking();plan=v.resource_plans.get()
        with self.assertRaises(IntegrityError),transaction.atomic():
            historical=ResourcePlan.objects.create(visit=v,service=self.service,room=self.room,snapshot={},is_current=False,recorded_by=self.front,reason='数据库约束验证')
            ResourceClaim.objects.create(plan=historical,asset=plan.claims.get().asset,starts_at=self.t,ends_at=self.t+timedelta(minutes=30),kind='FIRM')

    def test_previous_patient_overrun_blocks_checkin(self):
        first=self.booking();second=self.booking(patient=self.p2,start=self.t+timedelta(minutes=30))
        change_appointment(actor=self.front,visit_id=first.pk,expected_version=0,action='check_in')
        with self.assertRaisesMessage(RuleError,'上一位患者'):change_appointment(actor=self.front,visit_id=second.pk,expected_version=0,action='check_in')
    def test_front_preview_replay_and_stale_catalogue(self):
        p=prepare_booking(actor=self.front,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),service_id=self.service.pk,consent=True)
        v,repeated=confirm_booking(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        w,repeated=confirm_booking(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(v.pk,w.pk);self.assertTrue(repeated);self.assertEqual(Visit.objects.count(),1)
    def test_revocation_and_clinic_rejection(self):
        p=prepare_booking(actor=self.front,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),service_id=self.service.pk,consent=True)
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        with self.assertRaises(PermissionDenied):confirm_booking(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)

class TelephoneReceptionTests(ResourceFixture,TransactionTestCase):
    def setUp(self):self.resources()
    def test_consultation_no_booking_no_clinical_grant(self):
        c=self.case();self.assertIsNone(c.patient_id);self.assertFalse(Visit.objects.exists());self.assertFalse(ResourceClaim.objects.exists())
    def test_required_patient_and_explicit_consent(self):
        c=self.case()
        with self.assertRaises(RuleError):self.step(c,'BOOK',slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),consent=True,note='协商')
    def test_multicommunication_and_unique_atomic_booking(self):
        c=self.case(patient_no=self.p1.patient_no)
        c=self.step(c,'NOTE',note='第二次沟通核实服务与时间')
        p=prepare_case(actor=self.front,case_id=c.pk,expected_revision=c.revision,action='BOOK',fields=dict(slot_id=self.slot1.pk,
            start=self.t,end=self.t+timedelta(minutes=30),consent=True,note='第三次沟通，患者明确同意'))
        first,_=confirm_case(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        repeat,again=confirm_case(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(first.visit_id,repeat.visit_id);self.assertTrue(again);self.assertEqual(Visit.objects.count(),1)
        self.assertEqual(first.communications.count(),3)
    def test_pending_requires_deadline(self):
        with self.assertRaises(RuleError):self.case(due_at=None)
    def test_no_booking_reason(self):
        c=self.case();self.step(c,'UNBOOKED',reason_code='NO_RESOURCE',note='患者拒绝其他时段')
        c.refresh_from_db();self.assertEqual(c.state,'UNBOOKED');self.assertFalse(Visit.objects.exists())
    def test_manager_cannot_read_contacts(self):
        from reception.services import cases_for
        with self.assertRaises(PermissionDenied):cases_for(self.manager)
    def test_telephone_waitlist_accepts_same_original_visit(self):
        from coordination.services import create_plan,publish_plan,answer_offer
        c=self.case(patient_no=self.p1.patient_no)
        c=self.step(c,'WAITLIST',earliest=self.t,latest=self.t+timedelta(hours=3),due_at=timezone.now()+timedelta(hours=2),note='患者同意候补')
        p=create_plan(actor=self.manager,clinic_id=self.a.pk);self.assertEqual(p.metadata['algorithm'],'RESOURCE_GREEDY_V1')
        publish_plan(actor=self.manager,plan_id=p.pk)
        offer=c.wait_request.offers.get();answer_offer(actor=self.front,offer_id=offer.pk,accept=True)
        c.refresh_from_db();offer.refresh_from_db()
        self.assertEqual(c.state,'BOOKED');self.assertEqual(c.visit_id,offer.visit_id);self.assertEqual(Visit.objects.count(),1)

    def test_consultation_contact_correction_keeps_original_history(self):
        c=self.case();original=c.contact
        fields=self.reception_fields(contact='已重新核实的合成联络',patient_no=self.p1.patient_no,note='核实联络修正，不自动改写患者资料')
        c=self.step(c,'UPDATE',**fields)
        self.assertEqual(c.contact,'已重新核实的合成联络');self.assertEqual(c.communications.first().snapshot['contact'],original)
        self.p1.refresh_from_db();self.assertEqual(self.p1.phone,'000')


class ResourceCoordinationTests(ResourceFixture,TransactionTestCase):
    def setUp(self):self.resources()
    def test_maintenance_preserves_promise_and_records_impact(self):
        v=self.booking();asset=v.resource_plans.get().claims.get().asset
        self.maintain(asset);v.refresh_from_db()
        self.assertEqual(v.status,'SCHEDULED');self.assertEqual(Visit.objects.count(),1)
        self.assertEqual(ResourceCoordination.objects.get().plan.visit_id,v.pk)
        with self.assertRaises(RuleError):change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
    def test_compatible_replacement_retains_versions(self):
        from scheduling.resource_coordination import replacement_options,prepare_coordination,confirm_coordination
        v=self.booking();plan=v.resource_plans.get();self.maintain(plan.claims.get().asset)
        _,options=replacement_options(self.front,plan.pk);self.assertTrue(options)
        p=prepare_coordination(actor=self.front,plan_id=plan.pk,action='REPLACE',fields={'assets':[r['id'] for r in options[0]['resources']],'note':'前台核对同店同医师同时间兼容替换'})
        a,_=confirm_coordination(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        _,repeated=confirm_coordination(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeated);self.assertEqual(v.resource_plans.count(),2)
        plan.refresh_from_db();self.assertFalse(plan.is_current);self.assertFalse(plan.claims.get().active)
        v.refresh_from_db();self.assertEqual(v.scheduled_start,self.t);self.assertEqual(v.dentist_id,self.d1.pk)
        change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        self.assertEqual(ResourceCoordination.objects.get().state,'REPLACED')
    def test_fault_during_treatment_does_not_move_patient(self):
        from scheduling.resource_coordination import replacement_options
        v=self.booking();change_appointment(actor=self.front,visit_id=v.pk,expected_version=0,action='check_in')
        self.maintain(v.resource_plans.get().claims.get().asset)
        with self.assertRaisesMessage(RuleError,'医护'):replacement_options(self.front,v.resource_plans.get().pk)
        v.refresh_from_db();self.assertEqual(v.status,'CHECKED_IN')
    def test_unanswered_contact_keeps_original_booking(self):
        from scheduling.resource_coordination import prepare_coordination,confirm_coordination
        v=self.booking();plan=v.resource_plans.get();self.maintain(plan.claims.get().asset);issue=ResourceCoordination.objects.get()
        p=prepare_coordination(actor=self.front,plan_id=plan.pk,action='CONTACT',fields=dict(issue=issue.pk,owner=self.front2.pk,
            due_at=timezone.now()+timedelta(hours=1),note='患者未接听，约定继续联系'))
        confirm_coordination(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        v.refresh_from_db();issue.refresh_from_db()
        self.assertEqual(v.status,'SCHEDULED');self.assertEqual(issue.owner_id,self.front2.pk)
        self.assertEqual(issue.state,'CONTACT');self.assertIsNotNone(issue.due_at)
    def test_premature_resolve_rejected(self):
        from scheduling.resource_coordination import prepare_coordination,confirm_coordination
        v=self.booking();plan=v.resource_plans.get();self.maintain(plan.claims.get().asset);issue=ResourceCoordination.objects.get()
        p=prepare_coordination(actor=self.front,plan_id=plan.pk,action='RESOLVE',fields=dict(issue=issue.pk,note='尝试在未维修前关闭'))
        with self.assertRaises(RuleError):confirm_coordination(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
    def test_new_contact_for_overrun_is_explicit(self):
        from scheduling.resource_coordination import prepare_coordination,confirm_coordination
        v=self.booking();plan=v.resource_plans.get()
        p=prepare_coordination(actor=self.front,plan_id=plan.pk,action='OPEN',fields=dict(asset=plan.claims.get().asset_id,
            owner=self.front.pk,due_at=timezone.now()+timedelta(minutes=15),note='前台与医护核实椅位仍在使用'))
        confirm_coordination(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(ResourceCoordination.objects.get().state,'CONTACT')
        v.refresh_from_db();self.assertEqual(v.status,'SCHEDULED')
    def test_department_block_does_not_cancel_original(self):
        p=prepare_config(actor=self.manager,kind='block',fields={'department':self.department.pk,'room':'','asset':'',
            'starts_at':self.t.isoformat(),'ends_at':(self.t+timedelta(hours=1)).isoformat(),'reason':'课程临时关闭核实'})
        v=self.booking();confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):self.booking(patient=self.p2,slot=self.slot2)
        v.refresh_from_db();self.assertEqual(v.status,'SCHEDULED');self.assertEqual(ResourceCoordination.objects.count(),1)

class ResourcePortalAndWaitlistTests(ResourceFixture,TransactionTestCase):
    def setUp(self):
        self.resources()
        from accounts.models import UserAccount
        from portal.models import PatientAccess
        self.portal=UserAccount.objects.create_user(username='resource_patient',password='synthetic-resource-patient')
        PatientAccess.objects.create(user=self.portal,patient=self.p2)
        self.portal._adc_workspace=WorkspaceContext.objects.create(user=self.portal,role='PATIENT')
    def test_portal_service_duration_and_no_equipment_selection(self):
        from portal.services import preview_booking,confirm_booking,public_options
        self.service.duration_minutes=45;self.service.save()
        rows=public_options(self.portal,self.a.pk,self.t.date(),self.service.pk)
        self.assertTrue(rows);self.assertEqual(rows[0]['end']-rows[0]['start'],timedelta(minutes=45))
        slot,end,token=preview_booking(user=self.portal,slot_id=self.slot2.pk,start=self.t,service_id=self.service.pk)
        visit=confirm_booking(actor=self.portal,token=token)
        self.assertEqual(visit.scheduled_end-visit.scheduled_start,timedelta(minutes=45));self.assertEqual(visit.resource_plans.count(),1)
        self.assertEqual(confirm_booking(actor=self.portal,token=token).pk,visit.pk)
    def test_portal_legacy_preview_rejected_after_enable(self):
        from portal.services import preview_booking
        with self.assertRaises(RuleError):preview_booking(user=self.portal,slot_id=self.slot2.pk,start=self.t)
    def test_waitlist_15_minute_service(self):
        from coordination.services import join_waitlist,create_plan,publish_plan,answer_offer
        self.service.duration_minutes=15;self.service.save()
        e=join_waitlist(actor=self.front,clinic_id=self.a.pk,patient_no=self.p1.patient_no,service_id=self.service.pk,
            earliest=self.t,latest=self.t+timedelta(minutes=15))
        p=create_plan(actor=self.manager,clinic_id=self.a.pk);publish_plan(actor=self.manager,plan_id=p.pk)
        o=e.offers.get();self.assertEqual(o.ends_at-o.starts_at,timedelta(minutes=15))
        answer_offer(actor=self.front,offer_id=o.pk,accept=True);self.assertEqual(Visit.objects.count(),1)
    def test_offer_snapshot_survives_catalogue_duration_edit(self):
        from coordination.services import join_waitlist,create_plan,publish_plan,answer_offer
        e=join_waitlist(actor=self.front,clinic_id=self.a.pk,patient_no=self.p1.patient_no,service_id=self.service.pk,
            earliest=self.t,latest=self.t+timedelta(hours=2))
        p=create_plan(actor=self.manager,clinic_id=self.a.pk);publish_plan(actor=self.manager,plan_id=p.pk)
        self.service.duration_minutes=60;self.service.save()
        o=e.offers.get();answer_offer(actor=self.front,offer_id=o.pk,accept=True);o.refresh_from_db()
        self.assertEqual(o.visit.scheduled_end-o.visit.scheduled_start,timedelta(minutes=30))
        self.assertEqual(o.resource_plans.get().snapshot['service']['duration'],30)
    def test_decline_and_withdraw_release_physical_hold(self):
        from coordination.services import join_waitlist,create_plan,publish_plan,answer_offer,withdraw
        e=join_waitlist(actor=self.front,clinic_id=self.a.pk,patient_no=self.p1.patient_no,service_id=self.service.pk,
            earliest=self.t,latest=self.t+timedelta(hours=2))
        p=create_plan(actor=self.manager,clinic_id=self.a.pk);publish_plan(actor=self.manager,plan_id=p.pk)
        o=e.offers.get();answer_offer(actor=self.front,offer_id=o.pk,accept=False)
        self.assertFalse(ResourceClaim.objects.filter(active=True).exists())
        withdraw(actor=self.front,entry_id=e.pk)
    def test_reschedule_preserves_old_plan_and_claims_only_new(self):
        from scheduling.reschedule_services import prepare_reschedule,confirm_reschedule
        v=self.booking();plan=v.resource_plans.get()
        p=prepare_reschedule(actor=self.front,visit_id=v.pk,expected_version=0,new_slot_id=self.slot1.pk,
            start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=1,minutes=30),reason='患者明确要求调整时间',service_id=self.service.pk)
        r=confirm_reschedule(actor=self.front,visit_id=v.pk,proposal_token=p['proposal_token'],confirmed=True)
        v.refresh_from_db();self.assertEqual(v.status,'RESCHEDULED');self.assertEqual(r.visit.replaces_visit_id,v.pk)
        self.assertFalse(plan.claims.get().active);self.assertEqual(r.visit.resource_plans.count(),1)
    def test_next_catalogue_revision_invalidates_old_preview(self):
        from portal.services import preview_booking,confirm_booking
        _,_,token=preview_booking(user=self.portal,slot_id=self.slot2.pk,start=self.t,service_id=self.service.pk)
        self.policy.revision+=1;self.policy.save()
        with self.assertRaises(RuleError):confirm_booking(actor=self.portal,token=token)
        self.assertFalse(Visit.objects.exists())

class ResourceCatalogueAndHistoryTests(ResourceFixture,TransactionTestCase):
    def setUp(self):self.resources()
    def test_same_clinic_room_and_asset_enforced_in_command(self):
        foreign=Department.objects.create(clinic=self.b,code='FOREIGN',name='其他诊所')
        r=TreatmentRoom.objects.create(department=foreign,code='F',name='外店诊室')
        with self.assertRaises(RuleError):prepare_config(actor=self.manager,kind='binding',fields={'asset':self.chairs[0].pk,'room':r.pk,'shared':False,'is_active':True})
    def test_chair_is_not_a_shared_asset(self):
        with self.assertRaises(RuleError):prepare_config(actor=self.manager,kind='binding',fields={'asset':self.chairs[0].pk,'room':'','shared':True,'is_active':True})
    def test_activation_requires_mapping_existing_promises(self):
        self.policy.state='PREPARING';self.policy.save()
        v=Visit.objects.create(patient=self.p1,clinic=self.a,dentist=self.d1,availability_slot=self.slot1,scheduled_start=self.t,scheduled_end=self.t+timedelta(minutes=30))
        with self.assertRaises(RuleError):prepare_config(actor=self.manager,kind='activate')
        from scheduling.resource_mapping import prepare_mapping,confirm_mapping
        p=prepare_mapping(actor=self.manager,kind='visit',source_id=v.pk,service_id=self.service.pk,note='课程前台逐项核实原承诺，无补造来源')
        confirm_mapping(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        p=prepare_config(actor=self.manager,kind='activate');confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.policy.refresh_from_db();self.assertEqual(self.policy.state,'ENABLED')
    def test_history_plan_and_communication_are_immutable(self):
        v=self.booking();p=v.resource_plans.get();c=self.case()
        for operation in [lambda:ResourcePlan.objects.filter(pk=p.pk).update(snapshot={'changed':True}),
            lambda:c.communications.all().update(note='篡改历史'),lambda:c.communications.all().delete()]:
            with self.assertRaises(IntegrityError),transaction.atomic():operation()
    def test_full_patient_is_required_without_fabricating_allergies(self):
        c=self.case(patient_no=self.p1.patient_no)
        self.p1.emergency_phone='';self.p1.save(update_fields=['emergency_phone'])
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):self.step(c,'BOOK',slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),consent=True,note='尝试成约')
        self.assertFalse(Visit.objects.exists());self.p1.refresh_from_db();self.assertEqual(self.p1.allergy_status,'UNKNOWN')
    def test_reassign_revoked_owner_retains_communication(self):
        c=self.case();RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(is_active=False)
        p=prepare_case(actor=self.front2,case_id=c.pk,expected_revision=c.revision,action='ASSIGN',fields=dict(owner=self.front2.pk,due_at=timezone.now()+timedelta(hours=1),note='原负责人撤权，明确交接'))
        c,_=confirm_case(actor=self.front2,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(c.owner_id,self.front2.pk);self.assertEqual(c.communications.count(),2)
    def test_booking_cancellation_keeps_reception_success(self):
        c=self.case(patient_no=self.p1.patient_no)
        c=self.step(c,'BOOK',slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),consent=True,note='明确同意后成约')
        change_appointment(actor=self.front,visit_id=c.visit_id,expected_version=0,action='cancel',party='PATIENT',reason='患者要求取消')
        c.refresh_from_db();self.assertEqual(c.state,'BOOKED');self.assertEqual(c.visit.status,'CANCELLED')
    def test_configuration_is_preview_first_and_idempotent(self):
        p=prepare_config(actor=self.manager,kind='room',fields=dict(department=self.department.pk,code='SECOND',name='第二诊室',is_active=True))
        count=TreatmentRoom.objects.count();self.assertEqual(count,1)
        a,_=confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        b,repeat=confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(repeat);self.assertEqual(a.pk,b.pk);self.assertEqual(TreatmentRoom.objects.count(),count+1)

class ResourceConcurrencyTests(ResourceFixture,TransactionTestCase):
    def setUp(self):
        self.resources();ResourceBinding.objects.filter(asset=self.chairs[1]).update(is_active=False)
    def race(self,*calls):
        from threading import Barrier
        gate=Barrier(len(calls))
        def worker(fn):
            close_old_connections()
            try:
                gate.wait(timeout=5)
                try:return ('ok',fn())
                except RuleError:return ('conflict',None)
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=len(calls)) as pool:return list(pool.map(worker,calls))
    def test_two_front_desks_one_chair_one_winner(self):
        results=self.race(lambda:self.booking(),lambda:self.booking(patient=self.p2,slot=self.slot2,actor=self.front2))
        self.assertEqual(sorted(x[0] for x in results),['conflict','ok'])
        self.assertEqual(Visit.objects.count(),1);self.assertEqual(ResourceClaim.objects.filter(active=True).count(),1)
    def test_booking_races_maintenance_without_losing_original_promise(self):
        results=self.race(lambda:self.booking(),lambda:self.maintain(self.chairs[0]))
        self.chairs[0].refresh_from_db();self.assertEqual(self.chairs[0].state,'MAINTENANCE')
        if Visit.objects.exists():self.assertEqual(ResourceCoordination.objects.count(),1)
        else:self.assertFalse(ResourceClaim.objects.exists())
    def test_same_preview_concurrent_retry_single_effect(self):
        p=prepare_booking(actor=self.front,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),service_id=self.service.pk,consent=True)
        results=self.race(*[lambda:confirm_booking(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)[0].pk for _ in range(2)])
        self.assertTrue(all(x[0]=='ok' for x in results));self.assertEqual(results[0][1],results[1][1]);self.assertEqual(Visit.objects.count(),1)

    def test_website_and_frontdesk_compete_for_same_chair(self):
        from accounts.models import UserAccount
        from portal.models import PatientAccess
        from portal.services import preview_booking,confirm_booking as portal_confirm
        portal=UserAccount.objects.create_user(username='race_portal')
        PatientAccess.objects.create(user=portal,patient=self.p2)
        portal._adc_workspace=WorkspaceContext.objects.create(user=portal,role='PATIENT')
        front=prepare_booking(actor=self.front,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),service_id=self.service.pk,consent=True)
        _,_,token=preview_booking(user=portal,slot_id=self.slot2.pk,start=self.t,service_id=self.service.pk)
        result=self.race(lambda:confirm_booking(actor=self.front,proposal_token=front['proposal_token'],confirmed=True)[0].pk,
            lambda:portal_confirm(actor=portal,token=token).pk)
        self.assertEqual(sorted(x[0] for x in result),['conflict','ok']);self.assertEqual(Visit.objects.count(),1)


class ResourceHTTPAndFinancialTests(ResourceFixture,TransactionTestCase):
    def setUp(self):self.resources()
    def test_reception_preview_before_create_and_confirmation_scope(self):
        self.client.force_login(self.front)
        from django.urls import reverse
        data={k:v if v is not None else '' for k,v in self.reception_fields().items()};data['owner']=self.front.pk
        response=self.client.post(reverse('reception_create'),data)
        self.assertEqual(response.status_code,200);self.assertFalse(ReceptionCase.objects.exists())
        token=response.context['form'].initial['proposal_token']
        response=self.client.post(reverse('reception_create'),{'action':'confirm','proposal_token':token,'confirmed':'on'})
        self.assertEqual(response.status_code,302)
        response=self.client.get(response.url);self.assertContains(response,'沟通历史');self.assertContains(response,'下次联系期限')
    def test_seven_roles_new_route_boundaries(self):
        from accounts.models import UserAccount
        from portal.models import PatientAccess
        from django.urls import reverse
        doctor=UserAccount.objects.create_user(username='resource_doctor',dentist=self.d1)
        RoleAssignment.objects.create(user=doctor,role='DENTIST',scope_kind='SELF_DENTIST')
        finance=UserAccount.objects.create_user(username='resource_finance');RoleAssignment.objects.create(user=finance,role='FINANCE',scope_kind='CHAIN')
        hq=UserAccount.objects.create_user(username='resource_hq');RoleAssignment.objects.create(user=hq,role='HQ',scope_kind='CHAIN')
        patient=UserAccount.objects.create_user(username='resource_patient_http');PatientAccess.objects.create(user=patient,patient=self.p1)
        c=self.case();private=c.contact
        roles=[(self.front,'FRONT_DESK'),(self.manager,'MANAGER'),(doctor,'DENTIST'),(finance,'FINANCE'),(hq,'HQ'),(patient,'PATIENT'),(self.tech,'SYSADMIN')]
        for actor,role in roles:
            self.client.force_login(actor)
            for name,allowed in [('reception_list',{'FRONT_DESK'}),('resource_catalogue',{'MANAGER'}),
                ('resource_candidates',{'FRONT_DESK'}),('resource_coordination_list',{'FRONT_DESK','MANAGER'}),('resource_summary',{'HQ'})]:
                response=self.client.get(reverse(name));self.assertEqual(response.status_code,200 if role in allowed else 403,(role,name))
                if role!='FRONT_DESK':self.assertNotContains(response,private,status_code=response.status_code)
    def test_front_resource_booking_http_requires_two_steps(self):
        from django.urls import reverse
        self.client.force_login(self.front)
        r=self.client.post(reverse('visit_create'),dict(patient_no=self.p1.patient_no,slot=self.slot1.pk,start=self.t.isoformat(),
            end=(self.t+timedelta(minutes=30)).isoformat(),service=self.service.pk,consent='on'))
        self.assertEqual(r.status_code,200);self.assertFalse(Visit.objects.exists());self.assertContains(r,'复述并确认预约')
        t=r.context['form'].initial['proposal_token']
        r=self.client.post(reverse('visit_create'),dict(action='confirm',proposal_token=t,confirmed='on'))
        self.assertEqual(r.status_code,302);self.assertEqual(Visit.objects.count(),1)
    def test_booking_and_resources_do_not_invent_financial_facts(self):
        from decimal import Decimal
        from care.models import Invoice,TreatmentRecord
        from finance.cash_models import CashEntry
        from care.services import review_allergies,add_treatment,complete_visit
        from registry.models import TreatmentType
        from accounts.models import UserAccount
        c=self.case(patient_no=self.p1.patient_no)
        c=self.step(c,'BOOK',slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(minutes=30),consent=True,note='患者同意唯一成约')
        self.assertEqual((Invoice.objects.count(),CashEntry.objects.count(),TreatmentRecord.objects.count()),(0,0,0))
        doctor=UserAccount.objects.create_user(username='resource_treating_doctor',dentist=self.d1)
        RoleAssignment.objects.create(user=doctor,role='DENTIST',scope_kind='SELF_DENTIST')
        doctor._adc_workspace=WorkspaceContext.objects.create(user=doctor,role='DENTIST')
        v=change_appointment(actor=self.front,visit_id=c.visit_id,expected_version=0,action='check_in')
        review_allergies(actor=doctor,visit_id=v.pk,expected_version=v.lock_version,patient_version=self.p1.allergy_info_version,status='NO_KNOWN')
        v.refresh_from_db();t=TreatmentType.objects.create(code='ACTUAL',name='合成实际治疗',unit_definition='次',standard_unit_price=Decimal('120.00'))
        add_treatment(actor=doctor,visit_id=v.pk,expected_version=v.lock_version,treatment_id=t.pk,quantity=Decimal('2'))
        self.assertEqual(Invoice.objects.count(),0)
        v.refresh_from_db();bill=complete_visit(actor=doctor,visit_id=v.pk,expected_version=v.lock_version,outcome='TREATED')
        self.assertEqual(bill.current_record_version.total_amount,Decimal('240.00'));self.assertEqual(CashEntry.objects.count(),0)
        self.assertEqual(ResourcePlan.objects.count(),1);c.refresh_from_db();self.assertEqual(c.visit.status,'COMPLETED')
