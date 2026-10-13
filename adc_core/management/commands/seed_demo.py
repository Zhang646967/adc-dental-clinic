"""Synthetic local bootstrap. Passwords are random and printed only on creation/reset."""
import secrets
from datetime import date, datetime, time, timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from registry.models import Clinic, Dentist, Allergy, Qualification, TreatmentType
from scheduling.models import AvailabilitySlot
from patients.models import Patient
from patients.services import create_patient
from adc_core.rules import BUSINESS_TZ

class Command(BaseCommand):
    help = "Initialize local synthetic demo accounts, catalogs and future availability."
    def add_arguments(self, parser):
        parser.add_argument("--reset-passwords", action="store_true", help="Explicitly reset only the predefined demo accounts")
    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or settings.ADC_READ_ONLY:
            raise CommandError("Demo bootstrap is enabled only in writable local settings.")
        clinics = []
        dentists = []
        for n in (1, 2):
            c, _ = Clinic.objects.get_or_create(clinic_code=f"DEMO-{n}", defaults={"name": f"演示诊所{n}", "postal_address": f"虚构演示地址{n}号（不用于真实联系）", "supervisor_name": f"演示主管{n}", "phone": "000-DEMO", "email": f"clinic{n}@example.invalid", "area_sqm": "120.00"})
            d, _ = Dentist.objects.get_or_create(employee_no=f"DEMO-D{n}", defaults={"name": f"演示牙医{n}", "date_of_birth": date(1990, 1, 1), "home_address": "虚构地址", "phone": "000-DEMO", "email": f"dentist{n}@example.invalid"})
            clinics.append(c); dentists.append(d)
        for code, name in [("LATEX", "乳胶（演示目录）"), ("METAL", "金属（演示目录）")]:
            Allergy.objects.get_or_create(code=code, defaults={"name": name})
        Qualification.objects.get_or_create(code="DEMO-Q", defaults={"name": "资格类别（未作真实验证）"})
        TreatmentType.objects.get_or_create(code="DEMO-T", defaults={"name": "演示治疗项目", "unit_definition": "一次演示标准单位", "standard_unit_price": "200.00"})
        users = {}
        configs = [
            ("front_a", "FRONT_DESK", "CLINIC", clinics[0], None),
            ("front_b", "FRONT_DESK", "CLINIC", clinics[1], None),
            ("doctor_a", "DENTIST", "SELF_DENTIST", None, dentists[0]),
            ("manager_a", "MANAGER", "CLINIC", clinics[0], None),
            ("hq_demo", "HQ", "CHAIN", None, None),
            ("finance_demo", "FINANCE", "CHAIN", None, None),
            ("tech_demo", "SYSADMIN", "TECHNICAL", None, None),
        ]
        secrets_to_show = []
        for name, role, scope, clinic, dentist in configs:
            user, made = UserAccount.objects.get_or_create(username=name, defaults={"dentist": dentist})
            if made or options["reset_passwords"]:
                password = secrets.token_urlsafe(18)
                user.set_password(password); user.save(update_fields=["password"])
                secrets_to_show.append((name, password))
            RoleAssignment.objects.get_or_create(user=user, role=role, scope_kind=scope, clinic=clinic)
            users[name] = user
        for offset in range(1, 8):
            day = timezone.localdate() + timedelta(days=offset)
            for c, d in zip(clinics, dentists):
                AvailabilitySlot.objects.get_or_create(clinic=c, dentist=d,
                    starts_at=datetime.combine(day, time(9), BUSINESS_TZ), ends_at=datetime.combine(day, time(18), BUSINESS_TZ))
        for i, front in enumerate(("front_a", "front_b")):
            if not Patient.objects.filter(name=f"演示患者{i+1}", created_in_clinic=clinics[i]).exists():
                p = create_patient(actor=users[front], clinic_id=clinics[i].pk, allergy_status="UNKNOWN", details={
                    "name": f"演示患者{i+1}", "date_of_birth": date(2000, 1, 1), "billing_address": "虚构账单地址",
                    "phone": "000-DEMO", "email": "patient@example.invalid", "emergency_name": "演示联系人", "emergency_phone": "000-DEMO"})
                self.stdout.write(f"Patient {i+1}: {p.patient_no}")
        # Print only after commit so a failure doesn't leave misleading credentials.
        def report():
            self.stdout.write(self.style.SUCCESS("Synthetic data committed. Existing account passwords unchanged unless reset requested."))
            for name, password in secrets_to_show:
                self.stdout.write(f"LOCAL DEMO ONLY | {name} | {password}")
            if not secrets_to_show:
                self.stdout.write("No passwords changed. --reset-passwords resets only named demo accounts.")
        transaction.on_commit(report)
