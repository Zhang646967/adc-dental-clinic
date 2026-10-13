# Authored initial migration candidate. NOT generated or executed by Django here.
# Validate with: python manage.py makemigrations --check --dry-run
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db import migrations
import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone

class Migration(migrations.Migration):
    initial = True
    dependencies = [('auth', '0012_alter_user_first_name_max_length'), ('registry', '0001_initial')]
    operations = [
        migrations.CreateModel(name='UserAccount', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),

        ('password', models.CharField(max_length=128, verbose_name='password')),
        ('last_login', models.DateTimeField(blank=True, null=True, verbose_name='last login')),
        ('is_superuser', models.BooleanField(default=False, help_text='Designates that this user has all permissions without explicitly assigning them.', verbose_name='superuser status')),
        ('username', models.CharField(error_messages={'unique': 'A user with that username already exists.'}, help_text='Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only.', max_length=150, unique=True, validators=[django.contrib.auth.validators.UnicodeUsernameValidator()], verbose_name='username')),
        ('first_name', models.CharField(blank=True, max_length=150, verbose_name='first name')),
        ('last_name', models.CharField(blank=True, max_length=150, verbose_name='last name')),
        ('email', models.EmailField(blank=True, max_length=254, verbose_name='email address')),
        ('is_staff', models.BooleanField(default=False, help_text='Designates whether the user can log into this admin site.', verbose_name='staff status')),
        ('is_active', models.BooleanField(default=True, help_text='Designates whether this user should be treated as active. Unselect this instead of deleting accounts.', verbose_name='active')),
        ('date_joined', models.DateTimeField(default=django.utils.timezone.now, verbose_name='date joined')),
        ('groups', models.ManyToManyField(blank=True, help_text='The groups this user belongs to. A user will get all permissions granted to each of their groups.', related_name='user_set', related_query_name='user', to='auth.group', verbose_name='groups')),
        ('user_permissions', models.ManyToManyField(blank=True, help_text='Specific permissions for this user.', related_name='user_set', related_query_name='user', to='auth.permission', verbose_name='user permissions')),

        ], options={'db_table': 'adc_user', 'verbose_name': '员工账号', 'verbose_name_plural': '员工账号'}, managers=[('objects', django.contrib.auth.models.UserManager())]),
        migrations.CreateModel(name='RoleAssignment', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('role', models.CharField(max_length=16, choices=(('FRONT_DESK', '前台'), ('DENTIST', '牙医'), ('MANAGER', '诊所主管'), ('HQ', '总部管理'), ('FINANCE', '财务'), ('SYSADMIN', '系统管理员')))),
        ('scope_kind', models.CharField(max_length=16, choices=(('CLINIC', '诊所'), ('SELF_DENTIST', '本人接诊'), ('CHAIN', '全链'), ('TECHNICAL', '技术管理')))),
        ('is_active', models.BooleanField(default=True)),
        ], options={'db_table': 'adc_role_assignment'}),
        migrations.AddField(model_name='useraccount', name='dentist', field=models.OneToOneField('registry.Dentist', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddField(model_name='roleassignment', name='user', field=models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='role_assignments')),
        migrations.AddField(model_name='roleassignment', name='clinic', field=models.ForeignKey('registry.Clinic', on_delete=models.PROTECT, null=True, blank=True)),
        migrations.AddConstraint(model_name='roleassignment', constraint=models.CheckConstraint(condition=Q(role__in=['FRONT_DESK', 'MANAGER'], scope_kind='CLINIC', clinic__isnull=False) | Q(role='DENTIST', scope_kind='SELF_DENTIST', clinic__isnull=True) | Q(role__in=['HQ', 'FINANCE'], scope_kind='CHAIN', clinic__isnull=True) | Q(role='SYSADMIN', scope_kind='TECHNICAL', clinic__isnull=True), name='role_scope_valid')),
        migrations.AddConstraint(model_name='roleassignment', constraint=models.UniqueConstraint(fields=['user', 'role', 'scope_kind', 'clinic'], condition=Q(clinic__isnull=False), name='role_clinic_unique')),
        migrations.AddConstraint(model_name='roleassignment', constraint=models.UniqueConstraint(fields=['user', 'role', 'scope_kind'], condition=Q(clinic__isnull=True), name='role_noclinic_unique')),
    ]
