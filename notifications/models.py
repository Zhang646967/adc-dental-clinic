from django.db import models
from django.db.models import Q
from django.utils import timezone


class NotificationOutbox(models.Model):
    """Durable intent committed alongside a task and its immutable audit event."""
    source_event = models.OneToOneField('care.AuditEvent', on_delete=models.PROTECT, related_name='notice_outbox')
    task = models.ForeignKey('coordination.CoordinationTask', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    task_revision = models.PositiveBigIntegerField()
    action = models.CharField(max_length=12)
    event_state = models.CharField(max_length=12)
    occurred_at = models.DateTimeField()
    recipients = models.JSONField(default=list)
    state = models.CharField(max_length=16, default='PENDING')
    attempts = models.PositiveSmallIntegerField(default=0)
    retry_round = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, null=True)
    completed_at = models.DateTimeField(null=True)
    delivered_count = models.PositiveIntegerField(default=0)
    suppressed_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=24, default='', blank=True)

    class Meta:
        db_table = 'adc_notification_outbox'
        indexes = [models.Index(fields=['state', 'next_attempt_at', 'id'], name='notice_due_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=['PENDING','DELIVERED','NO_RECIPIENTS','FAILED']), name='notice_state_valid'),
            models.CheckConstraint(condition=Q(attempts__lte=5), name='notice_attempt_limit'),
            models.CheckConstraint(condition=(Q(state='PENDING', next_attempt_at__isnull=False, completed_at__isnull=True) |
                (~Q(state='PENDING') & Q(next_attempt_at__isnull=True, completed_at__isnull=False))), name='notice_timing_valid'),
            models.CheckConstraint(condition=~Q(state='DELIVERED') | Q(delivered_count__gt=0), name='notice_delivery_nonzero'),
        ]


class InboxMessage(models.Model):
    """One row per original recipient grant; read_at is explicit acknowledgement only."""
    event = models.ForeignKey(NotificationOutbox, on_delete=models.PROTECT, related_name='messages')
    recipient = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    grant = models.ForeignKey('accounts.RoleAssignment', on_delete=models.PROTECT)
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    role = models.CharField(max_length=16)
    delivered_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True)

    class Meta:
        db_table = 'adc_inbox_message'
        indexes = [models.Index(fields=['recipient','clinic','role','read_at'], name='inbox_scope_idx')]
        constraints = [
            models.UniqueConstraint(fields=['event','grant'], name='inbox_event_grant_unique'),
            models.CheckConstraint(condition=Q(role__in=['FRONT_DESK','MANAGER']), name='inbox_role_valid'),
            models.CheckConstraint(condition=Q(read_at__isnull=True) | Q(read_at__gte=models.F('delivered_at')), name='inbox_read_after_delivery'),
        ]
