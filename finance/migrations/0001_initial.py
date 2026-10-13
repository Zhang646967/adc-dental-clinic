# Authored initial migration candidate. NOT generated or executed by Django here.
# Validate with: python manage.py makemigrations --check --dry-run
from django.db import models
from django.db.models import Q
from django.db import migrations
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True
    dependencies = [('accounts', '0001_initial'), ('registry', '0001_initial')]
    operations = [
        migrations.CreateModel(name='Quarter', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('year', models.PositiveSmallIntegerField()),
        ('quarter_no', models.PositiveSmallIntegerField()),
        ('roster_status', models.CharField(max_length=12, default='DRAFT', choices=[('DRAFT', '未确认'), ('CONFIRMED', '已确认')])),
        ('roster_confirmed_at', models.DateTimeField(null=True, blank=True)),
        ], options={'db_table': 'adc_quarter'}),
        migrations.CreateModel(name='DentistQuarterCost', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('cost_status', models.CharField(max_length=12, default='MISSING', choices=[('MISSING', '未录入'), ('DRAFT', '草稿'), ('CONFIRMED', '已确认')])),
        ('supply_cost', models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)),
        ('operating_expense', models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)),
        ('confirmed_at', models.DateTimeField(null=True, blank=True)),
        ('notes', models.TextField(blank=True, default='')),
        ], options={'db_table': 'adc_dentist_quarter_cost'}),
        migrations.AddField(model_name='quarter', name='roster_confirmed_by', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddField(model_name='dentistquartercost', name='quarter', field=models.ForeignKey('finance.Quarter', on_delete=models.PROTECT, related_name='dentist_costs')),
        migrations.AddField(model_name='dentistquartercost', name='dentist', field=models.ForeignKey('registry.Dentist', on_delete=models.PROTECT)),
        migrations.AddField(model_name='dentistquartercost', name='confirmed_by', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddConstraint(model_name='quarter', constraint=models.UniqueConstraint(fields=['year', 'quarter_no'], name='quarter_unique')),
        migrations.AddConstraint(model_name='quarter', constraint=models.CheckConstraint(condition=Q(year__gte=1900, year__lte=9998, quarter_no__gte=1, quarter_no__lte=4), name='quarter_range_valid')),
        migrations.AddConstraint(model_name='quarter', constraint=models.CheckConstraint(condition=Q(roster_status='CONFIRMED', roster_confirmed_by__isnull=False, roster_confirmed_at__isnull=False) | Q(roster_status='DRAFT', roster_confirmed_by__isnull=True, roster_confirmed_at__isnull=True), name='quarter_confirmation_valid')),
        migrations.AddConstraint(model_name='dentistquartercost', constraint=models.UniqueConstraint(fields=['quarter', 'dentist'], name='dentist_quarter_unique')),
        migrations.AddConstraint(model_name='dentistquartercost', constraint=models.CheckConstraint(condition=Q(cost_status__in=['MISSING', 'DRAFT', 'CONFIRMED']), name='cost_status_valid')),
        migrations.AddConstraint(model_name='dentistquartercost', constraint=models.CheckConstraint(condition=(Q(supply_cost__isnull=True) | Q(supply_cost__gte=0)) & (Q(operating_expense__isnull=True) | Q(operating_expense__gte=0)), name='cost_nonnegative')),
        migrations.AddConstraint(model_name='dentistquartercost', constraint=models.CheckConstraint(condition=Q(cost_status='CONFIRMED', supply_cost__isnull=False, operating_expense__isnull=False, confirmed_by__isnull=False, confirmed_at__isnull=False) | ~Q(cost_status='CONFIRMED') & Q(confirmed_by__isnull=True, confirmed_at__isnull=True), name='cost_confirmation_valid')),
        migrations.AddConstraint(model_name='dentistquartercost', constraint=models.CheckConstraint(condition=~Q(cost_status='MISSING') | Q(supply_cost__isnull=True, operating_expense__isnull=True), name='missing_cost_is_null')),
    ]
