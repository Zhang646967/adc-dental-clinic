"""Additive demo with manager roles at two clinics and a separate dentist identity."""
import secrets
from datetime import date
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from accounts.models import UserAccount,RoleAssignment
from registry.models import Clinic,Dentist
from portal.models import PatientAccess
class Command(BaseCommand):
 help='Create multi_demo for role-first / clinic-second local demonstration. No existing passwords changed.'
 @transaction.atomic
 def handle(self,*args,**options):
  if not settings.DEBUG or settings.ADC_READ_ONLY:raise CommandError('Only a writable local synthetic instance.')
  clinics=list(Clinic.objects.filter(clinic_code__in=['DEMO-1','DEMO-2'],is_active=True).order_by('clinic_code'))
  if len(clinics)!=2:raise CommandError('Run seed_demo first; this command does not create or reset existing clinics.')
  dentist,_=Dentist.objects.get_or_create(employee_no='DEMO-D3',defaults={'name':'多身份演示医生','date_of_birth':date(1988,1,1),'home_address':'虚构地址','phone':'000-DEMO','email':'multi@example.invalid'})
  user,created=UserAccount.objects.get_or_create(username='multi_demo',defaults={'dentist':dentist})
  if user.dentist_id!=dentist.pk or PatientAccess.objects.filter(user=user).exists():raise CommandError('Reserved demo name is already assigned differently; refusing overwrite.')
  if not created and RoleAssignment.objects.filter(user=user).exclude(role__in=['DENTIST','MANAGER']).exists():raise CommandError('Unexpected existing grants; refusing to alter the account.')
  RoleAssignment.objects.get_or_create(user=user,role='DENTIST',scope_kind='SELF_DENTIST',clinic=None)
  for c in clinics:RoleAssignment.objects.get_or_create(user=user,role='MANAGER',scope_kind='CLINIC',clinic=c)
  password=secrets.token_urlsafe(18) if created else None
  if password:user.set_password(password);user.save(update_fields=['password'])
  def show():
   self.stdout.write('Workspace demo committed. Existing accounts, passwords and records preserved.')
   if password:self.stdout.write(f'LOCAL ONLY | multi_demo | {password}')
   else:self.stdout.write('multi_demo already exists; password and inactive grants not reset.')
  transaction.on_commit(show)
