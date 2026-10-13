# Authored initial migration candidate. NOT generated or executed by Django here.
# Validate with: python manage.py makemigrations --check --dry-run
from django.db import models
from django.db.models import F, Q
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from adc_core.identifiers import visit_no
from adc_core.db import TsTzRange
from django.db import migrations
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True
    dependencies = [('registry', '0001_initial'), ('patients', '0001_initial')]
    operations = [
        migrations.CreateModel(name='AvailabilitySlot', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('starts_at', models.DateTimeField()),
        ('ends_at', models.DateTimeField()),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_availability_slot', 'ordering': ['starts_at', 'id']}),
        migrations.CreateModel(name='Visit', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('visit_no', models.CharField(max_length=40, unique=True, default=visit_no, editable=False)),
        ('scheduled_start', models.DateTimeField()),
        ('scheduled_end', models.DateTimeField()),
        ('status', models.CharField(max_length=24, choices=(('SCHEDULED', '已预约'), ('CHECKED_IN', '已到诊'), ('COMPLETED', '治疗完成'), ('CLOSED_NO_TREATMENT', '无治疗关闭'), ('CANCELLED', '已取消'), ('NO_SHOW', '已爽约'), ('RESCHEDULED', '已改期替代')), default='SCHEDULED')),
        ('attended', models.BooleanField(default=False)),
        ('attended_at', models.DateTimeField(null=True, blank=True)),
        ('completed_at', models.DateTimeField(null=True, blank=True)),
        ('chief_complaint', models.TextField(blank=True, default='')),
        ('special_needs', models.TextField(blank=True, default='')),
        ('cancellation_party', models.CharField(max_length=8, blank=True, default='', choices=[('', '不适用'), ('PATIENT', '患者'), ('CLINIC', '诊所')])),
        ('cancellation_reason', models.TextField(blank=True, default='')),
        ('lock_version', models.PositiveIntegerField(default=0)),
        ('created_at', models.DateTimeField(auto_now_add=True)),
        ], options={'db_table': 'adc_visit', 'ordering': ['-scheduled_start', '-id']}),
        migrations.CreateModel(name='VisitRequest', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('description', models.CharField(max_length=500)),
        ], options={'db_table': 'adc_visit_request'}),
        migrations.AddField(model_name='availabilityslot', name='dentist', field=models.ForeignKey('registry.Dentist', on_delete=models.PROTECT)),
        migrations.AddField(model_name='availabilityslot', name='clinic', field=models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)),
        migrations.AddField(model_name='visit', name='patient', field=models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='visits')),
        migrations.AddField(model_name='visit', name='dentist', field=models.ForeignKey('registry.Dentist', on_delete=models.PROTECT, related_name='visits')),
        migrations.AddField(model_name='visit', name='clinic', field=models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='visits')),
        migrations.AddField(model_name='visit', name='availability_slot', field=models.ForeignKey('scheduling.AvailabilitySlot', on_delete=models.PROTECT, related_name='visits')),
        migrations.AddField(model_name='visit', name='replaces_visit', field=models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, null=True, blank=True, related_name='replacement')),
        migrations.AddField(model_name='visitrequest', name='visit', field=models.ForeignKey('scheduling.Visit', on_delete=models.PROTECT, related_name='requests')),
        migrations.AddField(model_name='visitrequest', name='treatment_type', field=models.ForeignKey('registry.TreatmentType', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddConstraint(model_name='availabilityslot', constraint=models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')), name='slot_time_order')),
        migrations.AddConstraint(model_name='availabilityslot', constraint=ExclusionConstraint(name='slot_dentist_no_overlap', expressions=[(TsTzRange('starts_at', 'ends_at', RangeBoundary()), RangeOperators.OVERLAPS), ('dentist', RangeOperators.EQUAL)], condition=Q(is_active=True))),
        migrations.AddConstraint(model_name='visit', constraint=models.CheckConstraint(condition=Q(status__in=['SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT', 'CANCELLED', 'NO_SHOW', 'RESCHEDULED']), name='visit_status_valid')),
        migrations.AddConstraint(model_name='visit', constraint=models.CheckConstraint(condition=Q(scheduled_end__gt=F('scheduled_start')), name='visit_time_order')),
        migrations.AddConstraint(model_name='visit', constraint=models.CheckConstraint(condition=Q(status__in=('CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT'), attended=True, attended_at__isnull=False) | ~Q(status__in=('CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT')) & Q(attended=False, attended_at__isnull=True), name='visit_attendance_consistent')),
        migrations.AddConstraint(model_name='visit', constraint=models.CheckConstraint(condition=Q(status__in=('COMPLETED', 'CLOSED_NO_TREATMENT')) & Q(completed_at__isnull=False, completed_at__gte=F('attended_at')) | ~Q(status__in=('COMPLETED', 'CLOSED_NO_TREATMENT')) & Q(completed_at__isnull=True), name='visit_completion_consistent')),
        migrations.AddConstraint(model_name='visit', constraint=models.CheckConstraint(condition=Q(status='CANCELLED', cancellation_party__in=['PATIENT', 'CLINIC']) & ~Q(cancellation_reason='') | ~Q(status='CANCELLED') & Q(cancellation_party='', cancellation_reason=''), name='visit_cancellation_consistent')),
        migrations.AddConstraint(model_name='visit', constraint=models.CheckConstraint(condition=~Q(replaces_visit=F('id')), name='visit_not_replace_self')),
        migrations.AddConstraint(model_name='visit', constraint=ExclusionConstraint(name='visit_dentist_no_overlap', expressions=[(TsTzRange('scheduled_start', 'scheduled_end', RangeBoundary()), RangeOperators.OVERLAPS), ('dentist', RangeOperators.EQUAL)], condition=Q(status__in=('SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT')))),
        migrations.AddConstraint(model_name='visit', constraint=ExclusionConstraint(name='visit_patient_no_overlap', expressions=[(TsTzRange('scheduled_start', 'scheduled_end', RangeBoundary()), RangeOperators.OVERLAPS), ('patient', RangeOperators.EQUAL)], condition=Q(status__in=('SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT')))),
        migrations.AddIndex(model_name='visit', index=models.Index(fields=['clinic', 'scheduled_start'], name='visit_clinic_time_idx')),
        migrations.AddIndex(model_name='visit', index=models.Index(fields=['dentist', 'completed_at'], name='visit_dentist_completed_idx')),
    ]
