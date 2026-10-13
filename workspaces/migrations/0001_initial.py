import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL), ('registry','0001_initial')]
    operations = [migrations.CreateModel(name='WorkspaceContext', fields=[
        ('id',models.UUIDField(default=uuid.uuid4,editable=False,primary_key=True,serialize=False)),
        ('role',models.CharField(blank=True,default='',max_length=16)),
        ('revision',models.PositiveIntegerField(default=0)),
        ('updated_at',models.DateTimeField(auto_now=True)),
        ('clinic',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,to='registry.clinic')),
        ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,to=settings.AUTH_USER_MODEL)),
    ], options={'db_table':'adc_workspace_context','constraints':[
        models.CheckConstraint(condition=models.Q(('clinic__isnull',True),('role__in',['MANAGER','FRONT_DESK']),_connector='OR'),name='workspace_clinic_role')
    ]})]
