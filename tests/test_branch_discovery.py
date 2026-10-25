"""C0.4 public discovery and login-channel boundaries on real PostgreSQL."""
from datetime import timedelta,time
from concurrent.futures import ThreadPoolExecutor
from django.db import transaction,IntegrityError,close_old_connections
from django.test import Client,TransactionTestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from accounts.models import UserAccount,RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent,Invoice
from portal.models import BookingReceipt
from registry.directory_models import ClinicDirectory,ClinicDirectoryRevision
from registry.branch_services import prepare_directory,confirm_directory,values
from registry.branch_projection import opening_data
from scheduling.models import Visit
from scheduling.resource_models import ResourceBlock,Department,DepartmentHours,ResourceClaim
from workspaces.context import SESSION_KEY,token_for
from workspaces.models import WorkspaceContext
from tests import test_mini_program as mini_base
from tests import test_patient_relationships as relationship_base
from tests import test_mini_waitlist as wait_base
from tests.test_reception_resources import ResourceFixture


class BranchDiscoveryTests(ResourceFixture,TransactionTestCase):
    make_case=relationship_base.RelationshipTests.make_case
    decide=relationship_base.RelationshipTests.decide
    setUp=mini_base.MiniProgramTests.setUp
    login=mini_base.MiniProgramTests.login
    post=mini_base.MiniProgramTests.post
    preview=mini_base.MiniProgramTests.preview
    book=mini_base.MiniProgramTests.book
    join_preview=wait_base.MiniWaitlistTests.join_preview
    join=wait_base.MiniWaitlistTests.join
    offered=wait_base.MiniWaitlistTests.offered

    def fields(self,**changes):
        return dict(display_name='ADC口腔·长沙梅溪湖门店',province='湖南',city='长沙',district='岳麓区',
            address='合成门址101号',entrance='合成楼层2层东侧',public_phone='0731-00000101',
            latitude='28.180000',longitude='112.900000',map_latitude='28.176000',map_longitude='112.905000',
            coordinate_source='课程合成双坐标点，不是真实经营门址',synthetic=True,is_published=True,**changes)

    def publish(self,**changes):
        data=self.fields()
        current=ClinicDirectory.objects.filter(clinic=self.a).first()
        if current:data=values(current)
        data.update(changes)
        p=prepare_directory(actor=self.manager,fields=data)
        return confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]

    def public(self,client=None):
        response=(client or Client()).get(reverse('mini_public_discovery'))
        self.assertEqual(response.status_code,200,response.content)
        return response.json()['data']

    def test_anonymous_discovery_has_no_patient_or_workspace_effect(self):
        self.publish()
        before=(WorkspaceContext.objects.count(),AuditEvent.objects.count(),Visit.objects.count(),Invoice.objects.count())
        for name,args in [('mini_public_discovery',[]),('mini_public_service',[self.service.pk]),
                          ('public_home',[]),('public_clinics',[]),('public_service_detail',[self.service.pk])]:
            with self.subTest(name=name):self.assertEqual(Client().get(reverse(name,args=args)).status_code,200)
        self.assertEqual(before,(WorkspaceContext.objects.count(),AuditEvent.objects.count(),Visit.objects.count(),Invoice.objects.count()))
        self.assertFalse(BookingReceipt.objects.exists())

    def test_public_fields_exclude_private_people_and_internal_reason(self):
        self.publish()
        self.d1.home_address='PRIVATE_STAFF_HOME';self.d1.phone='PRIVATE_STAFF_PHONE';self.d1.save()
        ResourceBlock.objects.create(clinic=self.a,department=self.department,starts_at=self.t,
            ends_at=self.t+timedelta(hours=1),reason='PRIVATE_PATIENT_REASON',public_notice='科室临时调整',
            recorded_by=self.manager)
        text=str(self.public())
        for hidden in ('PRIVATE_STAFF_HOME','PRIVATE_STAFF_PHONE','PRIVATE_PATIENT_REASON',self.p1.patient_no,self.p2.patient_no):
            self.assertNotIn(hidden,text)
        self.assertIn('科室临时调整',text)

    def test_public_alias_does_not_rename_business_or_invoice_identity(self):
        original=(self.a.name,self.a.clinic_code,self.a.postal_address,self.a.phone)
        self.publish()
        self.a.refresh_from_db()
        self.assertEqual(original,(self.a.name,self.a.clinic_code,self.a.postal_address,self.a.phone))
        branch=self.public()['clinics'][0]
        self.assertEqual(branch['name'],'ADC口腔·长沙梅溪湖门店')
        self.assertEqual(branch['coordinate_system'],'WGS-84')
        self.assertEqual(branch['map_coordinate_system'],'GCJ-02')

    def test_missing_one_coordinate_is_rejected_by_database(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            ClinicDirectory.objects.create(clinic=self.a,latitude='28.1',longitude=None)

    def test_no_coordinate_is_unknown_not_zero(self):
        self.publish(latitude=None,longitude=None,map_latitude=None,map_longitude=None)
        row=self.public()['clinics'][0]
        self.assertIsNone(row['latitude']);self.assertIsNone(row['map_longitude'])

    def test_synthetic_environment_keeps_real_dial_and_navigation_disabled(self):
        self.publish(synthetic=False)
        self.assertTrue(self.public()['clinics'][0]['synthetic'])
        self.assertTrue(self.public()['offerings'][0]['synthetic'])

    def test_explicit_confirmation_and_retry_has_one_revision(self):
        p=prepare_directory(actor=self.manager,fields=self.fields())
        with self.assertRaises(RuleError):confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=False)
        first,replayed=confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        second,replayed=confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertTrue(replayed);self.assertEqual(first.pk,second.pk)
        self.assertEqual(ClinicDirectoryRevision.objects.count(),1)

    def test_stale_preview_cannot_overwrite_directory(self):
        self.publish()
        p=prepare_directory(actor=self.manager,fields=self.fields())
        self.publish(display_name='ADC口腔·长沙五一广场门店')
        with self.assertRaises(RuleError):confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(ClinicDirectoryRevision.objects.count(),2)

    def test_history_is_append_only(self):
        self.publish()
        with self.assertRaises(IntegrityError),transaction.atomic():
            ClinicDirectoryRevision.objects.update(snapshot={})
        with self.assertRaises(IntegrityError),transaction.atomic():
            ClinicDirectoryRevision.objects.all().delete()

    def test_withdraw_hides_branch_and_service_and_invalidates_old_booking(self):
        self.publish();token=self.preview()
        self.publish(is_published=False)
        self.assertEqual(self.public()['clinics'],[])
        self.assertEqual(self.public()['offerings'],[])
        self.assertEqual(Client().get(reverse('mini_public_service',args=[self.service.pk])).status_code,404)
        self.publish(is_published=True)
        response=self.post('mini_book_confirm',{'proposal_token':token,'confirmed':'on'})
        self.assertEqual(response.status_code,409)
        self.assertFalse(Visit.objects.exists())

    def test_profile_change_preserves_existing_booking_and_resource_claim(self):
        self.publish();visit=self.book()
        plan=visit.resource_plans.get(is_current=True)
        self.publish(display_name='ADC口腔·长沙梅溪湖中心门店')
        visit.refresh_from_db();plan.refresh_from_db()
        self.assertEqual(visit.status,'SCHEDULED')
        self.assertEqual(ResourceClaim.objects.filter(active=True).count(),1)
        self.assertEqual(plan.snapshot['public_clinic']['name'],'ADC口腔·长沙梅溪湖门店')
        detail=self.client.get(reverse('mini_visit',args=[visit.pk])).json()['data']
        self.assertEqual(detail['clinic'],'ADC口腔·长沙梅溪湖门店')

    def test_new_booking_forms_and_native_preview_use_the_published_contact(self):
        self.publish()
        r=self.client.get(reverse('portal_slots'),{'service':self.service.pk})
        self.assertContains(r,'ADC口腔·长沙梅溪湖门店');self.assertNotContains(r,self.a.name)
        r=self.client.get(reverse('portal_confirm'),dict(slot=self.slot1.pk,start=self.t.isoformat(),service=self.service.pk))
        self.assertContains(r,'ADC口腔·长沙梅溪湖门店');self.assertContains(r,'合成门址101号')
        self.assertNotContains(r,self.a.postal_address)
        rows=self.client.get(reverse('mini_candidates'),dict(clinic=self.a.pk,service=self.service.pk,day=self.t.date().isoformat())).json()['data']['rows']
        self.assertTrue(rows);self.assertEqual(rows[0]['clinic'],'ADC口腔·长沙梅溪湖门店')
        response=self.post('mini_book_preview',dict(slot=self.slot1.pk,service=self.service.pk,start=self.t.isoformat()))
        self.assertEqual(response.json()['data']['clinic'],'ADC口腔·长沙梅溪湖门店')
        self.assertFalse(Visit.objects.exists());self.assertFalse(Invoice.objects.exists())

    def test_pending_offer_keeps_its_promised_contact_after_public_update(self):
        from portal.mini_waitlist import offer_data
        self.publish();offer=self.offered()
        self.publish(display_name='ADC口腔·长沙梅溪湖中心门店')
        self.assertEqual(offer.public_contact['name'],'ADC口腔·长沙梅溪湖门店')
        self.assertEqual(offer_data(offer)['clinic'],'ADC口腔·长沙梅溪湖门店')
        self.assertFalse(Visit.objects.exists())

    def test_department_closure_changes_today_without_cancelling_booking(self):
        self.publish();visit=self.book()
        ResourceBlock.objects.create(clinic=self.a,department=self.department,starts_at=self.t-timedelta(hours=1),
            ends_at=self.t+timedelta(hours=10),reason='内部排程依据',public_notice='当日暂停接诊',recorded_by=self.manager)
        self.assertEqual(opening_data(self.a.pk,now=self.t)['state'],'CLOSED')
        self.assertEqual(opening_data(self.a.pk,now=self.t)['today'],'休息')
        visit.refresh_from_db();self.assertEqual(visit.status,'SCHEDULED')

    def test_other_open_department_keeps_branch_open(self):
        ResourceBlock.objects.create(clinic=self.a,department=self.department,starts_at=self.t-timedelta(hours=1),
            ends_at=self.t+timedelta(hours=8),reason='综合科暂停',recorded_by=self.manager)
        other=Department.objects.create(clinic=self.a,code='OTHER',name='其他科室')
        DepartmentHours.objects.create(department=other,weekday=self.t.weekday(),opens_at=time(8),closes_at=time(18))
        self.assertEqual(opening_data(self.a.pk,now=self.t)['state'],'OPEN')

    def test_internal_role_or_other_clinic_cannot_prepare_profile(self):
        for actor in (self.front,self.user,self.tech):
            with self.subTest(actor=actor.username),self.assertRaises(PermissionDenied):
                prepare_directory(actor=actor,fields=self.fields())
        RoleAssignment.objects.filter(user=self.manager).update(is_active=False)
        with self.assertRaises(PermissionDenied):prepare_directory(actor=self.manager,fields=self.fields())

    @override_settings(ADC_READ_ONLY=True)
    def test_direct_write_is_rejected_in_read_only_mode(self):
        p=prepare_directory(actor=self.manager,fields=self.fields())
        with self.assertRaises(PermissionDenied):
            confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(ClinicDirectory.objects.exists())

    def test_two_previews_race_one_version_wins(self):
        previews=[prepare_directory(actor=self.manager,fields=self.fields()) for _ in range(2)]
        def run(token):
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=self.manager.pk)
                actor._adc_workspace=WorkspaceContext.objects.get(pk=self.manager._adc_workspace.pk)
                try:confirm_directory(actor=actor,proposal_token=token,confirmed=True);return 'saved'
                except RuleError:return 'conflict'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(run,[p['proposal_token'] for p in previews]))
        self.assertCountEqual(results,['saved','conflict'])
        self.assertEqual(ClinicDirectoryRevision.objects.count(),1)

    def test_patient_login_selects_patient_even_with_employee_grant(self):
        RoleAssignment.objects.create(user=self.user,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        c=Client();r=c.post(reverse('portal_login'),{'username':self.user.username,'password':self.password})
        self.assertEqual(r.status_code,302)
        ctx=WorkspaceContext.objects.get(pk=c.session[SESSION_KEY])
        self.assertEqual((ctx.role,ctx.login_channel),('PATIENT','PATIENT'))
        r=c.post(reverse('activate_role'),{'role':'FRONT_DESK','workspace_token':token_for(ctx)})
        self.assertEqual(r.status_code,403)

    def test_staff_login_excludes_patient_role(self):
        RoleAssignment.objects.create(user=self.user,role='FRONT_DESK',scope_kind='CLINIC',clinic=self.a)
        c=Client();r=c.post(reverse('login'),{'username':self.user.username,'password':self.password})
        self.assertEqual(r.status_code,302)
        ctx=WorkspaceContext.objects.get(pk=c.session[SESSION_KEY])
        self.assertEqual((ctx.role,ctx.login_channel),('FRONT_DESK','STAFF'))
        self.assertEqual(c.post(reverse('activate_role'),{'role':'PATIENT','workspace_token':token_for(ctx)}).status_code,403)

    def test_wrong_channel_does_not_authenticate_or_create_context(self):
        for route,user in [('login',self.user),('portal_login',self.manager)]:
            user.set_password(self.password);user.save(update_fields=['password'])
            c=Client();before=WorkspaceContext.objects.count()
            r=c.post(reverse(route),{'username':user.username,'password':self.password})
            self.assertEqual(r.status_code,200)
            self.assertNotIn('_auth_user_id',c.session)
            self.assertEqual(WorkspaceContext.objects.count(),before)

    def test_database_rejects_patient_role_in_staff_channel(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            WorkspaceContext.objects.create(user=self.user,role='PATIENT',login_channel='STAFF')

    def test_web_guest_service_survives_explicit_delegate_selection(self):
        self.publish()
        user=UserAccount.objects.create_user(username='guest_delegate',password=self.password)
        case=self.make_case(user=user)
        c=Client();r=c.post(reverse('portal_login'),{'username':user.username,'password':self.password,
            'booking_service':self.service.pk})
        self.assertRedirects(r,reverse('portal_subjects'),fetch_redirect_response=False)
        self.assertIn('adc_booking_intent',c.session)
        self.assertContains(c.get(reverse('portal_subjects')),'继续预约')
        ctx=WorkspaceContext.objects.get(pk=c.session[SESSION_KEY])
        r=c.post(reverse('portal_subjects'),{'subject':f'grant:{case.appointment_grant.pk}','workspace_token':token_for(ctx)})
        self.assertRedirects(r,reverse('portal_slots')+'?service='+str(self.service.pk),fetch_redirect_response=False)
        self.assertNotIn('adc_booking_intent',c.session)
        self.assertFalse(Visit.objects.exists())

    def test_abandoning_service_choice_does_not_cancel_or_create_any_booking(self):
        user=UserAccount.objects.create_user(username='guest_abandon',password=self.password)
        self.make_case(user=user)
        c=Client();c.post(reverse('portal_login'),{'username':user.username,'password':self.password,
            'booking_service':self.service.pk})
        ctx=WorkspaceContext.objects.get(pk=c.session[SESSION_KEY])
        r=c.post(reverse('portal_subjects'),{'action':'cancel_intent','workspace_token':token_for(ctx)})
        self.assertEqual(r.status_code,302)
        self.assertNotIn('adc_booking_intent',c.session)
        self.assertFalse(Visit.objects.exists());self.assertFalse(ResourceClaim.objects.exists())
