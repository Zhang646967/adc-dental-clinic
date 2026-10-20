from django.db import models
from django.db.models import Q,F

class WaitRequest(models.Model):
    patient=models.ForeignKey('patients.Patient',on_delete=models.PROTECT)
    clinic=models.ForeignKey('registry.Clinic',on_delete=models.PROTECT)
    service=models.ForeignKey('scheduling.BookingService',null=True,blank=True,on_delete=models.PROTECT)
    preferred_dentist=models.ForeignKey('registry.Dentist',null=True,blank=True,on_delete=models.PROTECT)
    earliest=models.DateTimeField()
    latest=models.DateTimeField()
    state=models.CharField(max_length=12,default='WAITING',choices=[('WAITING','等待安排'),('OFFERED','等待确认'),('BOOKED','已转预约'),('WITHDRAWN','已退出')])
    created_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    revision=models.PositiveIntegerField(default=0)
    class Meta:
        db_table='adc_wait_request'
        ordering=['created_at','id']
        constraints=[models.CheckConstraint(condition=Q(latest__gt=F('earliest')),name='wait_time_order'),
          models.CheckConstraint(condition=Q(state__in=['WAITING','OFFERED','BOOKED','WITHDRAWN']),name='wait_state_valid'),
          models.UniqueConstraint(fields=['patient'],condition=Q(state__in=['WAITING','OFFERED']),name='wait_one_open_patient')]

class SchedulePlan(models.Model):
    CONTRACT='FRONT-DESK-SCHEDULING-1'
    clinic=models.ForeignKey('registry.Clinic',on_delete=models.PROTECT)
    created_by=models.ForeignKey('accounts.UserAccount',on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    suggestions=models.JSONField(default=list)
    metadata=models.JSONField(default=dict)
    state=models.CharField(max_length=12,default='DRAFT',choices=[('DRAFT','待确认'),('PUBLISHED','已发出邀约')])
    published_at=models.DateTimeField(null=True,blank=True)
    class Meta: db_table='adc_schedule_plan'

class WaitOffer(models.Model):
    request=models.ForeignKey(WaitRequest,on_delete=models.PROTECT,related_name='offers')
    plan=models.ForeignKey(SchedulePlan,on_delete=models.PROTECT,related_name='offers')
    slot=models.ForeignKey('scheduling.AvailabilitySlot',on_delete=models.PROTECT)
    starts_at=models.DateTimeField()
    ends_at=models.DateTimeField()
    expires_at=models.DateTimeField()
    state=models.CharField(max_length=12,default='PENDING',choices=[('PENDING','等待确认'),('ACCEPTED','已接受'),('DECLINED','已拒绝'),('EXPIRED','已过期'),('REVOKED','已撤回')])
    visit=models.OneToOneField('scheduling.Visit',null=True,blank=True,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table='adc_wait_offer'
        constraints=[models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')),name='offer_time_order'),
            models.CheckConstraint(condition=Q(expires_at__lte=F('starts_at')),name='offer_expires_before_visit'),
            models.CheckConstraint(condition=Q(state__in=['PENDING','ACCEPTED','DECLINED','EXPIRED','REVOKED']),name='offer_state_valid'),
            models.UniqueConstraint(fields=['request'],condition=Q(state='PENDING'),name='offer_one_pending_request'),
            models.CheckConstraint(condition=Q(state='ACCEPTED',visit__isnull=False)|(~Q(state='ACCEPTED')&Q(visit__isnull=True)),name='offer_visit_state')]
        indexes=[models.Index(fields=['state','expires_at'],name='offer_expiry_idx'),
            models.Index(fields=['slot','state','expires_at'],name='offer_slot_state_exp_idx')]


class CoordinationTask(models.Model):
    """Workflow record, NOT a stop order, appointment or patient consent."""
    slot = models.ForeignKey('scheduling.AvailabilitySlot', on_delete=models.PROTECT,
                             related_name='coordination_tasks')
    purpose = models.CharField(max_length=12, choices=[('DEACTIVATE','为停用原出诊协调'),('REPLACE','为调整原出诊协调')])
    opening_reason = models.CharField(max_length=24, choices=[('PLAN_CHANGE','出诊计划变化'),('STAFF_UNAVAILABLE','人员安排变化')])
    creation_operation = models.UUIDField(unique=True, editable=False)
    state = models.CharField(max_length=12, default='OPEN', choices=[('OPEN','待前台受理'),('IN_PROGRESS','前台协调中'),('READY','待主管复核'),('CLOSED','协调核对已通过'),('CANCELLED','任务已撤销')])
    created_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='coordination_tasks_created')
    assignee = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='coordination_tasks_assigned')
    due_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='coordination_tasks_submitted')
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_digest = models.CharField(max_length=64, default='', blank=True)
    closed_by = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, null=True, blank=True, related_name='coordination_tasks_closed')
    closed_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'adc_coordination_task'
        ordering = ['-created_at','-id']
        indexes = [models.Index(fields=['state','created_at'],name='coord_task_queue_idx')]
        constraints = [
            models.UniqueConstraint(fields=['slot'], condition=Q(state__in=['OPEN','IN_PROGRESS','READY']), name='coord_task_one_active_slot'),
            models.CheckConstraint(condition=Q(state__in=['OPEN','IN_PROGRESS','READY','CLOSED','CANCELLED']),name='coord_task_state_valid'),
            models.CheckConstraint(condition=Q(purpose__in=['DEACTIVATE','REPLACE']),name='coord_task_purpose_valid'),
            models.CheckConstraint(condition=Q(opening_reason__in=['PLAN_CHANGE','STAFF_UNAVAILABLE']),name='coord_task_reason_valid'),
            models.CheckConstraint(condition=Q(state='OPEN',assignee__isnull=True) | Q(state__in=['IN_PROGRESS','READY','CLOSED'],assignee__isnull=False) | Q(state='CANCELLED'),name='coord_task_owner_valid'),
            models.CheckConstraint(condition=(Q(state__in=['READY','CLOSED'],submitted_by__isnull=False,submitted_at__isnull=False) & ~Q(submitted_digest='')) | (~Q(state__in=['READY','CLOSED']) & Q(submitted_by__isnull=True,submitted_at__isnull=True,submitted_digest='')),name='coord_task_submit_valid'),
            models.CheckConstraint(condition=~Q(state__in=['READY','CLOSED']) | Q(submitted_by=F('assignee')),name='coord_task_submit_owner'),
            models.CheckConstraint(condition=Q(state__in=['CLOSED','CANCELLED'],closed_by__isnull=False,closed_at__isnull=False) | (~Q(state__in=['CLOSED','CANCELLED']) & Q(closed_by__isnull=True,closed_at__isnull=True)),name='coord_task_close_valid'),
            models.CheckConstraint(condition=~Q(state='CLOSED') | ~Q(closed_by=F('submitted_by')),name='coord_task_separate_review'),
        ]
