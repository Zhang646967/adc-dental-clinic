"""Additive synthetic accounts; never rebind arbitrary users or reset staff passwords."""
import secrets
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from accounts.models import UserAccount,RoleAssignment
from registry.models import Clinic,Dentist
from patients.models import Patient
from portal.models import PatientAccess

class Command(BaseCommand):
    help="Create two synthetic patient logins and doctor_b; no destructive reset."
    def add_arguments(self,parser): parser.add_argument("--reset-passwords",action="store_true")
    @transaction.atomic
    def handle(self,*args,**options):
        if not settings.DEBUG or settings.ADC_READ_ONLY: raise CommandError("Writable local demo only.")
        clinics=list(Clinic.objects.filter(clinic_code__in=["DEMO-1","DEMO-2"]).order_by("clinic_code"))
        if len(clinics)!=2: raise CommandError("Run seed_demo first. Existing accounts are not reset by that command.")
        report=[]
        for i,name in enumerate(("patient_demo_a","patient_demo_b")):
            patient,_=Patient.objects.get_or_create(patient_no=f"PORTAL-DEMO-{i+1}",defaults={
                "name":f"门户体验患者{i+1}","date_of_birth":date(1998 if i==0 else 1955,1,1),
                "billing_address":"虚构账单地址（课程演示）","phone":"000-DEMO","email":f"portal{i+1}@example.invalid",
                "emergency_name":"虚构联系人","emergency_phone":"000-DEMO","created_in_clinic":clinics[i]})
            user,made=UserAccount.objects.get_or_create(username=name)
            if user.dentist_id or RoleAssignment.objects.filter(user=user).exists(): raise CommandError("Reserved demo username has staff permissions; refusing to bind.")
            access,created=PatientAccess.objects.get_or_create(user=user,defaults={"patient":patient})
            if access.patient_id!=patient.pk: raise CommandError("Existing patient binding differs; refusing to overwrite.")
            if made or options["reset_passwords"]:
                password=secrets.token_urlsafe(18);user.set_password(password);user.save(update_fields=["password"])
                report.append((name,password))
        dentist=Dentist.objects.get(employee_no="DEMO-D2")
        user,made=UserAccount.objects.get_or_create(username="doctor_b",defaults={"dentist":dentist})
        if user.dentist_id!=dentist.pk or PatientAccess.objects.filter(user=user).exists(): raise CommandError("doctor_b binding differs; refusing to overwrite.")
        RoleAssignment.objects.get_or_create(user=user,role="DENTIST",scope_kind="SELF_DENTIST",clinic=None)
        if made or options["reset_passwords"]:
            password=secrets.token_urlsafe(18);user.set_password(password);user.save(update_fields=["password"]);report.append(("doctor_b",password))
        def show():
            self.stdout.write("Portal demo committed. Existing staff passwords, patients and bookings were not reset.")
            for name,password in report: self.stdout.write(f"LOCAL ONLY | {name} | {password}")
            if not report: self.stdout.write("No passwords changed. Use --reset-passwords only for these three named accounts if needed.")
        transaction.on_commit(show)
