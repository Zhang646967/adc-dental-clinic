from datetime import date, timedelta
from decimal import Decimal
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from registry.models import Clinic, Dentist
from patients.models import Patient
from scheduling.models import AvailabilitySlot

from tests.workspace_client import WorkspaceClient

class FixtureMixin:
    client_class = WorkspaceClient
    def make_fixture(self):
        self.front=UserAccount.objects.create_user(username="test_front",password="test-only-pass-123")
        self.front2=UserAccount.objects.create_user(username="test_front_2",password="test-only-pass-456")
        self.manager=UserAccount.objects.create_user(username="test_manager",password="test-only-pass-789")
        self.tech=UserAccount.objects.create_user(username="test_tech",password="test-only-pass-abc",is_staff=True,is_superuser=True)
        self.a=Clinic.objects.create(clinic_code="A",name="演示甲店",postal_address="虚构甲址",supervisor_name="演示主管",phone="000",email="a@example.invalid",area_sqm=120)
        self.b=Clinic.objects.create(clinic_code="B",name="演示乙店",postal_address="虚构乙址",supervisor_name="演示主管",phone="000",email="b@example.invalid",area_sqm=120)
        self.d1=Dentist.objects.create(employee_no="D1",name="演示医生1",date_of_birth=date(1990,1,1),home_address="虚构地址",phone="000",email="d1@example.invalid")
        self.d2=Dentist.objects.create(employee_no="D2",name="演示医生2",date_of_birth=date(1990,1,1),home_address="虚构地址",phone="000",email="d2@example.invalid")
        for u in (self.front,self.front2):
            for c in (self.a,self.b):
                RoleAssignment.objects.create(user=u,role="FRONT_DESK",scope_kind="CLINIC",clinic=c)
        RoleAssignment.objects.create(user=self.manager,role="MANAGER",scope_kind="CLINIC",clinic=self.a)
        RoleAssignment.objects.create(user=self.tech,role="SYSADMIN",scope_kind="TECHNICAL")
        self.p1=Patient.objects.create(name="演示患者1",date_of_birth=date(2000,1,1),billing_address="虚构址",phone="000",emergency_name="联系人",emergency_phone="000",created_in_clinic=self.a)
        self.p2=Patient.objects.create(name="演示患者2",date_of_birth=date(2000,1,1),billing_address="虚构址",phone="000",emergency_name="联系人",emergency_phone="000",created_in_clinic=self.b)
        self.t=(timezone.now()+timedelta(days=1)).replace(second=0,microsecond=0)
        self.slot1=AvailabilitySlot.objects.create(clinic=self.a,dentist=self.d1,starts_at=self.t,ends_at=self.t+timedelta(hours=4))
        self.slot2=AvailabilitySlot.objects.create(clinic=self.b,dentist=self.d2,starts_at=self.t,ends_at=self.t+timedelta(hours=4))
    def book(self, **kw):
        from scheduling.services import create_appointment
        defaults=dict(actor=self.front,patient_no=self.p1.patient_no,slot_id=self.slot1.pk,start=self.t,end=self.t+timedelta(hours=1))
        defaults.update(kw)
        return create_appointment(**defaults)
