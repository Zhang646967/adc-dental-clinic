"""C1.1 real PostgreSQL, channel permissions, retained effects and identity races."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.db import connection, close_old_connections, transaction, DatabaseError
from django.test import TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import Invoice,AuditEvent
from finance.cash_models import CashEntry
from portal import relationships as rel,services,rescheduling
from portal.models import PatientAccess,PatientRelationship,PatientRelationshipEvent,PatientAppointmentGrant,BookingReceipt
from portal.policies import patient_access,has_patient_access,subject_choices,form_authority,read_form_authority
from scheduling.models import Visit,VisitRequest,AvailabilitySlot
from scheduling.resource_models import ServicePresentation,ResourceClaim
from coordination.models import WaitRequest,WaitOffer
from coordination import services as wait
from tests.test_reception_resources import ResourceFixture
from tests import test_mini_program as mini
from tests.workspace_client import WorkspaceClient
from workspaces.models import WorkspaceContext
from workspaces.context import SESSION_KEY

class RelationshipTests(ResourceFixture,TransactionTestCase):
    setUp=mini.MiniProgramTests.setUp
    login=mini.MiniProgramTests.login
    post=mini.MiniProgramTests.post
    preview=mini.MiniProgramTests.preview

    def make_case(self,kind='PARENT',user=None,patient=None,verify=True,actor=None):
        actor=actor or self.front
        RoleAssignment.objects.filter(user=actor,role='FRONT_DESK',clinic=self.a).update(can_verify_patient_relationships=True)
        t=rel.prepare_create(actor=actor,patient_no=(patient or self.p1).patient_no,related_name='合成关系人',kind=kind,
            username=(user or self.other).username,note='课程合成关系受理')
        case,_=rel.confirm(actor=actor,token=t,confirmed=True)
        if verify:self.decide(case,'VERIFY',actor=actor)
        case.refresh_from_db();return case
    def decide(self,case,action,actor=None):
        actor=actor or self.front
        t=rel.prepare_action(actor=actor,case_id=case.pk,action=action,basis='IN_PERSON',reference='SYNTHETIC-EVIDENCE-1',
            note='合成核验依据已人工核对',valid_until=timezone.now()+timedelta(days=30))
        return rel.confirm(actor=actor,token=t,confirmed=True)[0]
    def delegate(self):
        case=self.make_case();self.client,self.session=self.login(self.other)
        r=self.post('mini_subject_select',{'subject':f'grant:{case.appointment_grant.pk}'})
        self.assertEqual(r.status_code,200,r.content);self.session=r.json()['data'];return case
    def actor(self,user=None):
        user=UserAccount.objects.get(pk=(user or self.other).pk)
        user._adc_workspace=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY]);return user
    def booked(self):
        token=self.preview();r=self.post('mini_book_confirm',{'proposal_token':token,'confirmed':'on'})
        self.assertEqual(r.status_code,200,r.content);return Visit.objects.get(pk=r.json()['data']['id']),token
    def join(self):
        r=self.post('mini_wait_join_preview',{'clinic':self.a.pk,'service':self.service.pk,'dentist':self.d2.pk,
            'earliest':(self.t+timedelta(hours=2)).isoformat(),'latest':(self.t+timedelta(hours=3)).isoformat()})
        self.assertEqual(r.status_code,200,r.content)
        r=self.post('mini_wait_join_confirm',{'proposal_token':r.json()['data']['proposal_token'],'confirmed':'on'})
        self.assertEqual(r.status_code,200,r.content);return WaitRequest.objects.get(pk=r.json()['data']['wait']['id'])
    def test_create_and_verify_are_explicit_separate_effects(self):
        case=self.make_case(verify=False)
        self.assertFalse(PatientAppointmentGrant.objects.exists());self.decide(case,'VERIFY')
        self.assertTrue(case.appointment_grant.is_active);self.assertEqual(case.events.count(),2)
    def test_contact_and_family_never_grant_appointment_access(self):
        for kind in ['CONTACT','FAMILY']:
            u=UserAccount.objects.create_user(username=kind,password=self.password)
            case=self.make_case(kind,user=u)
            self.assertEqual(case.state,'VERIFIED');self.assertFalse(has_patient_access(u));self.assertFalse(PatientAppointmentGrant.objects.filter(relationship=case).exists())
    def test_unverified_relationship_does_not_login_or_switch(self):
        u=UserAccount.objects.create_user(username='unverified',password=self.password);self.make_case(user=u,verify=False)
        self.assertFalse(has_patient_access(u));self.assertEqual(subject_choices(u),[])
    def test_same_phone_does_not_merge_patients(self):
        self.assertEqual(self.p1.phone,self.p2.phone)
        self.make_case();self.assertEqual(PatientAccess.objects.get(user=self.other).patient_id,self.p2.pk)
        self.assertEqual(len(subject_choices(self.other)),2)
    def test_only_explicit_frontdesk_reviewer_can_verify(self):
        c=self.make_case(verify=False)
        with self.assertRaises(PermissionDenied):self.decide(c,'VERIFY',actor=self.front2)
        self.assertFalse(PatientAppointmentGrant.objects.exists())
    def test_reviewer_revoked_after_preview(self):
        c=self.make_case(verify=False)
        t=rel.prepare_action(actor=self.front,case_id=c.pk,action='VERIFY',basis='IN_PERSON',reference='synthetic',note='已核对',valid_until=timezone.now()+timedelta(days=1))
        RoleAssignment.objects.filter(user=self.front).update(can_verify_patient_relationships=False)
        with self.assertRaises(PermissionDenied):rel.confirm(actor=self.front,token=t,confirmed=True)
    def test_role_constraint_blocks_manager_as_reviewer(self):
        with self.assertRaises(DatabaseError),transaction.atomic():RoleAssignment.objects.filter(user=self.manager).update(can_verify_patient_relationships=True)
    def test_foreign_patient_is_not_a_relationship_lookup(self):
        with self.assertRaises(Exception) as e:self.make_case(patient=self.p2)
        self.assertIn(type(e.exception).__name__,['DoesNotExist','PermissionDenied']);self.assertFalse(PatientRelationship.objects.exists())
    def test_missing_account_can_be_linked_before_review(self):
        t=rel.prepare_create(actor=self.front,patient_no=self.p1.patient_no,related_name='待核验人',kind='GUARDIAN',note='待核对账号')
        c,_=rel.confirm(actor=self.front,token=t,confirmed=True)
        RoleAssignment.objects.filter(user=self.front,clinic=self.a).update(can_verify_patient_relationships=True)
        with self.assertRaises(RuleError):self.decide(c,'VERIFY')
        t=rel.prepare_action(actor=self.front,case_id=c.pk,action='LINK_ACCOUNT',username=self.other.username,note='已核对账号归属')
        rel.confirm(actor=self.front,token=t,confirmed=True);self.decide(c,'VERIFY')
        c.refresh_from_db();self.assertEqual(c.appointment_grant.relationship.delegate_user_id,self.other.pk)
    def test_create_replay_and_duplicate_case_do_not_duplicate_authority(self):
        t=rel.prepare_create(actor=self.front,patient_no=self.p1.patient_no,related_name='受理人',kind='DELEGATE',username=self.other.username,note='已受理')
        a,_=rel.confirm(actor=self.front,token=t,confirmed=True);b,replay=rel.confirm(actor=self.front,token=t,confirmed=True)
        self.assertTrue(replay);self.assertEqual(a.pk,b.pk);self.assertEqual(a.events.count(),1)
        with self.assertRaises(RuleError):self.make_case()
    def test_events_reject_sql_update_and_delete(self):
        c=self.make_case()
        for sql in ['UPDATE adc_patient_relationship_event SET note=\'changed\' WHERE relationship_id=%s','DELETE FROM adc_patient_relationship_event WHERE relationship_id=%s']:
            with self.assertRaises(DatabaseError),transaction.atomic():
                with connection.cursor() as cur:cur.execute(sql,[c.pk])
    def test_delegate_only_login_requires_patient_selection(self):
        u=UserAccount.objects.create_user(username='delegate_only',password=self.password);self.make_case(user=u)
        self.client,self.session=self.login(u);self.assertTrue(self.session['subject_required'])
        r=self.client.get(reverse('mini_visits'));self.assertEqual(r.status_code,409)
        self.assertEqual(r.json()['code'],'SUBJECT_REQUIRED');self.assertEqual(self.client.get(reverse('mini_subjects')).status_code,200)
    def test_delegate_booking_has_one_explicit_receipt_and_no_money(self):
        c=self.delegate();v,t=self.booked()
        receipt=BookingReceipt.objects.get(visit=v)
        self.assertEqual(receipt.appointment_grant_id,c.appointment_grant.pk);self.assertIsNone(receipt.access_id)
        r=self.post('mini_book_confirm',{'proposal_token':t,'confirmed':'on'})
        self.assertEqual(r.status_code,200,r.content);self.assertEqual(Visit.objects.count(),1)
        self.assertFalse(Invoice.objects.exists());self.assertFalse(CashEntry.objects.exists())
    def test_switch_away_and_back_invalidates_old_preview(self):
        c=self.delegate();t=self.preview()
        for key in ['self',f'grant:{c.appointment_grant.pk}']:
            r=self.post('mini_subject_select',{'subject':key});self.assertEqual(r.status_code,200);self.session=r.json()['data']
        self.assertEqual(self.post('mini_book_confirm',{'proposal_token':t,'confirmed':'on'}).status_code,409);self.assertFalse(Visit.objects.exists())
    def test_cannot_select_someone_elses_grant(self):
        c=self.make_case()
        self.assertEqual(self.post('mini_subject_select',{'subject':f'grant:{c.appointment_grant.pk}'}).status_code,403)
    def test_suspend_and_reverify_do_not_revive_preview(self):
        c=self.delegate();t=self.preview();self.decide(c,'SUSPEND');self.decide(c,'VERIFY')
        self.assertEqual(self.post('mini_book_confirm',{'proposal_token':t,'confirmed':'on'}).status_code,409)
        self.assertFalse(Visit.objects.exists());self.assertEqual(c.events.count(),4)
    def test_revoke_retains_booking_and_cannot_replay(self):
        c=self.delegate();v,t=self.booked();self.decide(c,'REVOKE')
        self.assertEqual(self.post('mini_book_confirm',{'proposal_token':t,'confirmed':'on'}).status_code,409)
        v.refresh_from_db();self.assertEqual(v.status,'SCHEDULED');self.assertTrue(ResourceClaim.objects.filter(plan__visit=v,active=True).exists())
    def test_expiry_blocks_selected_patient(self):
        c=self.delegate()
        PatientAppointmentGrant.objects.filter(relationship=c).update(valid_from=timezone.now()-timedelta(days=2),valid_until=timezone.now()-timedelta(days=1))
        self.assertEqual(self.client.get(reverse('mini_visits')).status_code,409)
    def test_delegate_cannot_read_clinical_text_or_invoice(self):
        self.delegate();v,_=self.booked();Visit.objects.filter(pk=v.pk).update(chief_complaint='PRIVATE_CLINICAL_TEXT')
        r=self.client.get(reverse('mini_visit',args=[v.pk]));self.assertEqual(r.status_code,200);self.assertNotIn('PRIVATE_CLINICAL_TEXT',r.content.decode())
        r=self.client.get(reverse('portal_visit',args=[v.pk]));self.assertEqual(r.status_code,200);self.assertNotIn('PRIVATE_CLINICAL_TEXT',r.content.decode())
        with self.assertRaises(PermissionDenied):patient_access(self.actor(),self_only=True)
    def test_clinic_scope_applies_to_candidates_and_waitlist(self):
        self.delegate();actor=self.actor()
        with self.assertRaises(PermissionDenied):services.public_options(actor,clinic_id=self.b.pk)
        with self.assertRaises(PermissionDenied):wait.join_waitlist(actor=actor,clinic_id=self.b.pk,earliest=self.t,latest=self.t+timedelta(hours=1),authority=patient_access(actor).stamp)
    def test_child_service_requires_verified_delegate(self):
        ServicePresentation.objects.filter(pk=self.profile.pk).update(category='CHILDREN')
        self.assertEqual(self.client.get(reverse('mini_catalogue')).json()['data']['services'],[])
        self.delegate();self.assertEqual(len(self.client.get(reverse('mini_catalogue')).json()['data']['services']),1)
        self.booked()
    def test_general_appointment_delegate_does_not_imply_guardianship(self):
        ServicePresentation.objects.filter(pk=self.profile.pk).update(category='CHILDREN')
        case=self.make_case(kind='DELEGATE');self.client,self.session=self.login(self.other)
        response=self.post('mini_subject_select',{'subject':f'grant:{case.appointment_grant.pk}'})
        self.assertEqual(response.status_code,200,response.content);self.session=response.json()['data']
        self.assertFalse(self.session['guardian'])
        self.assertEqual(self.client.get(reverse('mini_catalogue')).json()['data']['services'],[])
        from portal.service_catalogue import require_self_service
        with self.assertRaises(RuleError):require_self_service(self.service.pk,actor=self.actor())
    def test_shared_reschedule_and_cancel_preserve_original(self):
        self.delegate();v,_=self.booked();actor=self.actor()
        p=rescheduling.prepare(actor=actor,visit_id=v.pk,expected_version=0,slot_id=self.slot2.pk,start=self.t+timedelta(hours=1),reason='代患者确认改期')
        new,_=rescheduling.confirm(actor=actor,visit_id=v.pk,proposal_token=p['proposal_token'],confirmed=True)
        v.refresh_from_db();self.assertEqual(v.status,'RESCHEDULED');self.assertEqual(new.replaces_visit_id,v.pk)
        with self.assertRaises(RuleError):services.cancel_booking(actor=actor,visit_id=new.pk,expected_version=0,reason='代约取消')
        services.cancel_booking(actor=actor,visit_id=new.pk,expected_version=0,reason='代约取消',authority=patient_access(actor).stamp)
        new.refresh_from_db();self.assertEqual(new.cancellation_party,'PATIENT');self.assertEqual(new.cancellation_reason,'代约取消')
    def test_waitlist_accept_uses_same_patient_and_resource_ledger(self):
        self.delegate();entry=self.join();plan=wait.create_plan(actor=self.front,clinic_id=self.a.pk);wait.publish_plan(actor=self.front,plan_id=plan.pk)
        offer=WaitOffer.objects.get(request=entry);actor=self.actor()
        wait.answer_offer(actor=actor,offer_id=offer.pk,accept=True,authority=patient_access(actor).stamp)
        offer.refresh_from_db();self.assertEqual(offer.visit.patient_id,self.p1.pk)
        self.assertEqual(Visit.objects.count(),1);self.assertTrue(ResourceClaim.objects.filter(plan__visit=offer.visit,active=True).exists())
    def test_revoked_waitlist_cannot_be_accepted(self):
        c=self.delegate();entry=self.join();plan=wait.create_plan(actor=self.front,clinic_id=self.a.pk);wait.publish_plan(actor=self.front,plan_id=plan.pk)
        offer=WaitOffer.objects.get(request=entry);actor=self.actor();stamp=patient_access(actor).stamp;self.decide(c,'REVOKE')
        with self.assertRaises(PermissionDenied):wait.answer_offer(actor=actor,offer_id=offer.pk,accept=True,authority=stamp)
        self.assertFalse(Visit.objects.exists());entry.refresh_from_db();self.assertEqual(entry.state,'OFFERED')
    def test_web_switch_stale_form_and_frontdesk_reception_pages(self):
        c=self.delegate();web=WorkspaceClient();web.force_login(self.other)
        r=web.post(reverse('portal_subjects'),{'subject':f'grant:{c.appointment_grant.pk}'})
        self.assertEqual(r.status_code,302);r=web.get(reverse('portal_home'));self.assertEqual(r.status_code,200);self.assertContains(r,self.p1.name)
        staff=WorkspaceClient();staff.force_login(self.front)
        for name,args in [('patient_relationships',[]),('patient_relationship_detail',[c.pk]),('patient_relationship_create',[])]:
            self.assertEqual(staff.get(reverse(name,args=args)).status_code,200)
    def test_old_web_authority_fails_after_selection(self):
        c=self.delegate();actor=self.actor();token=form_authority(actor);rel.select_subject(actor=actor,key='self')
        with self.assertRaises(RuleError):read_form_authority(actor,token)
    def test_receipt_requires_exactly_one_authority(self):
        self.delegate();v,_=self.booked()
        with self.assertRaises(DatabaseError),transaction.atomic():BookingReceipt.objects.filter(visit=v).update(access=self.access)
    def test_actual_postgres_two_actors_one_patient_compete(self):
        self.delegate();delegate=self.actor();owner=self.user;owner._adc_workspace=WorkspaceContext.objects.create(user=owner,role='PATIENT')
        tokens=[services.preview_booking(user=u,slot_id=self.slot1.pk,start=self.t,service_id=self.service.pk)[2] for u in [owner,delegate]]
        barrier=Barrier(2)
        def execute(pair):
            u,t=pair;close_old_connections()
            try:
                with connection.cursor() as cur:cur.execute("SET lock_timeout='8s'")
                barrier.wait(timeout=10)
                try:return services.confirm_booking(actor=u,token=t).pk
                except RuleError:return None
            finally:connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,zip([owner,delegate],tokens)))
        self.assertEqual(sum(x is not None for x in results),1);self.assertEqual(Visit.objects.count(),1);self.assertEqual(BookingReceipt.objects.count(),1)
