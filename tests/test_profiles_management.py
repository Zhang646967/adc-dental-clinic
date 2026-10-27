"""P1 business boundaries on PostgreSQL; no provider or medical certification."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta,date
from decimal import Decimal
from io import BytesIO
from threading import Barrier
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction,DatabaseError,close_old_connections
from django.test import TransactionTestCase,Client,override_settings
from django.urls import reverse
from django.utils import timezone
from django.test.utils import CaptureQueriesContext
from django.db import connection
from PIL import Image
from accounts.models import UserAccount,RoleAssignment
from workspaces.models import WorkspaceContext
from tests.test_reception_resources import ResourceFixture
from tests.test_care_finance_equipment import CFEFixture,activate
from adc_core.rules import RuleError
from registry.profile_models import *
from registry import profile_services as ps
from finance import management_services as ms
from finance.management_models import CostMonth,MonthlyCost,ManagementReport,CostAllocation,ManagementAction,COST_CATEGORIES
from finance.management_selectors import monthly_report,monthly_facts,workload
from finance.management_policy import allocate_cost,ZERO
from scheduling.models import Visit,AvailabilitySlot
from scheduling.resource_models import ServicePresentation
from scheduling.service_content import draft_from_guide


class ProfileTests(ResourceFixture,TransactionTestCase):
    def setUp(self):
        self.resources()
        self.doc=UserAccount.objects.create_user(username='p1_doc',password='test-profile-pass',dentist=self.d1)
        RoleAssignment.objects.create(user=self.doc,role='DENTIST',scope_kind='SELF_DENTIST')
        activate(self.doc,'DENTIST')
        self.presentation=ServicePresentation.objects.create(service=self.service,
            **dict(draft_from_guide('CHECKUP'),title='综合口腔评估',is_published=True))
        from registry.branch_services import prepare_directory,confirm_directory
        p=prepare_directory(actor=self.manager,fields=dict(display_name='ADC口腔·长沙课程门店',province='湖南省',city='长沙',
            district='岳麓区',address='课程合成门址',entrance='合成接待入口',public_phone='000-0000-0010',
            latitude='28.18',longitude='112.90',map_latitude=None,map_longitude=None,
            coordinate_source='课程示意点',synthetic=True,is_published=True))
        confirm_directory(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    def fields(self,**changes):
        data=dict(title='主治医师',specialties=['CHECKUP'],summary='注重解释与持续口腔照护',biography='针对检查结果与患者讨论就诊安排。',
            practicing_since='2015-07-01',languages='普通话、英语',education='课程合成学习经历',
            credential_reference='PRIVATE_CREDENTIAL_SOURCE',media_ids='')
        data.update(changes);return data

    def submit(self,**changes):
        p=ps.prepare_profile(actor=self.doc,kind='dentist',action='SUBMIT',fields=self.fields(**changes))
        row,_=ps.confirm_profile(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        return row.submitted_version

    def affiliate(self,dentist=None,**changes):
        fields=dict(dentist_id=(dentist or self.d1).pk,kind='RESIDENT',starts_on=timezone.localdate().isoformat(),ends_on='')
        fields.update(changes)
        p=ps.prepare_affiliation(actor=self.manager,action='UPSERT',fields=fields)
        return ps.confirm_affiliation(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]

    def publish(self):
        version=self.submit();a=self.affiliate()
        p=ps.prepare_review(actor=self.manager,affiliation_id=a.pk,action='PUBLISH',version_id=version.pk)
        ps.confirm_review(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        return a

    def public(self):
        from portal.discovery import discovery_data
        return discovery_data()

    def test_draft_does_not_publish_or_grant(self):
        before=RoleAssignment.objects.count()
        version=self.submit()
        self.assertFalse(self.public()['dentists']);self.assertEqual(RoleAssignment.objects.count(),before)
        self.assertEqual(version.content['credential_status'],'UNVERIFIED')

    def test_doctor_submits_manager_publishes(self):
        self.publish();d=self.public()['dentists'][0]
        self.assertEqual(d['name'],self.d1.name);self.assertEqual(d['clinics'][0]['id'],self.a.pk)
        self.assertEqual(d['clinics'][0]['services'][0]['id'],self.service.pk)
        self.assertIn('CHECKUP',d['specialties'])

    def test_public_allowlist_excludes_home_contact_and_sources(self):
        self.publish();text=str(self.public())
        self.assertNotIn('PRIVATE_CREDENTIAL_SOURCE',text)
        self.assertNotIn('date_of_birth',text);self.assertNotIn('home_address',text)
        self.assertNotIn('uploaded_by',text)

    def test_doctor_cannot_publish(self):
        self.submit()
        with self.assertRaises(RuleError):ps.prepare_profile(actor=self.doc,kind='dentist',action='PUBLISH')

    def test_manager_cannot_edit_other_doctor_as_self(self):
        with self.assertRaises(PermissionDenied):ps.prepare_profile(actor=self.manager,kind='dentist',action='SUBMIT',fields=self.fields())

    def test_same_person_cannot_review_by_role_switch(self):
        version=self.submit();a=self.affiliate()
        RoleAssignment.objects.create(user=self.doc,role='MANAGER',scope_kind='CLINIC',clinic=self.a);activate(self.doc,'MANAGER',self.a)
        p=ps.prepare_review(actor=self.doc,affiliation_id=a.pk,action='PUBLISH',version_id=version.pk)
        with self.assertRaises(RuleError):ps.confirm_review(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)

    def test_new_draft_keeps_published_version(self):
        self.publish();before=self.public()['dentists'][0]['summary']
        self.submit(summary='尚待审核的新介绍')
        self.assertEqual(self.public()['dentists'][0]['summary'],before)

    def test_return_retains_old_publication(self):
        a=self.publish();version=self.submit(summary='新介绍待补充')
        p=ps.prepare_review(actor=self.manager,affiliation_id=a.pk,action='RETURN',version_id=version.pk,note='请补充经历来源')
        ps.confirm_review(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertNotEqual(self.public()['dentists'][0]['summary'],'新介绍待补充')
        self.assertTrue(ProfileAction.objects.filter(action='RETURN',note='请补充经历来源').exists())

    def test_withdraw_only_hides_introduction(self):
        a=self.publish();visit=self.booking()
        p=ps.prepare_review(actor=self.manager,affiliation_id=a.pk,action='WITHDRAW')
        ps.confirm_review(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(self.public()['dentists']);visit.refresh_from_db();self.assertEqual(visit.status,'SCHEDULED')

    def test_versions_are_database_immutable(self):
        version=self.submit()
        with self.assertRaises(DatabaseError),transaction.atomic():ProfileVersion.objects.filter(pk=version.pk).update(content={})

    def test_submission_replay_returns_original(self):
        p=ps.prepare_profile(actor=self.doc,kind='dentist',action='SUBMIT',fields=self.fields())
        for _ in range(2):ps.confirm_profile(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(ProfileVersion.objects.count(),1)

    def test_stale_draft_cannot_overwrite(self):
        p=ps.prepare_profile(actor=self.doc,kind='dentist',action='SUBMIT',fields=self.fields())
        self.submit(summary='已经提交另一个版本')
        with self.assertRaises(RuleError):ps.confirm_profile(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)

    def test_revoked_doctor_blocks_confirmation(self):
        p=ps.prepare_profile(actor=self.doc,kind='dentist',action='SUBMIT',fields=self.fields())
        RoleAssignment.objects.filter(user=self.doc).update(is_active=False)
        with self.assertRaises(PermissionDenied):ps.confirm_profile(actor=self.doc,proposal_token=p['proposal_token'],confirmed=True)

    def test_cross_clinic_review_rejected(self):
        a=self.publish();RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        activate(self.manager,'MANAGER',self.b)
        with self.assertRaises(DentistClinicAffiliation.DoesNotExist):ps.prepare_review(actor=self.manager,affiliation_id=a.pk,action='WITHDRAW')

    def test_roster_activation_checks_existing_shifts(self):
        self.affiliate()
        p=ps.prepare_affiliation(actor=self.manager,action='ACTIVATE')
        with self.assertRaises(RuleError):ps.confirm_affiliation(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    def enforce(self):
        self.affiliate();self.affiliate(self.d2)
        p=ps.prepare_affiliation(actor=self.manager,action='ACTIVATE')
        ps.confirm_affiliation(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    def test_ended_affiliation_blocks_new_booking_preserves_original(self):
        self.enforce();v=self.booking();a=DentistClinicAffiliation.objects.get(dentist=self.d1,clinic=self.a)
        p=ps.prepare_affiliation(actor=self.manager,action='END',affiliation_id=a.pk)
        ps.confirm_affiliation(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        with self.assertRaises(RuleError):self.booking(patient=self.p2,start=self.t+timedelta(hours=1))
        v.refresh_from_db();self.assertEqual(v.status,'SCHEDULED');self.assertEqual(Visit.objects.count(),1)

    def test_ended_affiliation_blocks_slot_creation(self):
        from scheduling.slot_creation import prepare_slot_creation,confirm_slot_creation
        self.enforce();a=DentistClinicAffiliation.objects.get(dentist=self.d1,clinic=self.a)
        p=ps.prepare_affiliation(actor=self.manager,action='END',affiliation_id=a.pk)
        ps.confirm_affiliation(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        p=prepare_slot_creation(actor=self.front,clinic_id=self.a.pk,dentist_id=self.d1.pk,start=self.t+timedelta(days=2),end=self.t+timedelta(days=2,hours=2))
        with self.assertRaises(RuleError):confirm_slot_creation(actor=self.front,proposal_token=p['proposal_token'],confirmed=True)

    def test_affiliation_date_is_checked_for_future_booking(self):
        self.enforce();a=DentistClinicAffiliation.objects.get(dentist=self.d1,clinic=self.a)
        a.ends_on=timezone.localdate();a.save()
        with self.assertRaises(RuleError):self.booking()

    def test_valid_same_room_parallel_still_works(self):
        self.enforce();self.booking();self.booking(patient=self.p2,slot=self.slot2)
        self.assertEqual(Visit.objects.count(),2)

    def test_multiple_clinics_preserve_one_dentist_identity(self):
        a=self.publish();RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        activate(self.manager,'MANAGER',self.b);b=self.affiliate(kind='VISITING')
        self.assertEqual(a.dentist_id,b.dentist_id)
        self.assertNotEqual(a.clinic_id,b.clinic_id)

    def test_clinic_search_and_detail_use_that_clinics_adopted_version(self):
        from portal.service_views import doctor_filter
        from portal.discovery_queries import doctor_listing_data
        first=self.publish();version=self.submit(summary='轮诊门店独立采用的复诊说明')
        RoleAssignment.objects.create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=self.b)
        activate(self.manager,'MANAGER',self.b);second=self.affiliate(kind='VISITING')
        from registry.branch_services import prepare_directory,confirm_directory
        from scheduling.resource_models import Department,DepartmentHours
        from datetime import time
        department=Department.objects.create(clinic=self.b,code='P15-HOURS',name='课程综合科')
        DepartmentHours.objects.create(department=department,weekday=self.t.weekday(),opens_at=time(8),closes_at=time(18))
        fields=dict(display_name='ADC口腔·同城轮诊门店',province='湖南省',city='长沙',district='课程区',
            address='课程合成门址',entrance='合成接待入口',public_phone='000-0000-0020',latitude=None,longitude=None,
            map_latitude=None,map_longitude=None,coordinate_source='课程示意点',synthetic=True,is_published=True)
        proposal=prepare_directory(actor=self.manager,fields=fields)
        confirm_directory(actor=self.manager,proposal_token=proposal['proposal_token'],confirmed=True)
        proposal=ps.prepare_review(actor=self.manager,affiliation_id=second.pk,action='PUBLISH',version_id=version.pk)
        ps.confirm_review(actor=self.manager,proposal_token=proposal['proposal_token'],confirmed=True)
        data=doctor_listing_data()
        rows=doctor_filter(data,{'clinic':str(self.b.pk),'q':'独立采用'})
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['summary'],version.content['summary'])
        self.assertEqual(doctor_filter(data,{'clinic':str(self.a.pk),'q':'独立采用'}),[])
        self.assertContains(Client().get(reverse('public_dentist_detail',args=[self.d1.pk]),{'clinic':self.b.pk}),version.content['summary'])

    def test_avatar_is_normalized_and_private_until_publication(self):
        out=BytesIO();Image.new('RGB',(120,150),'#bccfc1').save(out,'PNG')
        image=ps.upload_media(actor=self.doc,kind='dentist',uploaded=SimpleUploadedFile('avatar.png',out.getvalue()),alt_text='课程合成头像')
        self.assertEqual(Client().get(reverse('profile_media',args=[image.pk])).status_code,404)
        version=self.submit(media_ids=str(image.pk));a=self.affiliate()
        p=ps.prepare_review(actor=self.manager,affiliation_id=a.pk,action='PUBLISH',version_id=version.pk)
        ps.confirm_review(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        response=Client().get(reverse('profile_media',args=[image.pk]))
        self.assertEqual(response.status_code,200);self.assertEqual(response['Content-Type'],'image/jpeg')
        self.assertTrue(response.content.startswith(b'\xff\xd8'))

    def test_cannot_publish_another_profiles_media(self):
        other=PublicProfile.objects.create(clinic=self.a)
        image=ProfileMedia.objects.create(profile=other,image=b'x',digest='a'*64,width=1,height=1,alt_text='x',uploaded_by=self.manager)
        with self.assertRaises(RuleError):self.submit(media_ids=str(image.pk))

    def test_public_web_and_native_have_same_profile(self):
        a=self.publish()
        for name,args in [('public_dentists',[]),('public_dentist_detail',[self.d1.pk]),('public_clinic_detail',[self.a.pk])]:
            response=Client().get(reverse(name,args=args));self.assertEqual(response.status_code,200,response.content[:500])
            self.assertIn(self.d1.name,response.content.decode())
        response=Client().get(reverse('mini_public_dentist',args=[self.d1.pk]))
        self.assertEqual(response.json()['data']['id'],self.d1.pk)

    def test_public_reads_do_not_create_business_facts(self):
        self.publish();before=(Visit.objects.count(),ProfileAction.objects.count(),WorkspaceContext.objects.count())
        self.public();Client().get(reverse('public_dentists'))
        self.assertEqual(before,(Visit.objects.count(),ProfileAction.objects.count(),WorkspaceContext.objects.count()))

    def test_authenticated_patient_can_browse_public_profiles(self):
        from portal.models import PatientAccess
        self.publish();patient=UserAccount.objects.create_user(username='profile_patient',password='patient-test-pass')
        PatientAccess.objects.create(user=patient,patient=self.p1);self.client.force_login(patient)
        for name,args in [('public_dentists',[]),('public_dentist_detail',[self.d1.pk]),('public_clinic_detail',[self.a.pk])]:
            self.assertEqual(self.client.get(reverse(name,args=args)).status_code,200)

    def test_selected_doctor_survives_real_website_password_login(self):
        from portal.models import PatientAccess
        self.publish();patient=UserAccount.objects.create_user(username='profile_patient',password='patient-test-pass')
        PatientAccess.objects.create(user=patient,patient=self.p1);client=Client()
        client.get(reverse('portal_login')+f'?service={self.service.pk}&dentist={self.d1.pk}')
        response=client.post(reverse('portal_login'),{'username':patient.username,'password':'patient-test-pass',
            'booking_service':self.service.pk,'booking_dentist':self.d1.pk,'login_method':'password'})
        self.assertEqual(response.status_code,302,response.content[:500]);self.assertIn('dentist='+str(self.d1.pk),response.url)

    def test_draft_single_submit_has_idempotency_and_keeps_publication(self):
        self.publish();before=self.public()['dentists'][0]['summary'];token=ps.draft_token(self.doc,'dentist')
        for _ in range(2):ps.save_draft(actor=self.doc,token=token,fields=self.fields(summary='可编辑草稿'))
        self.assertEqual(ProfileAction.objects.filter(action='SAVE').count(),1)
        self.assertEqual(self.public()['dentists'][0]['summary'],before)

    def test_staff_http_draft_form_has_real_workspace_token(self):
        self.client.force_login(self.doc)
        response=self.client.get(reverse('profile_edit',args=['dentist']))
        self.assertEqual(response.status_code,200,response.content[:500])
        self.assertIn('name="workspace_token"',response.content.decode())
        self.assertIn('name="draft_token"',response.content.decode())

    def test_end_and_booking_race_retains_valid_single_effect(self):
        self.enforce();a=DentistClinicAffiliation.objects.get(clinic=self.a,dentist=self.d1)
        p=ps.prepare_affiliation(actor=self.manager,action='END',affiliation_id=a.pk);barrier=Barrier(2)
        def run(kind):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                if kind=='book':
                    try:return self.booking().pk
                    except RuleError:return None
                return ps.confirm_affiliation(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0].pk
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,['book','end']))
        self.assertLessEqual(Visit.objects.count(),1)
        with self.assertRaises(RuleError):self.booking(patient=self.p2,start=self.t+timedelta(hours=1))

    def test_profile_review_rejects_newer_submission(self):
        version=self.submit();a=self.affiliate()
        p=ps.prepare_review(actor=self.manager,affiliation_id=a.pk,action='PUBLISH',version_id=version.pk)
        self.submit(summary='医师刚提交的新说明')
        with self.assertRaises(RuleError):ps.confirm_review(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_cannot_submit(self):
        with self.assertRaises(PermissionDenied):self.submit()


class ManagementTests(CFEFixture,TransactionTestCase):
    def setUp(self):
        self.setup_cfe();self.year=self.today.year;self.month=self.today.month
        self.fin2=UserAccount.objects.create_user(username='p1_other_finance',password='test-other-finance')
        RoleAssignment.objects.create(user=self.fin2,role='FINANCE',scope_kind='CHAIN');activate(self.fin2,'FINANCE')

    def submit(self,amount='100.00',category='RENT',actor=None,clinic=None,reference=None,**extra):
        actor=actor or self.manager;clinic=self.a if clinic is None else clinic
        fields=dict(category=category,amount=amount,reference=reference or 'COST-'+str(MonthlyCost.objects.count()+1),basis='合成费用来源核实',dentist_id=None,equipment_event_id=None)
        replaces=extra.pop('replaces_id',None);fields.update(extra)
        p=ms.prepare_cost(actor=actor,year=self.year,month=self.month,clinic_id=clinic.pk,fields=fields,replaces_id=replaces)
        return ms.confirm_management(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0].cost

    def approve(self,cost,actor=None):
        actor=actor or self.fin
        p=ms.prepare_decision(actor=actor,cost_id=cost.pk,decision='APPROVED',note='独立核对合成费用')
        return ms.confirm_management(actor=actor,proposal_token=p['proposal_token'],confirmed=True)[0].cost

    def cover(self):
        period=CostMonth.objects.get(year=self.year,month=self.month,clinic=self.a)
        for category,_ in COST_CATEGORIES:
            amount=sum(ms.current_costs(period).filter(category=category).values_list('amount',flat=True),ZERO)
            p=ms.prepare_coverage(actor=self.fin,year=self.year,month=self.month,clinic_id=self.a.pk,
                category=category,state='COMPLETE' if amount else 'ZERO',note='本月合成费用完整核实')
            ms.confirm_management(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)

    def report(self):
        p=ms.prepare_report(actor=self.fin,year=self.year,month=self.month,clinic_id=self.a.pk)
        return ms.confirm_management(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0].report

    def test_cost_submission_is_not_money_or_profit(self):
        from finance.cash_models import CashEntry
        c=self.submit();facts=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertFalse(facts['ready']);self.assertIsNone(facts['profit']);self.assertEqual(facts['confirmed_cost'],'0.00')
        self.assertFalse(CashEntry.objects.exists())

    def test_independent_review_required(self):
        c=self.submit(actor=self.fin)
        with self.assertRaises(RuleError):self.approve(c)
        self.approve(c,self.fin2)

    def test_same_account_multi_role_cannot_self_review(self):
        c=self.submit();RoleAssignment.objects.create(user=self.manager,role='FINANCE',scope_kind='CHAIN');activate(self.manager,'FINANCE')
        with self.assertRaises(RuleError):self.approve(c,self.manager)

    def test_cross_clinic_manager_cannot_submit(self):
        with self.assertRaises(PermissionDenied):self.submit(clinic=self.b)

    def test_missing_and_zero_are_distinct(self):
        self.approve(self.submit());facts=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertFalse(facts['ready']);self.cover();facts=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertTrue(facts['ready']);self.assertEqual(facts['profit'],'-100.00')

    def test_pending_cost_blocks_coverage(self):
        self.submit();
        p=ms.prepare_coverage(actor=self.fin,year=self.year,month=self.month,clinic_id=self.a.pk,category='RENT',state='ZERO',note='待核实')
        with self.assertRaises(RuleError):ms.confirm_management(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)

    def test_nonzero_category_cannot_be_zero(self):
        self.approve(self.submit())
        p=ms.prepare_coverage(actor=self.fin,year=self.year,month=self.month,clinic_id=self.a.pk,category='RENT',state='ZERO',note='错误零值')
        with self.assertRaises(RuleError):ms.confirm_management(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)

    def test_new_cost_invalidates_previous_coverage(self):
        self.approve(self.submit());self.cover();self.approve(self.submit(amount='5.00'))
        self.assertFalse(monthly_report(self.manager,self.year,self.month,self.a.pk)['ready'])

    def test_duplicate_source_is_rejected(self):
        self.submit(reference='SAME')
        with self.assertRaises(RuleError):self.submit(reference='SAME')

    def test_correction_retains_original_and_counts_once(self):
        old=self.approve(self.submit());new=self.approve(self.submit(amount='80.00',replaces_id=old.pk))
        old.refresh_from_db();self.assertEqual(old.amount,Decimal('100.00'))
        facts=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertEqual(facts['confirmed_cost'],'80.00');self.assertEqual(MonthlyCost.objects.count(),2)

    def test_cost_history_database_guard(self):
        c=self.approve(self.submit())
        with self.assertRaises(DatabaseError),transaction.atomic():MonthlyCost.objects.filter(pk=c.pk).update(amount=1)

    def test_month_report_retains_snapshot_and_allocations(self):
        self.approve(self.submit());self.cover();r=self.report()
        self.assertEqual(r.snapshot['confirmed_cost'],'100.00')
        self.assertEqual(CostAllocation.objects.filter(report=r).count(),len(r.snapshot['allocations']))
        self.assertEqual(sum((x.shared_cost for x in r.allocations.all()),ZERO)+Decimal(r.snapshot['unallocated']),Decimal('100.00'))

    def test_month_report_is_database_immutable(self):
        self.approve(self.submit());self.cover();r=self.report()
        with self.assertRaises(DatabaseError),transaction.atomic():ManagementReport.objects.filter(pk=r.pk).update(snapshot={})

    def test_stale_report_preview_rejected(self):
        self.approve(self.submit());self.cover()
        p=ms.prepare_report(actor=self.fin,year=self.year,month=self.month,clinic_id=self.a.pk)
        self.approve(self.submit(amount='5.00'));self.cover()
        with self.assertRaises(RuleError):ms.confirm_management(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)

    def test_revised_report_keeps_previous(self):
        self.approve(self.submit());self.cover();old=self.report()
        self.approve(self.submit(amount='9.00'));self.cover();new=self.report()
        self.assertEqual(new.sequence,2);self.assertNotEqual(new.digest,old.digest)
        old.refresh_from_db();self.assertEqual(old.snapshot['confirmed_cost'],'100.00')

    def test_submission_replay_has_one_cost(self):
        fields=dict(category='RENT',amount='1.00',reference='REPLAY',basis='同一来源明确重试')
        p=ms.prepare_cost(actor=self.manager,year=self.year,month=self.month,clinic_id=self.a.pk,fields=fields)
        for _ in range(2):ms.confirm_management(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertEqual(MonthlyCost.objects.count(),1)

    def test_revoked_grant_cannot_confirm_cost(self):
        p=ms.prepare_cost(actor=self.manager,year=self.year,month=self.month,clinic_id=self.a.pk,
            fields=dict(category='RENT',amount='1.00',reference='REVOKE',basis='合成依据'))
        RoleAssignment.objects.filter(user=self.manager,role='MANAGER').update(is_active=False)
        with self.assertRaises(PermissionDenied):ms.confirm_management(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    def test_frontdesk_has_workload_without_financial_projection(self):
        facts=monthly_report(self.front,self.year,self.month,self.a.pk)
        for key in ('profit','production','confirmed_cost','categories','source','allocations'):self.assertNotIn(key,facts)
        self.assertIn('shift_minutes',workload(self.front,self.year,self.month,self.a.pk))

    def test_doctor_projection_only_contains_self(self):
        self.approve(self.submit(dentist_id=self.d1.pk));self.cover()
        facts=monthly_report(self.doctor,self.year,self.month,self.a.pk)
        self.assertTrue(all(r['dentist']==self.d1.pk for r in facts['allocations']))
        for hidden in ('source','categories','retained_reports','shared_cost'):self.assertNotIn(hidden,facts)

    def test_doctor_http_monthly_page_uses_clinic_association(self):
        from tests.workspace_client import WorkspaceClient
        c=WorkspaceClient();c.force_login(self.doctor)
        response=c.get('/operations/management/?clinic='+str(self.a.pk))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'本人汇总')
        self.assertNotContains(response,'成本提交与复核记录')

    def test_concurrent_same_cost_confirmation_has_one_effect(self):
        p=ms.prepare_cost(actor=self.manager,year=self.year,month=self.month,clinic_id=self.a.pk,
            fields=dict(category='RENT',amount='13.00',reference='CONCURRENT',basis='同一费用并发重试'))
        uid=self.manager.pk;ctx=self.manager._adc_workspace.pk;barrier=Barrier(2)
        def submit():
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=uid);actor._adc_workspace=WorkspaceContext.objects.get(pk=ctx)
                barrier.wait(timeout=10)
                event,replay=ms.confirm_management(actor=actor,proposal_token=p['proposal_token'],confirmed=True)
                return event.cost_id,replay
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:answers=list(pool.map(lambda _:submit(),range(2)))
        self.assertEqual(len({x[0] for x in answers}),1)
        self.assertEqual(sorted(x[1] for x in answers),[False,True])
        self.assertEqual(MonthlyCost.objects.filter(reference='CONCURRENT').count(),1)

    def test_latest_bill_revision_changes_production_and_retains_old_report(self):
        from care.corrections import review_correction
        v,invoice,request=self.correction();self.approve(self.submit());self.cover();old=self.report()
        review_correction(actor=self.fin,request_id=request.pk,decision='approve',reason='独立核对治疗数量')
        new=self.report();old.refresh_from_db()
        self.assertEqual(Decimal(old.snapshot['production']),Decimal('199.98'))
        self.assertEqual(Decimal(new.snapshot['production']),Decimal('99.99'))
        self.assertEqual(new.sequence,old.sequence+1)

    def test_cross_month_receipt_and_refund_use_cash_business_date(self):
        from datetime import datetime,time
        v,invoice=self.billed()
        next_month=(date(self.year,self.month,1)+timedelta(days=32)).replace(day=1)
        first=self.cash(invoice,amount=Decimal('40.00'));self.approve_cash(first)
        clock=timezone.make_aware(datetime.combine(next_month,time(12)))
        with patch('django.utils.timezone.now',return_value=clock):
            refund=self.cash(invoice,kind='REFUND',amount=Decimal('10.00'),occurred_on=next_month);self.approve_cash(refund)
        present=monthly_report(self.manager,self.year,self.month,self.a.pk)
        later=monthly_report(self.manager,next_month.year,next_month.month,self.a.pk)
        self.assertEqual(present['patient_net'],'40.00');self.assertEqual(later['patient_net'],'-10.00')
        self.assertEqual(Decimal(present['production']),invoice.current_record_version.total_amount)
        self.assertEqual(Decimal(later['production']),ZERO)

    def test_hq_and_technical_cannot_write(self):
        for actor in (self.hq,self.tech,self.pa):
            with self.subTest(actor=actor.username),self.assertRaises(PermissionDenied):self.submit(actor=actor)

    def test_zero_shift_keeps_unallocated_cost(self):
        self.approve(self.submit());AvailabilitySlot.objects.all().update(is_active=False);self.cover()
        facts=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertEqual(facts['unallocated'],'100.00');self.assertEqual(facts['profit'],'-100.00')

    def test_intake_pause_is_still_published_shift_time(self):
        before=workload(self.front,self.year,self.month,self.a.pk)['shift_minutes']
        AvailabilitySlot.objects.filter(clinic=self.a).update(booking_paused=True)
        self.assertEqual(before,workload(self.front,self.year,self.month,self.a.pk)['shift_minutes'])

    def test_purchase_cost_cannot_be_maintenance(self):
        a=self.asset();event=a.events.get(sequence=0)
        with self.assertRaises(RuleError):self.submit(category='MAINTENANCE',amount='500.00',equipment_event_id=event.pk)

    def test_equipment_source_can_only_be_counted_once(self):
        a=self.asset();self.change(a);self.change(a,kind='SERVICE',cost=Decimal('20.00'));event=a.events.order_by('-sequence').first()
        self.approve(self.submit(category='MAINTENANCE',amount='20.00',equipment_event_id=event.pk))
        self.month=1 if self.month!=1 else 2
        with self.assertRaises(RuleError):self.submit(category='MAINTENANCE',amount='20.00',equipment_event_id=event.pk)

    def test_changed_equipment_source_requires_reviewed_cost_revision(self):
        from equipment import costs as equipment_costs
        asset=self.asset();self.change(asset);self.change(asset,kind='SERVICE',cost=Decimal('20.00'))
        event=asset.events.order_by('-sequence').first()
        old=self.approve(self.submit(category='MAINTENANCE',amount='20.00',equipment_event_id=event.pk));self.cover()
        retained=self.report()
        p=equipment_costs.prepare_cost(actor=self.manager,event_id=event.pk,proposed_cost='25.00',reason='合成保养凭据补充')
        amendment=equipment_costs.confirm_cost(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)[0]
        p=equipment_costs.prepare_cost_review(actor=self.fin,amendment_id=amendment.pk,decision='approve',reason='独立核对来源修订')
        equipment_costs.confirm_cost_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)
        changed=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertFalse(changed['ready']);self.assertEqual(changed['changed_cost_sources'],[old.pk])
        self.approve(self.submit(category='MAINTENANCE',amount='25.00',equipment_event_id=event.pk,replaces_id=old.pk));self.cover()
        latest=self.report();retained.refresh_from_db()
        self.assertEqual(retained.snapshot['confirmed_cost'],'20.00');self.assertEqual(latest.snapshot['confirmed_cost'],'25.00')

    def test_concurrent_cross_month_equipment_source_has_one_cost(self):
        asset=self.asset();self.change(asset);self.change(asset,kind='SERVICE',cost=Decimal('20.00'))
        event=asset.events.order_by('-sequence').first();next_month=1 if self.month!=1 else 2
        previews=[]
        for actor,month in ((self.manager,self.month),(self.fin,next_month)):
            p=ms.prepare_cost(actor=actor,year=self.year,month=month,clinic_id=self.a.pk,fields=dict(category='MAINTENANCE',
                amount='20.00',equipment_event_id=event.pk,reference='RACE-'+str(month),basis='同一保养来源跨月竞争'))
            previews.append((actor.pk,actor._adc_workspace.pk,p['proposal_token']))
        barrier=Barrier(2)
        def submit(spec):
            close_old_connections()
            try:
                actor=UserAccount.objects.get(pk=spec[0]);actor._adc_workspace=WorkspaceContext.objects.get(pk=spec[1]);barrier.wait(timeout=10)
                try:ms.confirm_management(actor=actor,proposal_token=spec[2],confirmed=True);return 'saved'
                except RuleError:return 'rejected'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:answers=list(pool.map(submit,previews))
        self.assertCountEqual(answers,['saved','rejected'])
        self.assertEqual(MonthlyCost.objects.filter(equipment_event=event).count(),1)

    def test_completed_bill_and_two_cash_receipts_not_double_revenue(self):
        v,invoice=self.billed();self.approve(self.submit());self.cover()
        first=self.cash(invoice,amount=Decimal('10.00'));self.approve_cash(first)
        second=self.cash(invoice,amount=Decimal('20.00'));self.approve_cash(second)
        facts=monthly_report(self.manager,self.year,self.month,self.a.pk)
        self.assertEqual(Decimal(facts['production']),invoice.current_record_version.total_amount)
        self.assertEqual(facts['patient_net'],'30.00')

    def approve_cash(self,entry):
        from finance.cash_services import prepare_review,confirm_cash_review
        p=prepare_review(actor=self.fin,entry_id=entry.pk,decision='approve',reason='独立核对合成款项')
        return confirm_cash_review(actor=self.fin,proposal_token=p['proposal_token'],confirmed=True)[0]

    def test_zero_denominator_load_is_unknown(self):
        AvailabilitySlot.objects.all().update(is_active=False)
        self.assertIsNone(workload(self.front,self.year,self.month,self.a.pk)['load_percent'])

    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_no_cost_write(self):
        with self.assertRaises(PermissionDenied):self.submit()


class AllocationPolicyTests(TransactionTestCase):
    def test_fen_conservation_and_employee_order(self):
        parts,left=allocate_cost('0.02',{'D3':1,'D1':1,'D2':1})
        self.assertEqual(parts,{'D3':ZERO,'D1':Decimal('.01'),'D2':Decimal('.01')});self.assertEqual(left,ZERO)

    def test_many_amounts_and_work_distributions_conserve(self):
        for cents in (0,1,2,99,10001,10000003):
            for minutes in ({'A':0,'B':0},{'A':1,'B':3,'C':7},{'A':0,'B':1}):
                amount=Decimal(cents)/100;parts,left=allocate_cost(amount,minutes)
                self.assertEqual(sum(parts.values(),ZERO)+left,amount)
                self.assertTrue(all(v>=0 for v in parts.values()))
