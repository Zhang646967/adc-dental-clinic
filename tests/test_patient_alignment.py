"""Patient-visible P1.5 contracts against real Django/PostgreSQL."""
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlparse,parse_qs
from django.test import Client,TransactionTestCase
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from accounts.models import UserAccount,RoleAssignment
from registry.models import Clinic
from registry.directory_models import ClinicDirectory
from scheduling.resource_models import Department,BookingService,ResourcePolicy,ServicePresentation
from scheduling.service_content import draft_from_guide
from portal.discovery_queries import clinic_index
from portal.models import PatientAccess,PatientRelationship,PatientAppointmentGrant
from scheduling.models import Visit
from care.models import Invoice
from finance.cash_models import CashEntry
from clinical.models import SensitiveReadEvent
from tests import test_mini_program as mini
from tests.test_reception_resources import ResourceFixture
from tests.test_care_finance_equipment import CFEFixture
from tests.workspace_client import WorkspaceClient


class DiscoveryAlignmentTests(ResourceFixture,TransactionTestCase):
    setUp=mini.MiniProgramTests.setUp
    login=mini.MiniProgramTests.login
    post=mini.MiniProgramTests.post

    def directory(self,clinic,city='长沙'):
        return ClinicDirectory.objects.create(clinic=clinic,display_name='ADC·'+clinic.name,province='课程省',
            city=city,district='课程区',address='课程合成地址',entrance='课程接待入口',public_phone='000-0000-1000',
            synthetic=True,is_published=True)

    def second_service(self):
        self.directory(self.a);self.directory(self.b)
        ResourcePolicy.objects.create(clinic=self.b,state='ENABLED')
        department=Department.objects.create(clinic=self.b,code='REST',name='综合口腔')
        service=BookingService.objects.create(department=department,code='REST',name='基础修复',duration_minutes=45)
        service.dentists.set([self.d2])
        ServicePresentation.objects.create(service=service,**dict(draft_from_guide('RESTORATION'),title='牙痛评估预约',is_published=True))
        return service

    def test_index_is_small_public_projection_without_calendars(self):
        response=Client().get(reverse('mini_public_index'))
        self.assertEqual(response.status_code,200)
        self.assertLess(len(response.content),100*1024)
        data=response.json()['data'];self.assertNotIn('dentists',data)
        self.assertNotIn('shifts',response.content.decode())
        self.assertNotIn('credential_reference',response.content.decode())
        self.assertNotIn('home_address',response.content.decode())

    def test_twenty_branch_index_has_bounded_queries(self):
        self.directory(self.a)
        with CaptureQueriesContext(connection) as small:clinic_index()
        for n in range(19):
            clinic=Clinic.objects.create(clinic_code='P15-'+str(n),name='合成门店'+str(n),postal_address='合成地址',
                supervisor_name='合成负责人',phone='00000000000',email='course@example.invalid',area_sqm=100)
            self.directory(clinic)
        with CaptureQueriesContext(connection) as larger:rows=clinic_index()
        self.assertEqual(len(rows['clinics']),20)
        self.assertLessEqual(len(larger),len(small)+2)

    def test_unsupported_pair_keeps_filters_and_offers_actual_same_city(self):
        service=self.second_service()
        response=Client().get(reverse('mini_public_services'),{'clinic':self.a.pk,'category':'RESTORATION'})
        data=response.json()['data']
        self.assertEqual(data['status'],'NOT_OFFERED');self.assertEqual(data['selected_clinic'],self.a.pk)
        self.assertEqual(data['selected_category'],'RESTORATION');self.assertEqual(data['offerings'],[])
        self.assertEqual([c['id'] for c in data['alternatives']],[self.b.pk])
        result=Client().get(reverse('mini_public_services'),{'clinic':self.b.pk,'category':'RESTORATION'}).json()['data']
        self.assertEqual([s['id'] for s in result['offerings']],[service.pk])

    def test_web_and_native_use_identical_selection_and_suggestions(self):
        self.second_service();query={'clinic':self.a.pk,'category':'RESTORATION'}
        web=Client().get(reverse('public_services'),query)
        native=Client().get(reverse('mini_public_services'),query).json()['data']
        self.assertEqual(web.context['count'],native['count'])
        self.assertEqual([c['id'] for c in web.context['alternatives']],[c['id'] for c in native['alternatives']])
        self.assertContains(web,'这些门店可以继续办理')

    def test_published_service_without_schedule_is_not_an_unsupported_service(self):
        from scheduling.models import AvailabilitySlot
        AvailabilitySlot.objects.filter(clinic=self.a).update(is_active=False)
        data=Client().get(reverse('mini_public_services'),{'clinic':self.a.pk,'category':'CHECKUP'}).json()['data']
        self.assertEqual(data['status'],'READY');self.assertEqual(data['count'],1)
        detail=Client().get(reverse('mini_public_service',args=[self.service.pk])).json()['data']
        self.assertIsNone(detail['default_day'])

    def test_default_day_comes_from_selected_doctor_schedule(self):
        response=self.client.get(reverse('mini_service',args=[self.service.pk]),{'dentist':self.d1.pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['data']['default_day'],self.t.date().isoformat())

    def test_unknown_or_unadapted_doctor_is_rejected(self):
        response=Client().get(reverse('mini_public_service',args=[self.service.pk]),{'dentist':999999})
        self.assertEqual(response.status_code,404)

    def test_login_handoff_preserves_the_actual_selected_day(self):
        day=self.t.date().isoformat()
        response=self.client.get(reverse('portal_login'),{'service':self.service.pk,'dentist':self.d1.pk,'day':day})
        self.assertEqual(response.status_code,302)
        query=parse_qs(urlparse(response.url).query)
        self.assertEqual(query['day'],[day]);self.assertEqual(query['dentist'],[str(self.d1.pk)])

    def test_public_reads_do_not_create_appointments_or_financial_effects(self):
        before=(Visit.objects.count(),Invoice.objects.count(),CashEntry.objects.count())
        for route in ['mini_public_index','mini_public_services']:
            self.assertEqual(Client().get(reverse(route)).status_code,200)
        self.assertEqual(before,(Visit.objects.count(),Invoice.objects.count(),CashEntry.objects.count()))

    def test_invalid_filters_are_not_silently_replaced(self):
        for query in [{'category':'UNKNOWN'},{'clinic':'-1'},{'clinic':'999999'}]:
            self.assertEqual(Client().get(reverse('mini_public_services'),query).status_code,404)


class PatientInvoiceAlignmentTests(CFEFixture,TransactionTestCase):
    def setUp(self):
        self.setup_cfe();self.visit,self.invoice=self.billed()
        self.owner=PatientAccess.objects.get(patient=self.visit.patient).user
        self.client=WorkspaceClient();self.client.force_login(self.owner)

    def test_native_invoice_equals_web_published_money_and_balance(self):
        native=self.client.get(reverse('mini_invoice',args=[self.invoice.pk]))
        self.assertEqual(native.status_code,200,native.content)
        data=native.json()['data'];web=self.client.get(reverse('portal_invoice',args=[self.invoice.pk]))
        self.assertEqual(data['total'],str(web.context['total']))
        for key in ['billed','net_received','remaining','refund_due']:
            self.assertEqual(data['cash_balance'][key],str(web.context['cash_balance'][key]))
        self.assertEqual(len(data['lines']),len(web.context['lines']))

    def test_only_posted_cash_changes_native_balance(self):
        entry=self.cash(self.invoice,amount=Decimal('10.00'))
        url=reverse('mini_invoice',args=[self.invoice.pk])
        pending=self.client.get(url).json()['data']['cash_balance']
        self.assertEqual(pending['net_received'],'0.00');self.assertEqual(pending['pending'],1)
        self.approve(entry)
        posted=self.client.get(url).json()['data']['cash_balance']
        self.assertEqual(posted['net_received'],'10.00')

    def test_other_patient_cannot_read_by_guessed_invoice_id(self):
        other=UserAccount.objects.exclude(pk=self.owner.pk).filter(patient_access__is_active=True).first()
        self.assertIsNotNone(other);client=WorkspaceClient();client.force_login(other)
        self.assertEqual(client.get(reverse('mini_invoice',args=[self.invoice.pk])).status_code,404)

    def test_inactive_patient_access_cannot_read(self):
        PatientAccess.objects.filter(user=self.owner).update(is_active=False)
        response=self.client.get(reverse('mini_invoice',args=[self.invoice.pk]))
        self.assertEqual(response.status_code,409)
        self.assertNotIn('data',response.json())

    def test_invoice_is_get_only_and_does_not_post_cash(self):
        before=(Invoice.objects.count(),CashEntry.objects.count())
        self.assertEqual(self.client.post(reverse('mini_invoice',args=[self.invoice.pk]),{},
            HTTP_X_ADC_WORKSPACE=self.client.current_token()).status_code,405)
        self.assertEqual(before,(Invoice.objects.count(),CashEntry.objects.count()))

    def test_invalid_revision_does_not_fall_back_to_current(self):
        for value in ['0','-1','abc','999999']:
            self.assertEqual(self.client.get(reverse('mini_invoice',args=[self.invoice.pk]),{'revision':value}).status_code,404)

    def test_invoice_read_has_typed_sensitive_audit(self):
        self.client.get(reverse('mini_invoice',args=[self.invoice.pk]))
        row=SensitiveReadEvent.objects.filter(actor=self.owner,object_kind='INVOICE').latest('pk')
        self.assertEqual(row.object_id,self.invoice.pk);self.assertEqual(row.purpose,'BILLING')

    def test_old_invoice_version_retains_total_and_marks_current_balance(self):
        from care.corrections import request_line_correction,review_correction
        self.visit.refresh_from_db();line=self.invoice.current_record_version.treatment_lines.first()
        old_total=self.invoice.current_record_version.total_amount
        case=request_line_correction(actor=self.doctor,visit_id=self.visit.pk,expected_version=self.visit.lock_version,
            line_id=line.pk,quantity=Decimal('1'),unit_price=Decimal('99.99'),reason='合成数量更正')
        review_correction(actor=self.fin,request_id=case.pk,decision='approve',reason='独立核对合成更正')
        url=reverse('mini_invoice',args=[self.invoice.pk])
        old=self.client.get(url,{'revision':1}).json()['data'];current=self.client.get(url).json()['data']
        self.assertEqual(old['total'],str(old_total));self.assertFalse(old['is_current'])
        self.assertEqual(current['total'],'99.99');self.assertTrue(current['is_current'])
        self.assertEqual(old['cash_balance'],current['cash_balance']);self.assertEqual(old['cash_balance']['current_revision'],2)

    def test_verified_appointment_delegate_still_cannot_read_invoice(self):
        from portal import relationships as rel
        delegate=UserAccount.objects.create_user(username='p15_appointment_delegate',password='synthetic-delegate')
        RoleAssignment.objects.filter(user=self.front,role='FRONT_DESK',clinic=self.a).update(can_verify_patient_relationships=True)
        token=rel.prepare_create(actor=self.front,patient_no=self.visit.patient.patient_no,related_name='课程合成代约人',
            kind='DELEGATE',username=delegate.username,note='仅合成预约委托')
        case,_=rel.confirm(actor=self.front,token=token,confirmed=True)
        token=rel.prepare_action(actor=self.front,case_id=case.pk,action='VERIFY',basis='IN_PERSON',reference='P15-SYNTHETIC',
            note='已核对课程合成关系',valid_until=timezone.now()+timedelta(days=7))
        rel.confirm(actor=self.front,token=token,confirmed=True)
        grant=PatientAppointmentGrant.objects.get(relationship=case)
        client=WorkspaceClient();client.force_login(delegate)
        selected=client.post(reverse('mini_subject_select'),{'subject':'grant:'+str(grant.pk)},HTTP_X_ADC_WORKSPACE=client.current_token())
        self.assertEqual(selected.status_code,200,selected.content)
        self.assertEqual(client.get(reverse('mini_invoice',args=[self.invoice.pk])).status_code,403)
