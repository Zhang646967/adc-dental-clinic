"""Additive admission state. Old migrations stay byte-for-byte unchanged.
Old application binaries ignore the new state: do not downgrade while operating
this feature. Reverse migration refuses when pause history would be discarded.
"""
from django.db import migrations, models


def guard_reverse(apps, schema_editor):
    Slot = apps.get_model('scheduling', 'AvailabilitySlot')
    if Slot.objects.using(schema_editor.connection.alias).filter(intake_revision__gt=0).exists() or Slot.objects.using(schema_editor.connection.alias).filter(booking_paused=True).exists():
        raise RuntimeError('接收控制已被使用，不能直接删列降级。请停写并按私密备份/恢复计划处理。')


class Migration(migrations.Migration):
    dependencies = [('scheduling', '0001_initial')]
    operations = [
        migrations.AddField(model_name='availabilityslot', name='booking_paused', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='availabilityslot', name='intake_revision', field=models.PositiveIntegerField(default=0)),
        migrations.RunPython(migrations.RunPython.noop, guard_reverse),
    ]
