from django.db import migrations, models
import django.db.models.deletion


def preserve_service_content(apps, schema_editor):
    model = apps.get_model('scheduling', 'ServicePresentation')
    if model.objects.using(schema_editor.connection.alias).exists():
        raise RuntimeError('Service descriptions exist. Preserve and review them before reversing this migration.')


class Migration(migrations.Migration):
    dependencies = [('scheduling', '0005_scheduling_relations_and_calendar')]
    operations = [migrations.CreateModel(
        name='ServicePresentation',
        fields=[
            ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
            ('category', models.CharField(choices=[('CHECKUP', '口腔检查与初诊'), ('PREVENTION', '洁牙与牙龈护理'),
                ('RESTORATION', '牙痛与牙体修复'), ('CHILDREN', '儿童口腔就诊'), ('ORTHODONTICS', '牙齿排列与正畸咨询'),
                ('REPLACEMENT', '缺牙修复咨询'), ('FOLLOWUP', '复诊与治疗后复查'), ('IMAGING', '影像检查相关评估'),
                ('OTHER', '其他就诊服务')], default='OTHER', max_length=24)),
            ('title', models.CharField(blank=True, default='', max_length=100)),
            ('summary', models.CharField(blank=True, default='', max_length=240)),
            ('suitable_for', models.TextField(blank=True, default='', max_length=1600)),
            ('visit_content', models.TextField(blank=True, default='', max_length=2400)),
            ('limitations', models.TextField(blank=True, default='', max_length=1600)),
            ('preparation', models.TextField(blank=True, default='', max_length=1600)),
            ('fee_mode', models.CharField(choices=[('ASSESSED', '评估后确认费用'), ('FIXED', '本次服务固定费用'),
                ('FROM', '本次服务起价')], default='ASSESSED', max_length=12)),
            ('fee_amount', models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
            ('fee_note', models.TextField(blank=True, default='', max_length=1600)),
            ('is_published', models.BooleanField(default=False)),
            ('updated_at', models.DateTimeField(auto_now=True)),
            ('service', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,
                related_name='patient_presentation', to='scheduling.bookingservice')),
        ],
        options={'db_table': 'adc_service_presentation', 'ordering': ['category', 'title', 'pk'],
            'constraints': [models.CheckConstraint(condition=(
                models.Q(fee_mode='ASSESSED', fee_amount__isnull=True) |
                models.Q(fee_mode__in=['FIXED', 'FROM'], fee_amount__isnull=False, fee_amount__gte=0)),
                name='service_presentation_fee_valid')]},
    ), migrations.RunPython(migrations.RunPython.noop, preserve_service_content)]
