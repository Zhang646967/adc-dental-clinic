"""Verify the actual synthetic preparation command and original-row preservation."""
from datetime import date
from unittest.mock import patch
from django.test import TransactionTestCase
from tests.fixtures import FixtureMixin
from adc_core.rules import RuleError
from care.models import Invoice
from registry.models import Clinic,Dentist
from registry.directory_models import ClinicDirectory,ClinicDirectoryRevision
from scheduling.models import Visit
from scheduling.resource_models import ResourcePolicy,ServicePresentation
from workspaces.models import WorkspaceContext
from scripts.course_branch_network import prepare_network
from accounts.models import RoleAssignment


class CourseNetworkTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.make_fixture()
        self.tech._adc_workspace=WorkspaceContext.objects.create(user=self.tech,role='SYSADMIN',login_channel='STAFF')
        self.dentists=[self.d1.pk,self.d2.pk]
        for i in (3,4):
            self.dentists.append(Dentist.objects.create(employee_no='NET-D'+str(i),name='合成网络医师'+str(i),
                date_of_birth=date(1990,1,1),home_address='虚构地址',phone='00000000000',email=f'net{i}@example.invalid').pk)

    def run_preparation(self):
        return prepare_network(technical_actor=self.tech,operator_password='test-only-pass-abc',manager=self.manager,
            frontdesk=self.front,existing_clinic_ids=[self.a.pk,self.b.pk],dentist_ids=self.dentists)

    @patch.dict('os.environ',{'ADC_RC_SYNTHETIC':'1'})
    def test_twenty_directory_rows_four_operational_branches_keep_original_facts(self):
        before=list(Clinic.objects.order_by('pk').values())
        result=self.run_preparation()
        self.assertEqual(len(result),20);self.assertEqual(Clinic.objects.count(),20)
        self.assertEqual(ClinicDirectory.objects.count(),20);self.assertEqual(ClinicDirectoryRevision.objects.count(),20)
        self.assertEqual(ClinicDirectory.objects.values('city').distinct().count(),8)
        self.assertEqual(ResourcePolicy.objects.filter(state='ENABLED').count(),4)
        self.assertEqual(ResourcePolicy.objects.filter(state='PREPARING').count(),16)
        self.assertEqual(ServicePresentation.objects.filter(is_published=True).count(),16)
        self.assertEqual(before,list(Clinic.objects.filter(pk__in=[self.a.pk,self.b.pk]).order_by('pk').values()))
        self.assertFalse(Visit.objects.exists());self.assertFalse(Invoice.objects.exists())
        with self.assertRaises(RuleError):self.run_preparation()
        self.assertEqual(ClinicDirectoryRevision.objects.count(),20)

    @patch.dict('os.environ',{'ADC_RC_SYNTHETIC':'0'})
    def test_non_synthetic_environment_is_not_seeded(self):
        with self.assertRaises(RuleError):self.run_preparation()
        self.assertEqual(Clinic.objects.count(),2)
        self.assertFalse(ClinicDirectory.objects.exists())

    @patch.dict('os.environ',{'ADC_RC_SYNTHETIC':'1'})
    def test_prepared_original_clinics_retain_their_existing_service_profile_rows(self):
        from scripts.course_resources import prepare_clinic
        from scheduling.resource_models import BookingService
        original_ids=[]
        for clinic,dentist in [(self.a,self.d1),(self.b,self.d2)]:
            RoleAssignment.objects.get_or_create(user=self.manager,role='MANAGER',scope_kind='CLINIC',clinic=clinic)
            self.manager._adc_workspace=WorkspaceContext.objects.create(user=self.manager,role='MANAGER',clinic=clinic,login_channel='STAFF')
            prepare_clinic(actor=self.manager,clinic_id=clinic.pk,dentist_ids=[dentist.pk])
            for service in BookingService.objects.filter(department__clinic=clinic):
                profile=ServicePresentation.objects.create(service=service,title='原已发布服务',summary='已有资料',
                    suitable_for='已有适用说明',visit_content='已有包含内容',limitations='已有范围',preparation='已有准备',
                    fee_note='费用经实际评估',is_published=True)
                original_ids.append((profile.pk,service.pk))
        self.run_preparation()
        self.assertEqual(ServicePresentation.objects.filter(is_published=True).count(),16)
        for pk,service in original_ids:
            current=ServicePresentation.objects.get(pk=pk)
            self.assertEqual(current.service_id,service);self.assertTrue(current.is_published)
            self.assertNotEqual(current.title,'原已发布服务')
        self.assertEqual(ClinicDirectory.objects.count(),20)
        self.assertFalse(Visit.objects.exists());self.assertFalse(Invoice.objects.exists())
