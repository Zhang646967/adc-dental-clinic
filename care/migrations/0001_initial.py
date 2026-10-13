# Authored initial migration candidate. NOT generated or executed by Django here.
# Validate with: python manage.py makemigrations --check --dry-run
from django.db import models
from django.db.models import F, Q
from adc_core.identifiers import invoice_no
from django.db import migrations
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True
    dependencies = [('accounts', '0001_initial'), ('scheduling', '0001_initial'), ('registry', '0001_initial')]
    operations = [
        migrations.CreateModel(name='CorrectionRequest', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('kind', models.CharField(max_length=24, choices=[('APPOINTMENT_STATUS', '预约结果'), ('RECORD_CONTENT', '治疗内容')])),
        ('expected_visit_lock_version', models.PositiveIntegerField()),
        ('status', models.CharField(max_length=12, default='OPEN', choices=[('OPEN', '待审核'), ('APPLIED', '已应用'), ('REJECTED', '已拒绝'), ('WITHDRAWN', '已撤回')])),
        ('reason', models.TextField()),
        ('proposed_change', models.JSONField(default=dict)),
        ('requested_at', models.DateTimeField(auto_now_add=True)),
        ('applied_at', models.DateTimeField(null=True, blank=True)),
        ], options={'db_table': 'adc_correction_request'}),
        migrations.CreateModel(name='VisitRecordVersion', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('revision_no', models.PositiveIntegerField()),
        ('state', models.CharField(max_length=12, default='DRAFT', choices=[('DRAFT', '草稿'), ('PUBLISHED', '已发布'), ('ABANDONED', '已弃用')])),
        ('outcome', models.CharField(max_length=16, choices=[('TREATED', '有治疗'), ('NO_TREATMENT', '无治疗')])),
        ('created_at', models.DateTimeField(auto_now_add=True)),
        ('published_at', models.DateTimeField(null=True, blank=True)),
        ('allergy_review_snapshot', models.JSONField(default=dict)),
        ('billing_header_snapshot', models.JSONField(default=dict)),
        ('clinical_note', models.TextField(blank=True, default='')),
        ('no_treatment_reason', models.TextField(blank=True, default='')),
        ('total_amount', models.DecimalField(max_digits=16, decimal_places=2, default=0)),
        ('currency', models.CharField(max_length=3, default='CNY')),
        ], options={'db_table': 'adc_visit_record_version'}),
        migrations.CreateModel(name='TreatmentRecord', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('line_no', models.PositiveIntegerField()),
        ('name_snapshot', models.CharField(max_length=120)),
        ('unit_snapshot', models.CharField(max_length=120)),
        ('quantity', models.DecimalField(max_digits=12, decimal_places=3)),
        ('unit_price', models.DecimalField(max_digits=12, decimal_places=2)),
        ('line_amount', models.DecimalField(max_digits=16, decimal_places=2)),
        ('confirmed_at', models.DateTimeField(null=True, blank=True)),
        ('price_reason', models.CharField(max_length=500, blank=True, default='')),
        ], options={'db_table': 'adc_treatment_record', 'ordering': ['line_no']}),
        migrations.CreateModel(name='Invoice', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('invoice_no', models.CharField(max_length=40, unique=True, default=invoice_no, editable=False)),
        ('first_issued_at', models.DateTimeField(auto_now_add=True)),
        ], options={'db_table': 'adc_invoice'}),
        migrations.CreateModel(name='AuditEvent', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('event_type', models.CharField(max_length=48)),
        ('occurred_at', models.DateTimeField()),
        ('recorded_at', models.DateTimeField(auto_now_add=True)),
        ('subject_type', models.CharField(max_length=32)),
        ('subject_key', models.CharField(max_length=80)),
        ('reason', models.CharField(max_length=500, blank=True, default='')),
        ('change_summary', models.JSONField(default=dict)),
        ], options={'db_table': 'adc_audit_event'}),
        migrations.AddField(model_name='correctionrequest', name='visit', field=models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT)),
        migrations.AddField(model_name='correctionrequest', name='base_record_version', field=models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, null=True, blank=True, related_name='based_corrections')),
        migrations.AddField(model_name='correctionrequest', name='requester', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='requested_corrections')),
        migrations.AddField(model_name='correctionrequest', name='reviewer', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_corrections')),
        migrations.AddField(model_name='correctionrequest', name='dentist_confirmed_by', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='confirmed_corrections')),
        migrations.AddField(model_name='visitrecordversion', name='visit', field=models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, related_name='record_versions')),
        migrations.AddField(model_name='visitrecordversion', name='previous_version', field=models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, null=True, blank=True, related_name='next_versions')),
        migrations.AddField(model_name='visitrecordversion', name='correction_request', field=models.OneToOneField('care.CorrectionRequest', on_delete=models.PROTECT, null=True, blank=True, related_name='new_version')),
        migrations.AddField(model_name='visitrecordversion', name='prepared_by', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='prepared_versions')),
        migrations.AddField(model_name='visitrecordversion', name='reviewed_by', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='reviewed_versions')),
        migrations.AddField(model_name='treatmentrecord', name='record_version', field=models.ForeignKey('care.VisitRecordVersion', on_delete=models.PROTECT, related_name='treatment_lines')),
        migrations.AddField(model_name='treatmentrecord', name='treatment_type', field=models.ForeignKey('registry.TreatmentType', on_delete=models.PROTECT)),
        migrations.AddField(model_name='treatmentrecord', name='confirmed_by', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddField(model_name='invoice', name='visit', field=models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, related_name='invoice')),
        migrations.AddField(model_name='invoice', name='current_record_version', field=models.OneToOneField('care.VisitRecordVersion', on_delete=models.PROTECT, related_name='current_invoice')),
        migrations.AddField(model_name='auditevent', name='actor', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddField(model_name='auditevent', name='visit', field=models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, null=True, blank=True, related_name='events')),
        migrations.AddField(model_name='auditevent', name='correction_request', field=models.ForeignKey('care.CorrectionRequest', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddConstraint(model_name='correctionrequest', constraint=models.CheckConstraint(condition=Q(kind__in=['APPOINTMENT_STATUS', 'RECORD_CONTENT']), name='correction_kind_valid')),
        migrations.AddConstraint(model_name='correctionrequest', constraint=models.CheckConstraint(condition=Q(status__in=['OPEN', 'APPLIED', 'REJECTED', 'WITHDRAWN']), name='correction_status_valid')),
        migrations.AddConstraint(model_name='correctionrequest', constraint=models.CheckConstraint(condition=~Q(requester=F('reviewer')), name='correction_no_self_approval')),
        migrations.AddConstraint(model_name='correctionrequest', constraint=models.CheckConstraint(condition=Q(kind='APPOINTMENT_STATUS', base_record_version__isnull=True) | Q(kind='RECORD_CONTENT', base_record_version__isnull=False), name='correction_base_required')),
        migrations.AddConstraint(model_name='correctionrequest', constraint=models.CheckConstraint(condition=Q(status='APPLIED', reviewer__isnull=False, applied_at__isnull=False) | ~Q(status='APPLIED') & Q(applied_at__isnull=True), name='correction_applied_metadata')),
        migrations.AddConstraint(model_name='correctionrequest', constraint=models.UniqueConstraint(fields=['visit'], condition=Q(status='OPEN'), name='one_open_correction_per_visit')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.UniqueConstraint(fields=['visit', 'revision_no'], name='visit_revision_unique')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.UniqueConstraint(fields=['id', 'visit'], name='version_id_visit_unique')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.UniqueConstraint(fields=['visit'], condition=Q(state='DRAFT'), name='one_draft_per_visit')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.CheckConstraint(condition=Q(revision_no__gte=1), name='revision_positive')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.CheckConstraint(condition=Q(state__in=['DRAFT', 'PUBLISHED', 'ABANDONED']), name='version_state_valid')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.CheckConstraint(condition=Q(outcome__in=['TREATED', 'NO_TREATMENT']), name='version_outcome_valid')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.CheckConstraint(condition=Q(total_amount__gte=0, currency='CNY'), name='version_money_valid')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.CheckConstraint(condition=Q(state='PUBLISHED', published_at__isnull=False) | ~Q(state='PUBLISHED') & Q(published_at__isnull=True), name='version_publish_metadata')),
        migrations.AddConstraint(model_name='visitrecordversion', constraint=models.CheckConstraint(condition=~Q(previous_version=F('id')), name='version_not_previous_self')),
        migrations.AddConstraint(model_name='treatmentrecord', constraint=models.UniqueConstraint(fields=['record_version', 'line_no'], name='record_line_unique')),
        migrations.AddConstraint(model_name='treatmentrecord', constraint=models.CheckConstraint(condition=Q(line_no__gte=1, quantity__gt=0, unit_price__gte=0, line_amount__gte=0), name='record_values_valid')),
        migrations.AddConstraint(model_name='treatmentrecord', constraint=models.CheckConstraint(condition=Q(unit_price__gt=0) | ~Q(price_reason=''), name='zero_price_reason_required')),
        migrations.AddConstraint(model_name='treatmentrecord', constraint=models.CheckConstraint(condition=Q(confirmed_by__isnull=True, confirmed_at__isnull=True) | Q(confirmed_by__isnull=False, confirmed_at__isnull=False), name='line_confirmation_consistent')),
        migrations.AddIndex(model_name='auditevent', index=models.Index(fields=['subject_type', 'subject_key', 'recorded_at'], name='audit_subject_time_idx')),
    ]
