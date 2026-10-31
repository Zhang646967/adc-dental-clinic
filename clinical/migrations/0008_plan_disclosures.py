from django.db import migrations, models


def preserve_disclosures(apps, schema_editor):
    versions = apps.get_model('clinical', 'PlanVersion').objects.using(schema_editor.connection.alias)
    drafts = apps.get_model('clinical', 'PlanDraft').objects.using(schema_editor.connection.alias)
    if versions.exclude(disclosures={}).exists() or drafts.filter(
            payload__has_key='disclosures').exclude(payload__disclosures={}).exists():
        raise RuntimeError('Retained treatment explanations exist; do not remove their storage.')


class Migration(migrations.Migration):
    dependencies = [('clinical', '0007_outpatient_documents')]
    operations = [
        migrations.AddField(model_name='planversion', name='disclosures',
                            field=models.JSONField(default=dict, db_default={})),
        migrations.RunPython(migrations.RunPython.noop, reverse_code=preserve_disclosures),
    ]
