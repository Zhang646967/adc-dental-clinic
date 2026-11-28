from django.db import migrations, models


def preserve_site_projects(apps, schema_editor):
    projects = apps.get_model('clinical', 'ExaminationProject').objects.using(schema_editor.connection.alias)
    if projects.exclude(operating_mode='REHEARSAL').exists():
        raise RuntimeError('已有机构检查项目，回退会删除其开通范围。请使用已验证的备份恢复。')


class Migration(migrations.Migration):
    dependencies = [('clinical', '0023_examination_followup')]
    operations = [
        migrations.AddField(
            model_name='examinationproject', name='operating_mode',
            field=models.CharField(choices=[('REHEARSAL', '演练项目'), ('SITE', '门店已开通'),
                ('SUSPENDED', '门店已暂停')], default='REHEARSAL', max_length=10)),
        migrations.AddField(
            model_name='examinationproject', name='operating_revision',
            field=models.PositiveBigIntegerField(default=1)),
        migrations.AddConstraint(
            model_name='examinationproject',
            constraint=models.CheckConstraint(condition=models.Q(operating_mode__in=['REHEARSAL', 'SITE', 'SUSPENDED']),
                                              name='examination_project_mode_valid')),
        migrations.RunPython(migrations.RunPython.noop, preserve_site_projects),
    ]
