"""Accountable internal maintenance; no clinical certification or implicit scheduling."""
from django.db import models
from django.db.models import Q,F

ACTIVE=('ASSIGNED','IN_PROGRESS','READY')
STATES=[('ASSIGNED','待开始'),('IN_PROGRESS','处理中'),('READY','待独立验收'),('CLOSED','已验收'),('CANCELLED','已取消')]
ACTIONS=[('OPEN','建立工单'),('START','开始处理'),('ASSIGN','调整责任与期限'),('SUBMIT','提交维修事实'),('RETURN','退回处理'),('WITHDRAW','撤回重核'),('APPROVE','验收并恢复设备'),('CANCEL','取消工单')]

class MaintenanceOrder(models.Model):
    asset=models.ForeignKey('equipment.EquipmentAsset',on_delete=models.PROTECT,related_name='maintenance_orders')
    maintenance_event=models.ForeignKey('equipment.EquipmentEvent',on_delete=models.PROTECT,related_name='maintenance_orders')
    issue=models.CharField(max_length=500)
    created_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='maintenance_created')
    created_at=models.DateTimeField(auto_now_add=True)
    assigned_to=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,related_name='maintenance_owned')
    due_on=models.DateField()
    state=models.CharField(max_length=12,choices=STATES,default='ASSIGNED')
    lock_version=models.PositiveIntegerField(default=0)
    performed_on=models.DateField(null=True,blank=True)
    cost=models.DecimalField(max_digits=16,decimal_places=2,null=True,blank=True)
    next_service_due=models.DateField(null=True,blank=True)
    completion_note=models.CharField(max_length=500,blank=True,default='')
    schedule_checked=models.BooleanField(default=False)
    submitted_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,null=True,blank=True,related_name='maintenance_submitted')
    submitted_at=models.DateTimeField(null=True,blank=True)
    reviewed_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT,null=True,blank=True,related_name='maintenance_reviewed')
    reviewed_at=models.DateTimeField(null=True,blank=True)
    review_reason=models.CharField(max_length=500,blank=True,default='')
    service_event=models.OneToOneField('equipment.EquipmentEvent',on_delete=models.PROTECT,null=True,blank=True,related_name='accepted_maintenance')
    class Meta:
        db_table='adc_maintenance_order'
        indexes=[models.Index(fields=['state','due_on'],name='maintenance_queue_idx')]
        constraints=[
            models.UniqueConstraint(fields=['asset'],condition=Q(state__in=ACTIVE),name='maintenance_one_active'),
            models.CheckConstraint(condition=Q(state__in=[s for s,l in STATES]),name='maintenance_state_valid'),
            models.CheckConstraint(condition=Q(cost__isnull=True)|Q(cost__gte=0),name='maintenance_cost_valid'),
            models.CheckConstraint(condition=Q(reviewed_by__isnull=True)|(~Q(reviewed_by=F('submitted_by'))&~Q(reviewed_by=F('assigned_to'))),name='maintenance_separate_review'),
            models.CheckConstraint(condition=(
                Q(state__in=['ASSIGNED','IN_PROGRESS','CANCELLED'],performed_on__isnull=True,cost__isnull=True,next_service_due__isnull=True,completion_note='',schedule_checked=False,submitted_by__isnull=True,submitted_at__isnull=True,reviewed_by__isnull=True,reviewed_at__isnull=True,service_event__isnull=True,review_reason='') |
                (Q(state__in=['READY','CLOSED'],performed_on__isnull=False,schedule_checked=True,submitted_by__isnull=False,submitted_by=F('assigned_to'),submitted_at__isnull=False)&~Q(completion_note='') &
                 (Q(state='READY',reviewed_by__isnull=True,reviewed_at__isnull=True,service_event__isnull=True,review_reason='')|
                  (Q(state='CLOSED',reviewed_by__isnull=False,reviewed_at__isnull=False,service_event__isnull=False)&~Q(review_reason=''))))
            ),name='maintenance_report_metadata'),
        ]

class MaintenanceAction(models.Model):
    order=models.ForeignKey(MaintenanceOrder,on_delete=models.PROTECT,related_name='actions')
    operation_id=models.UUIDField(unique=True,editable=False)
    sequence=models.PositiveIntegerField()
    action=models.CharField(max_length=10,choices=ACTIONS)
    actor=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    note=models.CharField(max_length=500)
    snapshot=models.JSONField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_maintenance_action'
        constraints=[models.UniqueConstraint(fields=['order','sequence'],name='maintenance_action_sequence'),models.CheckConstraint(condition=Q(action__in=[a for a,l in ACTIONS]),name='maintenance_action_valid')]
