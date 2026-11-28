"""Opening a clinic project never promotes old cases or grants clinical authority."""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TransactionTestCase, override_settings

from care.models import AuditEvent
from clinical.authority_services import confirm_authority, prepare_authority
from clinical.examination_models import ExaminationDuty, ExaminationProject
from tests.test_examination_reports import ExaminationFixture


class SiteExaminationSetupTests(ExaminationFixture, TransactionTestCase):
    def setUp(self):
        with override_settings(ADC_CLINICAL_SYNTHETIC=True):
            self.setup_examinations()
        self.mode = override_settings(ADC_CLINICAL_SYNTHETIC=False)
        self.mode.enable()
        self.addCleanup(self.mode.disable)

    def configure(self, action, *options, code='SITE-EXAM', operator=None):
        call_command('configure_site_examination', '--operator', (operator or self.tech).username,
                     '--service', str(self.service.pk), '--code', code, action, *options, stdout=StringIO())

    def open(self, *, reviewer=None, **kwargs):
        self.configure('provision', '--name', '门诊文本检查', '--examiner', self.doc.username,
                       '--reviewer', (reviewer or self.reviewer).username, **kwargs)

    def test_nonclinical_configuration_requires_current_independent_grants(self):
        for parameters in ({}, {'reviewer': self.doc}, {'operator': self.front}, {'code': self.project.code}):
            with self.subTest(parameters=tuple(parameters)), self.assertRaises(CommandError):
                self.open(**parameters)
        self.assertFalse(ExaminationProject.objects.exclude(operating_mode='REHEARSAL').exists())
        for overrides in ({'ADC_CLINICAL_SYNTHETIC': True}, {'ADC_READ_ONLY': True}):
            with override_settings(**overrides), self.assertRaises(CommandError):
                self.open()
        with self.assertRaises(CommandError):
            self.configure('suspend', code=self.project.code)
        with self.assertRaises(CommandError):
            self.configure('revoke', '--user', self.doc.username, '--duty', 'EXECUTE', code=self.project.code)
        self.assertTrue(ExaminationDuty.objects.filter(project=self.project, user=self.doc, is_active=True).exists())

    def test_pause_and_reopen_require_fresh_duties_and_preserve_the_audit(self):
        for user, reviewer in ((self.doc, self.reviewer), (self.reviewer, self.doc)):
            fields = self.fields(user, source_kind='DOCUMENT', source_reference='ISOLATED-PROVISION',
                                 issuer='隔离库授权样本')
            proposal = prepare_authority(actor=self.manager, action='PROPOSE', fields=fields)
            grant, _ = confirm_authority(actor=self.manager, proposal_token=proposal['proposal_token'], confirmed=True)
            self.ctx(reviewer, 'DENTIST')
            self.decide(grant, 'APPROVE', actor=reviewer)
        self.open()
        self.open()
        self.configure('suspend')
        self.configure('suspend')
        project = ExaminationProject.objects.get(service=self.service, code='SITE-EXAM')
        self.assertEqual((project.operating_mode, project.operating_revision), ('SUSPENDED', 2))
        self.assertFalse(ExaminationDuty.objects.filter(project=project, is_active=True).exists())
        self.open()
        self.open()
        project.refresh_from_db()
        self.assertEqual((project.operating_mode, project.operating_revision), ('SITE', 3))
        self.assertEqual(ExaminationDuty.objects.filter(project=project, is_active=True).count(), 2)
        transitions = list(AuditEvent.objects.filter(subject_type='examinationproject', subject_key=str(project.pk))
                           .order_by('pk').values_list('event_type', flat=True))
        self.assertEqual(transitions, ['EXAMINATION_PROJECT_PROVISIONED', 'EXAMINATION_PROJECT_SUSPENDED',
                                      'EXAMINATION_PROJECT_RESUMED'])
