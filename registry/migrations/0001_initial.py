# Authored initial migration candidate. NOT generated or executed by Django here.
# Validate with: python manage.py makemigrations --check --dry-run
from django.db import models
from django.db.models import Q
from django.db import migrations
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone
from django.contrib.postgres.operations import BtreeGistExtension

def require_postgresql(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        raise RuntimeError('ADC requires PostgreSQL. SQLite is not an equivalent test or deployment backend.')


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.RunPython(require_postgresql, migrations.RunPython.noop),
        BtreeGistExtension(),
        migrations.CreateModel(name='Clinic', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('clinic_code', models.CharField(max_length=24, unique=True)),
        ('name', models.CharField(max_length=120)),
        ('postal_address', models.CharField(max_length=255)),
        ('supervisor_name', models.CharField(max_length=80)),
        ('phone', models.CharField(max_length=32)),
        ('email', models.EmailField()),
        ('area_sqm', models.DecimalField(max_digits=10, decimal_places=2)),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_clinic', 'ordering': ['clinic_code']}),
        migrations.CreateModel(name='Dentist', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('employee_no', models.CharField(max_length=24, unique=True)),
        ('name', models.CharField(max_length=80)),
        ('date_of_birth', models.DateField()),
        ('home_address', models.CharField(max_length=255)),
        ('phone', models.CharField(max_length=32)),
        ('email', models.EmailField()),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_dentist', 'ordering': ['employee_no']}),
        migrations.CreateModel(name='Qualification', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('code', models.CharField(max_length=24, unique=True)),
        ('name', models.CharField(max_length=120)),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_qualification'}),
        migrations.CreateModel(name='DentistQualification', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('notes', models.TextField(blank=True, default='')),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_dentist_qualification'}),
        migrations.CreateModel(name='Allergy', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('code', models.CharField(max_length=24, unique=True)),
        ('name', models.CharField(max_length=120)),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_allergy'}),
        migrations.CreateModel(name='TreatmentType', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('code', models.CharField(max_length=24, unique=True)),
        ('name', models.CharField(max_length=120)),
        ('unit_definition', models.CharField(max_length=120)),
        ('standard_unit_price', models.DecimalField(max_digits=12, decimal_places=2)),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_treatment_type'}),
        migrations.AddField(model_name='dentistqualification', name='dentist', field=models.ForeignKey('registry.Dentist', on_delete=models.PROTECT, related_name='qualifications')),
        migrations.AddField(model_name='dentistqualification', name='qualification', field=models.ForeignKey('registry.Qualification', on_delete=models.PROTECT)),
        migrations.AddConstraint(model_name='clinic', constraint=models.CheckConstraint(condition=Q(area_sqm__gt=0), name='clinic_area_positive')),
        migrations.AddConstraint(model_name='dentistqualification', constraint=models.UniqueConstraint(fields=['dentist', 'qualification'], name='dentist_qualification_unique')),
        migrations.AddConstraint(model_name='treatmenttype', constraint=models.CheckConstraint(condition=Q(standard_unit_price__gte=0), name='treatment_price_nonnegative')),
    ]
