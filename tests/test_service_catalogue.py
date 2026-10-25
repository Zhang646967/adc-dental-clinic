"""Service publishing, public discovery and booking: PostgreSQL/HTTP acceptance.

Authored with the product slice; execution status is tracked in C0_SERVICE_RELEASE.md.
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.db import transaction, IntegrityError
from django.test import TransactionTestCase, RequestFactory
from django.core import signing
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from portal.models import PatientAccess, BookingReceipt
from portal.forms import SlotFilterForm
from portal.booking_intent import destination_after_activation
from portal.booking_intent_rules import INTENT_KEY, INTENT_SALT, INTENT_SECONDS
from portal.service_catalogue import public_profiles
from portal.services import preview_booking, confirm_booking, public_options
from scheduling.models import Visit
from scheduling.resource_models import ServicePresentation, BookingService, ResourceAction
from scheduling.resource_config import prepare_config, confirm_config
from scheduling.service_content import CONTENT_LIMITS
from tests.test_reception_resources import ResourceFixture
from adc_core.rules import RuleError
from workspaces.context import SESSION_KEY
from workspaces.models import WorkspaceContext


class ServiceCatalogueTests(ResourceFixture, TransactionTestCase):
    def setUp(self):
        self.resources()
        self.patient_user=UserAccount.objects.create_user(username='service_patient',password='synthetic-service-only')
        PatientAccess.objects.create(user=self.patient_user,patient=self.p2)
        self.patient_user._adc_workspace=WorkspaceContext.objects.create(user=self.patient_user,role='PATIENT')
        self.profile=self.presentation()

    def fields(self,**changes):
        fields={key:'已核对的本店服务内容' for key in CONTENT_LIMITS}
        fields.update(service=self.service.pk,category='CHECKUP',title='口腔初诊与需求评估',
            fee_mode='ASSESSED',fee_amount='',is_published=True)
        return dict(fields,**changes)

    def presentation(self,**changes):
        fields=self.fields(**changes)
        p=prepare_config(actor=self.manager,kind='service_profile',fields=fields)
        action,_=confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        return ServicePresentation.objects.get(pk=action.result['id'])

    def change(self,**changes):
        fields={key:getattr(self.profile,key) for key in (*CONTENT_LIMITS,'category','fee_mode','fee_amount','is_published')}
        fields['service']=self.service.pk;fields.update(changes)
        p=prepare_config(actor=self.manager,kind='service_profile',target=self.profile.pk,fields=fields)
        return confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    def login_patient(self):
        self.client.force_login(self.patient_user)

    def test_public_home_root_and_legacy_entry_are_patient_pages(self):
        for route in ('public_home','system_entry'):
            response=self.client.get(reverse(route))
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'口腔初诊与需求评估')
            self.assertNotContains(response,'业务核验路线')

    def test_browsing_does_not_create_bookings_or_workspaces(self):
        before=WorkspaceContext.objects.count()
        for route,args in [('public_services',[]),('public_service_detail',[self.service.pk]),
                           ('public_service_guide',['CHECKUP']),('public_clinics',[])]:
            self.assertEqual(self.client.get(reverse(route,args=args)).status_code,200)
        self.assertEqual(WorkspaceContext.objects.count(),before)
        self.assertFalse(Visit.objects.exists())
        self.assertFalse(BookingReceipt.objects.exists())

    def test_detail_has_content_preparation_fee_and_only_public_clinician_fields(self):
        self.d1.home_address='PRIVATE-HOME-DO-NOT-PUBLISH';self.d1.phone='PRIVATE-PHONE';self.d1.save()
        response=self.client.get(reverse('public_service_detail',args=[self.service.pk]))
        for text in ('适合什么需求','这次预约包含什么','到诊前','费用与包含范围',self.d1.name,self.a.postal_address):
            self.assertContains(response,text)
        self.assertNotContains(response,'PRIVATE-HOME-DO-NOT-PUBLISH')
        self.assertNotContains(response,'PRIVATE-PHONE')
        self.assertNotContains(response,self.p2.patient_no)

    def test_draft_and_incomplete_imports_cannot_be_published(self):
        self.change(is_published=False)
        self.assertEqual(public_profiles(),[])
        self.assertEqual(self.client.get(reverse('public_service_detail',args=[self.service.pk])).status_code,404)
        ServicePresentation.objects.filter(pk=self.profile.pk).update(is_published=True,summary=' ')
        self.assertEqual(public_profiles(),[])

    def test_complete_content_required_before_publication(self):
        for field in CONTENT_LIMITS:
            with self.subTest(field=field),self.assertRaises(RuleError):
                fields=self.fields();fields[field]=' '
                prepare_config(actor=self.manager,kind='service_profile',target=self.profile.pk,fields=fields)

    def test_service_retirement_and_disabled_clinic_or_dentists_hide_public_content(self):
        self.service.is_active=False;self.service.save()
        self.assertEqual(public_profiles(),[])
        self.service.is_active=True;self.service.save()
        self.service.dentists.clear()
        self.assertEqual(public_profiles(),[])

    def test_preparing_policy_hides_offering_without_cancelling_existing_facts(self):
        self.policy.state='PREPARING';self.policy.save()
        self.assertEqual(public_profiles(),[])
        self.assertFalse(Visit.objects.exists())

    def test_fee_modes_keep_unknown_zero_and_starting_price_distinct(self):
        self.change(fee_mode='FIXED',fee_amount=Decimal('0.00'))
        self.profile.refresh_from_db();self.assertEqual(self.profile.fee_display,'¥0.00 / 本次服务')
        self.change(fee_mode='FROM',fee_amount=Decimal('100.50'))
        self.profile.refresh_from_db();self.assertEqual(self.profile.fee_display,'¥100.50 起')
        self.change(fee_mode='ASSESSED',fee_amount='')
        self.profile.refresh_from_db();self.assertIsNone(self.profile.fee_amount)

    def test_database_rejects_ambiguous_fee_or_missing_fixed_fee(self):
        for mode,amount in [('ASSESSED',Decimal('0')),('FIXED',None),('FROM',Decimal('-1'))]:
            with self.subTest(mode=mode),self.assertRaises(IntegrityError),transaction.atomic():
                ServicePresentation.objects.filter(pk=self.profile.pk).update(fee_mode=mode,fee_amount=amount)

    def test_publication_confirmation_is_idempotent_and_retains_audit_action(self):
        fields=self.fields(title='更新后的患者名称')
        p=prepare_config(actor=self.manager,kind='service_profile',target=self.profile.pk,fields=fields)
        a,replay=confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        b,replay2=confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)
        self.assertFalse(replay);self.assertTrue(replay2);self.assertEqual(a.pk,b.pk)
        self.assertEqual(ResourceAction.objects.filter(pk=a.pk,kind='service_profile').count(),1)

    def test_stale_publication_preview_requires_reconfirmation(self):
        p=prepare_config(actor=self.manager,kind='service_profile',target=self.profile.pk,fields=self.fields(title='旧预览'))
        self.change(title='先保存的新内容')
        with self.assertRaises(RuleError):confirm_config(actor=self.manager,proposal_token=p['proposal_token'],confirmed=True)

    def test_service_identity_cannot_be_repointed_to_another_appointment_type(self):
        other=BookingService.objects.create(department=self.department,code='OTHER',name='另一服务')
        other.dentists.set([self.d1])
        with self.assertRaisesRegex(RuleError,'对应服务保持不变'):
            prepare_config(actor=self.manager,kind='service_profile',target=self.profile.pk,fields=self.fields(service=other.pk))

    def test_publication_cannot_accept_another_clinic_service(self):
        from scheduling.resource_models import Department
        other=BookingService.objects.create(department=Department.objects.create(clinic=self.b,code='B',name='另一店'),
                                            code='OTHER',name='另一店服务')
        with self.assertRaises(RuleError):
            prepare_config(actor=self.manager,kind='service_profile',fields=self.fields(service=other.pk))

    def test_public_copy_is_escaped_and_query_parameters_are_not_destinations(self):
        self.change(summary='<script>alert(1)</script>')
        response=self.client.get(reverse('public_service_detail',args=[self.service.pk]),{'next':'https://evil.invalid'})
        self.assertContains(response,'&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertNotContains(response,'evil.invalid')

    def test_only_published_service_compatible_dentists_can_filter(self):
        self.service.dentists.set([self.d1])
        form=SlotFilterForm({'service':self.service.pk,'dentist':self.d2.pk})
        self.assertFalse(form.is_valid());self.assertIn('dentist',form.errors)
        form=SlotFilterForm({'service':self.service.pk,'dentist':self.d1.pk})
        self.assertTrue(form.is_valid(),form.errors)

    def test_blank_day_search_finds_tomorrow_and_retains_actual_service(self):
        with patch('portal.services.timezone.localdate',return_value=self.t.date()-timedelta(days=1)):
            rows=public_options(self.patient_user,service_id=self.service.pk)
        self.assertTrue(rows)
        self.assertTrue(all(row['service'].pk==self.service.pk for row in rows))

    def test_booking_receives_patient_request_and_replay_does_not_overwrite(self):
        _,_,token=preview_booking(user=self.patient_user,slot_id=self.slot2.pk,start=self.t,service_id=self.service.pk)
        visit=confirm_booking(actor=self.patient_user,token=token,patient_request='想了解这次牙齿不适的原因')
        self.assertEqual(visit.patient_id,self.p2.pk)
        self.assertEqual(visit.chief_complaint,'想了解这次牙齿不适的原因')
        replay=confirm_booking(actor=self.patient_user,token=token,patient_request='重复请求修改主诉')
        self.assertEqual(replay.pk,visit.pk)
        visit.refresh_from_db();self.assertEqual(visit.chief_complaint,'想了解这次牙齿不适的原因')

    def test_invalid_patient_request_creates_no_booking(self):
        _,_,token=preview_booking(user=self.patient_user,slot_id=self.slot2.pk,start=self.t,service_id=self.service.pk)
        with self.assertRaises(RuleError):confirm_booking(actor=self.patient_user,token=token,patient_request='字'*501)
        self.assertFalse(Visit.objects.exists());self.assertFalse(BookingReceipt.objects.exists())

    def test_public_login_retains_typed_service_after_normal_patient_activation(self):
        response=self.client.post(reverse('portal_login'),{'username':self.patient_user.username,
            'password':'synthetic-service-only','booking_service':self.service.pk,'next':'https://evil.invalid'})
        self.assertRedirects(response,reverse('portal_slots')+'?service='+str(self.service.pk),fetch_redirect_response=False)
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        self.assertEqual(ctx.role,'PATIENT');self.assertIsNone(ctx.clinic_id)

    def test_unauthorized_login_hint_cannot_choose_a_staff_role_or_url(self):
        response=self.client.post(reverse('portal_login'),{'username':self.patient_user.username,
            'password':'synthetic-service-only','booking_service':'https://evil.invalid','role':'SYSADMIN','clinic':self.b.pk})
        self.assertRedirects(response,reverse('portal_home'),fetch_redirect_response=False)

    def test_children_service_uses_verified_frontdesk_path(self):
        self.change(category='CHILDREN')
        response=self.client.get(reverse('public_service_detail',args=[self.service.pk]))
        self.assertContains(response,'核验监护')
        self.assertNotContains(response,'登录并选择时间')
        self.assertFalse(SlotFilterForm({'service':self.service.pk}).is_valid())

    def test_patient_can_read_service_choose_time_and_confirm_own_request(self):
        self.login_patient()
        response=self.client.get(reverse('portal_slots'),{'service':self.service.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.profile.title)
        response=self.client.get(reverse('portal_confirm'),{'service':self.service.pk,'slot':self.slot2.pk,
            'start':self.t.isoformat()})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'费用')
        token=response.context['form'].initial['token']
        response=self.client.post(reverse('portal_confirm'),{'token':token,'confirmed':True,
            'patient_request':'牙齿不舒服，希望检查一下','patient_id':self.p1.pk,'fee_amount':'0'})
        visit=Visit.objects.get()
        self.assertRedirects(response,reverse('portal_visit',args=[visit.pk]),fetch_redirect_response=False)
        self.assertEqual(visit.patient_id,self.p2.pk)
        self.assertEqual(visit.chief_complaint,'牙齿不舒服，希望检查一下')
        self.assertEqual(visit.resource_plans.get(is_current=True).service_id,self.service.pk)
        self.assertFalse(hasattr(visit,'fee_amount'))
        self.assertContains(self.client.get(reverse('portal_visit',args=[visit.pk])),'牙齿不舒服，希望检查一下')

    def test_availability_rule_failure_is_not_presented_as_no_slots(self):
        self.login_patient()
        with patch('portal.views.public_options',side_effect=RuleError('接诊配置已更新，请重试。')):
            response=self.client.get(reverse('portal_slots'),{'service':self.service.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'查询未完成')
        self.assertContains(response,'接诊配置已更新')
        self.assertNotContains(response,'这次查询暂无合适时段')

    def test_patient_cannot_open_or_write_service_publishing_screen(self):
        self.login_patient()
        url=reverse('resource_config',args=['service_profile'])
        self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.post(url,self.fields(title='恶意改写')).status_code,403)
        self.profile.refresh_from_db();self.assertEqual(self.profile.title,'口腔初诊与需求评估')

    def test_invalid_public_filters_and_private_ids_return_404(self):
        for query in ({'category':'unknown'},{'clinic':'https://evil.invalid'},{'clinic':self.b.pk}):
            self.assertEqual(self.client.get(reverse('public_services'),query).status_code,404)
        self.assertEqual(self.client.get(reverse('public_service_detail',args=[999999])).status_code,404)

    def test_browser_filter_rejects_other_clinic_and_past_date(self):
        self.assertFalse(SlotFilterForm({'service':self.service.pk,'clinic':self.b.pk}).is_valid())
        self.assertFalse(SlotFilterForm({'service':self.service.pk,'day':(timezone.localdate()-timedelta(days=1)).isoformat()}).is_valid())

    def test_authenticated_public_discovery_leaves_workspace_unchanged(self):
        self.login_patient()
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        before=(ctx.role,ctx.clinic_id,ctx.revision)
        self.client.get(reverse('public_services'),{'role':'MANAGER','clinic':self.a.pk})
        ctx.refresh_from_db()
        self.assertEqual((ctx.role,ctx.clinic_id,ctx.revision),before)

    def add_manager_role(self):
        RoleAssignment.objects.create(user=self.patient_user,role='MANAGER',scope_kind='CLINIC',clinic=self.a)

    def login_with_selection(self):
        return self.client.post(reverse('portal_login'),{'username':self.patient_user.username,
            'password':'synthetic-service-only','booking_service':self.service.pk})

    def intent_request(self,**payload_changes):
        request=RequestFactory().get('/')
        request.user=self.patient_user;request.workspace=self.patient_user._adc_workspace
        payload={'uid':self.patient_user.pk,'workspace':str(request.workspace.pk),'service':self.service.pk}
        payload.update(payload_changes)
        request.session={INTENT_KEY:signing.dumps(payload,salt=INTENT_SALT)}
        return request

    def test_multi_role_patient_channel_continues_exact_service_without_staff_selection(self):
        self.add_manager_role()
        response=self.login_with_selection()
        self.assertRedirects(response,reverse('portal_slots')+'?service='+str(self.service.pk),fetch_redirect_response=False)
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        self.assertEqual((ctx.role,ctx.login_channel),('PATIENT','PATIENT'));self.assertIsNone(ctx.clinic_id)
        self.assertNotIn(INTENT_KEY,self.client.session)
        self.assertFalse(Visit.objects.exists())

    def test_patient_channel_rejects_staff_selection_without_changing_scope(self):
        self.add_manager_role();self.login_with_selection()
        response=self.client.post(reverse('activate_role'),{'role':'MANAGER','clinic':self.b.pk})
        self.assertEqual(response.status_code,403)
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        self.assertEqual(ctx.role,'PATIENT');self.assertIsNone(ctx.clinic_id)
        self.assertNotIn(INTENT_KEY,self.client.session)

    def test_new_login_clears_previous_pending_patient_selection(self):
        self.add_manager_role();self.login_with_selection()
        old=self.client.session[SESSION_KEY]
        session=self.client.session;session[INTENT_KEY]='previous-pending-choice';session.save()
        response=self.client.post(reverse('login'),{'username':self.patient_user.username,'password':'synthetic-service-only'})
        self.assertRedirects(response,reverse('manager_home'),fetch_redirect_response=False)
        self.assertNotIn(INTENT_KEY,self.client.session)
        self.assertNotEqual(old,self.client.session[SESSION_KEY])
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        self.assertEqual((ctx.role,ctx.login_channel),('MANAGER','STAFF'))
        response=self.client.post(reverse('activate_role'),{'role':'PATIENT'})
        self.assertEqual(response.status_code,403)

    def test_already_active_patient_continues_without_get_activating_anything(self):
        self.login_patient()
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        before=(WorkspaceContext.objects.count(),ctx.role,ctx.clinic_id,ctx.revision)
        response=self.client.get(reverse('portal_login'),{'service':self.service.pk})
        self.assertRedirects(response,reverse('portal_slots')+'?service='+str(self.service.pk),fetch_redirect_response=False)
        ctx.refresh_from_db()
        self.assertEqual((WorkspaceContext.objects.count(),ctx.role,ctx.clinic_id,ctx.revision),before)

    def test_staff_service_link_never_activates_patient_on_get(self):
        self.client.force_login(self.manager)
        ctx=WorkspaceContext.objects.get(pk=self.client.session[SESSION_KEY])
        before=(WorkspaceContext.objects.count(),ctx.role,ctx.clinic_id,ctx.revision)
        response=self.client.get(reverse('portal_login'),{'service':self.service.pk})
        self.assertEqual(response.status_code,200);self.assertContains(response,self.profile.title)
        ctx.refresh_from_db()
        self.assertEqual((WorkspaceContext.objects.count(),ctx.role,ctx.clinic_id,ctx.revision),before)

    def test_expired_selection_returns_to_patient_home_without_booking(self):
        from time import time
        request=self.intent_request();later=time()+INTENT_SECONDS+2
        with patch('django.core.signing.time.time',return_value=later):
            self.assertIsNone(destination_after_activation(request))
        self.assertNotIn(INTENT_KEY,request.session)
        self.assertFalse(Visit.objects.exists())

    def test_selection_cannot_be_replayed_for_another_login_workspace_or_user(self):
        for change in ({'workspace':'another-context'},{'uid':self.manager.pk},{'next':'https://evil.invalid'}):
            with self.subTest(change=change):
                request=self.intent_request(**change)
                self.assertIsNone(destination_after_activation(request))
                self.assertNotIn(INTENT_KEY,request.session)

    def test_revocation_and_unpublication_are_rechecked_after_login(self):
        request=self.intent_request()
        self.change(is_published=False)
        self.assertIsNone(destination_after_activation(request))
        self.change(is_published=True)
        request=self.intent_request()
        PatientAccess.objects.filter(user=self.patient_user).update(is_active=False)
        self.assertIsNone(destination_after_activation(request))
        self.assertFalse(Visit.objects.exists())

    def test_service_workspace_shows_missing_content_without_implicitly_publishing(self):
        other=BookingService.objects.create(department=self.department,code='SECOND',name='另一项接诊服务')
        self.client.force_login(self.manager)
        before=ServicePresentation.objects.count()
        response=self.client.get(reverse('service_content_home'))
        self.assertContains(response,'另一项接诊服务')
        self.assertContains(response,'待创建服务说明')
        self.assertEqual(ServicePresentation.objects.count(),before)
        self.assertFalse(ServicePresentation.objects.filter(service=other).exists())

    def test_draft_preview_is_current_clinic_manager_only_and_has_no_booking_link(self):
        self.change(is_published=False)
        url=reverse('service_content_preview',args=[self.profile.pk])
        self.client.force_login(self.manager)
        response=self.client.get(url)
        self.assertEqual(response.status_code,200);self.assertContains(response,'预览不接受预约')
        self.assertNotContains(response,'?service='+str(self.service.pk))
        self.assertEqual(self.client.get(reverse('public_service_detail',args=[self.service.pk])).status_code,404)
        self.login_patient()
        self.assertEqual(self.client.get(url).status_code,403)

    def test_service_content_workspace_and_preview_cannot_read_another_clinic(self):
        from scheduling.resource_models import Department
        service=BookingService.objects.create(department=Department.objects.create(clinic=self.b,code='B',name='B科室'),
            code='B_SERVICE',name='另一店服务')
        profile=ServicePresentation.objects.create(service=service,title='另一店私有草稿')
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(reverse('service_content_home'),{'clinic':self.b.pk}),'另一店私有草稿')
        self.assertEqual(self.client.get(reverse('service_content_preview',args=[profile.pk])).status_code,404)

    def test_service_template_is_editable_draft_and_get_changes_no_business_data(self):
        self.client.force_login(self.manager)
        before=ServicePresentation.objects.count()
        response=self.client.get(reverse('resource_config',args=['service_profile']),
            {'category':'CHECKUP','service':self.service.pk})
        self.assertEqual(response.status_code,200)
        values=response.context['form'].initial
        self.assertEqual(values['service'],self.service.pk)
        self.assertEqual(values['title'],'口腔检查与初诊')
        self.assertFalse(values['is_published']);self.assertIsNone(values['fee_amount'])
        self.assertEqual(ServicePresentation.objects.count(),before)

    def test_reverse_migration_refuses_to_discard_service_descriptions(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from types import SimpleNamespace
        guard=importlib.import_module('scheduling.migrations.0006_servicepresentation').preserve_service_content
        with self.assertRaisesRegex(RuntimeError,'Service descriptions exist'):
            guard(apps,SimpleNamespace(connection=connection))

    def test_public_mutations_are_not_allowed(self):
        for route,args in [('public_home',[]),('system_entry',[]),('public_services',[]),
                           ('public_service_detail',[self.service.pk]),('public_service_guide',['CHECKUP']),('public_clinics',[])]:
            self.assertEqual(self.client.post(reverse(route,args=args),{'is_published':True}).status_code,405)

