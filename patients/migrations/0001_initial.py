# Authored initial migration candidate. NOT generated or executed by Django here.
# Validate with: python manage.py makemigrations --check --dry-run
from django.db import models
from django.db.models import Q
from adc_core.identifiers import patient_no
from django.db import migrations
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True
    dependencies = [('registry', '0001_initial')]
    operations = [
        migrations.CreateModel(name='Patient', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('patient_no', models.CharField(max_length=40, unique=True, default=patient_no, editable=False)),
        ('name', models.CharField(max_length=80)),
        ('date_of_birth', models.DateField()),
        ('billing_address', models.CharField(max_length=255)),
        ('phone', models.CharField(max_length=32)),
        ('email', models.EmailField(blank=True, default='')),
        ('emergency_name', models.CharField(max_length=80)),
        ('emergency_phone', models.CharField(max_length=32)),
        ('allergy_status', models.CharField(max_length=12, default='UNKNOWN', choices=[('UNKNOWN', '未询问/未知'), ('NO_KNOWN', '已确认无已知过敏'), ('KNOWN', '已知过敏')])),
        ('allergy_info_version', models.PositiveIntegerField(default=1)),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_patient', 'ordering': ['-id']}),
        migrations.CreateModel(name='PatientAllergy', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('notes', models.TextField(blank=True, default='')),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_patient_allergy'}),
        migrations.AddField(model_name='patient', name='created_in_clinic', field=models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, related_name='registered_patients')),
        migrations.AddField(model_name='patientallergy', name='patient', field=models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='allergy_links')),
        migrations.AddField(model_name='patientallergy', name='allergy', field=models.ForeignKey('registry.Allergy', on_delete=models.PROTECT)),
        migrations.AddConstraint(model_name='patient', constraint=models.CheckConstraint(condition=Q(allergy_status__in=['UNKNOWN', 'NO_KNOWN', 'KNOWN']), name='patient_allergy_status_valid')),
        migrations.AddConstraint(model_name='patient', constraint=models.CheckConstraint(condition=Q(allergy_info_version__gte=1), name='allergy_version_positive')),
        migrations.AddIndex(model_name='patient', index=models.Index(fields=['phone'], name='patient_phone_idx')),
        migrations.AddConstraint(model_name='patientallergy', constraint=models.UniqueConstraint(fields=['patient', 'allergy'], name='patient_allergy_unique')),
    ]
