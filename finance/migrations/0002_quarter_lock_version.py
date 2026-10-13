from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[("finance","0001_initial")]
    operations=[migrations.AddField(model_name="quarter", name="lock_version", field=models.PositiveIntegerField(default=0))]
