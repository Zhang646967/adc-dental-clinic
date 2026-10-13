from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    initial=True
    dependencies=[migrations.swappable_dependency(settings.AUTH_USER_MODEL),('patients','0001_initial'),('registry','0001_initial'),('scheduling','0001_initial')]
    operations=[
migrations.CreateModel(name='WaitRequest',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('patient',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='patients.patient')),('clinic',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='registry.clinic')),('preferred_dentist',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='registry.dentist', null=True, blank=True)),('created_by',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='accounts.useraccount')),('earliest',models.DateTimeField()),('latest',models.DateTimeField()),
('state',models.CharField(choices=[('WAITING','等待安排'),('OFFERED','等待确认'),('BOOKED','已转预约'),('WITHDRAWN','已退出')],default='WAITING',max_length=12)),
('created_at',models.DateTimeField(auto_now_add=True)),('revision',models.PositiveIntegerField(default=0))],options={'db_table':'adc_wait_request','ordering':['created_at','id'],'constraints':[
models.CheckConstraint(condition=models.Q(latest__gt=models.F('earliest')),name='wait_time_order'),
models.CheckConstraint(condition=models.Q(state__in=['WAITING','OFFERED','BOOKED','WITHDRAWN']),name='wait_state_valid'),
models.UniqueConstraint(fields=['patient'],condition=models.Q(state__in=['WAITING','OFFERED']),name='wait_one_open_patient')]}),
migrations.CreateModel(name='SchedulePlan',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('clinic',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='registry.clinic')),('created_by',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='accounts.useraccount')),('created_at',models.DateTimeField(auto_now_add=True)),('suggestions',models.JSONField(default=list)),('metadata',models.JSONField(default=dict)),
('state',models.CharField(choices=[('DRAFT','待确认'),('PUBLISHED','已发出邀约')],default='DRAFT',max_length=12)),
('published_at',models.DateTimeField(null=True,blank=True))],options={'db_table':'adc_schedule_plan'}),
migrations.CreateModel(name='WaitOffer',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('request',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='coordination.waitrequest', related_name='offers')),('plan',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='coordination.scheduleplan', related_name='offers')),('slot',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='scheduling.availabilityslot')),('starts_at',models.DateTimeField()),('ends_at',models.DateTimeField()),('expires_at',models.DateTimeField()),
('state',models.CharField(choices=[('PENDING','等待确认'),('ACCEPTED','已接受'),('DECLINED','已拒绝'),('EXPIRED','已过期'),('REVOKED','已撤回')],default='PENDING',max_length=12)),
('visit',models.OneToOneField(null=True,blank=True,on_delete=django.db.models.deletion.PROTECT,to='scheduling.visit')),
('created_at',models.DateTimeField(auto_now_add=True))],options={'db_table':'adc_wait_offer','indexes':[models.Index(fields=['state','expires_at'],name='offer_expiry_idx')],'constraints':[
models.CheckConstraint(condition=models.Q(ends_at__gt=models.F('starts_at')),name='offer_time_order'),
models.CheckConstraint(condition=models.Q(expires_at__lte=models.F('starts_at')),name='offer_expires_before_visit'),
models.CheckConstraint(condition=models.Q(state__in=['PENDING','ACCEPTED','DECLINED','EXPIRED','REVOKED']),name='offer_state_valid'),
models.UniqueConstraint(fields=['request'],condition=models.Q(state='PENDING'),name='offer_one_pending_request'),
models.CheckConstraint(condition=models.Q(state='ACCEPTED',visit__isnull=False)|(~models.Q(state='ACCEPTED')&models.Q(visit__isnull=True)),name='offer_visit_state')]}),
]
