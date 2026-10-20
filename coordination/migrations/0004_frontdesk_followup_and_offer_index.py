from django.db import migrations,models

class Migration(migrations.Migration):
    dependencies=[('coordination','0003_waitrequest_service')]
    operations=[
        migrations.AddField(model_name='coordinationtask',name='due_at',field=models.DateTimeField(null=True,blank=True)),
        migrations.AddIndex(model_name='waitoffer',index=models.Index(fields=['slot','state','expires_at'],name='offer_slot_state_exp_idx')),
    ]
