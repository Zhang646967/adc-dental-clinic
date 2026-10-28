"""Explicit fresh course release; stdout is a PRIVATE credential handover."""
import io
import json
import os
import re
import secrets

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from accounts.models import UserAccount
from care.models import AuditEvent
from registry.models import Clinic, Dentist


EVENT = 'COURSE_RELEASE_PREPARED'


class Command(BaseCommand):
    help = 'Prepare the complete synthetic twenty-clinic course release in an empty database.'

    def handle(self, *args, **options):
        if (os.environ.get('ADC_RC_SYNTHETIC') != '1' or not settings.ADC_CLINICAL_SYNTHETIC
                or settings.ADC_READ_ONLY or connection.settings_dict['NAME'] != 'adc_rc_demo'):
            raise CommandError('Explicit writable adc_rc_demo synthetic course database required.')
        # Serialize the whole initializer, including the completion check. Each
        # owned command retains its own transaction and append-only audit.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(hashtext('adc.course.release.bootstrap.v1'))")
        try:
            previous = AuditEvent.objects.filter(event_type=EVENT).first()
            if previous:
                self.stdout.write(json.dumps({'status': 'ALREADY_PREPARED', **previous.change_summary}))
                return
            if UserAccount.objects.exists() or Clinic.objects.exists():
                raise CommandError('Existing or interrupted domain preserved; initialization cannot overwrite it.')
            self.prepare()
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(hashtext('adc.course.release.bootstrap.v1'))")

    def prepare(self):
        from accounts.governance import create_account, change_account, target_token
        from care.audit import emit
        from portal.discovery_queries import clinic_index
        from registry.directory_services import prepare_registration, confirm_directory_change
        from scripts.course_branch_network import prepare_network
        from scripts.course_profiles import prepare_profiles
        from scripts.course_profile_alignment import prepare_alignment, prepare_family_sample
        from workspaces.models import WorkspaceContext

        capture = io.StringIO()
        call_command('bootstrap_release_demo', stdout=capture)
        credentials = dict(re.findall(r'^LOCAL(?: DEMO)? ONLY \| ([a-z0-9_]+) \| (\S+)$',
                                      capture.getvalue(), re.MULTILINE))
        if 'tech_demo' not in credentials:
            raise CommandError('Private initial credentials were not captured; preserve the interrupted database.')
        # Emit immediately into the operator's redirected file, so an interrupted
        # catalogue preparation does not lose the already committed passwords.
        self.stdout.write(capture.getvalue())
        technical = UserAccount.objects.get(username='tech_demo')
        technical._adc_workspace = WorkspaceContext.objects.create(
            user=technical, role='SYSADMIN', login_channel='STAFF')
        manager = UserAccount.objects.get(username='manager_a')
        frontdesk = UserAccount.objects.get(username='front_a')
        password = credentials['tech_demo']
        p = prepare_registration(actor=technical, kind='dentist', reason_code='SOURCE_RECORD', details={
            'employee_no': 'COURSE-BOOT-D4', 'name': '课程轮诊医师', 'date_of_birth': '1988-06-01',
            'home_address': '课程合成地址', 'phone': '00000003004', 'email': 'course4@example.invalid'})
        row = confirm_directory_change(actor=technical, proposal_token=p.proposal_token,
                                       operator_password=password, confirmed=True)
        dentist_ids = [Dentist.objects.get(employee_no='DEMO-D' + str(n)).pk for n in (1, 2, 3)] + [row.object_id]
        clinics = list(Clinic.objects.filter(clinic_code__in=['DEMO-1', 'DEMO-2'])
                       .order_by('clinic_code').values_list('pk', flat=True))
        prepare_network(technical_actor=technical, operator_password=password, manager=manager,
                        frontdesk=frontdesk, existing_clinic_ids=clinics, dentist_ids=dentist_ids)
        from registry.directory_models import ClinicDirectory
        branch_ids = list(ClinicDirectory.objects.order_by('clinic_id').values_list('clinic_id', flat=True))
        names = [f'p1_c{clinic:03}_doctor{position}' for clinic in branch_ids for position in (1, 2, 3)]
        names += ['p15_guardian', 'p1_finance_review']
        passwords = {name: secrets.token_urlsafe(24) for name in names}
        for name, value in passwords.items():
            self.stdout.write(f'LOCAL ONLY | {name} | {value}')
        reviewer = create_account(actor=technical, username='p1_finance_review',
            password=passwords['p1_finance_review'], operator_password=password,
            reason='课程独立财务复核账号')
        change_account(actor=technical, target_id=reviewer.pk, token=target_token(technical, reviewer),
            action='grant', operator_password=password, reason='课程独立财务复核职责', role='FINANCE')
        prepare_profiles(technical_actor=technical, operator_password=password, manager=manager,
                         frontdesk=frontdesk, passwords=passwords, reviewer=reviewer)
        prepare_alignment(technical_actor=technical, operator_password=password, manager=manager, frontdesk=frontdesk)
        prepare_family_sample(technical_actor=technical, operator_password=password, frontdesk=frontdesk,
                              guardian_password=passwords['p15_guardian'])
        index = clinic_index()
        required = {'CHECKUP', 'PREVENTION', 'RESTORATION', 'FOLLOWUP'}
        if len(index['clinics']) != 20 or any(not required <= set(c['service_categories']) for c in index['clinics']):
            raise CommandError('The complete clinic/service matrix is not ready; preserve initialization progress.')
        summary = {'dataset': 'course-20-v1', 'clinics': 20, 'cities': 8,
                   'doctor_profiles': 60, 'base_service_combinations': 80,
                   'history_imported': False, 'clinical_or_cash_created': False}
        with transaction.atomic():
            emit(technical, EVENT, technical, summary=summary)
        self.stdout.write(json.dumps({'status': 'COURSE_PREPARED', **summary}))
