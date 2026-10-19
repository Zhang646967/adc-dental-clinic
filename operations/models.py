from django.db import models
from django.db.models import Q, F
from operations.cancellation_policy import (BANDS, REASONS, FOLLOW_STATES, ACTION_STATES,
    KINDS, ASSESSMENTS, ACTION_NAMES)

class CancellationFollowUp(models.Model):
    visit = models.OneToOneField('scheduling.Visit', on_delete=models.PROTECT, related_name='cancellation_followup')
    reason_code = models.CharField(max_length=16, choices=REASONS, default='UNSUPPLIED')
    state = models.CharField(max_length=16, choices=FOLLOW_STATES, default='OPEN')
    assigned_to = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    due_on = models.DateField(null=True, blank=True)
    replacement_visit = models.ForeignKey('scheduling.Visit', null=True, blank=True, on_delete=models.PROTECT, related_name='cancellation_origins')
    note = models.CharField(max_length=500)
    lock_version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        db_table = 'adc_cancellation_followup'
        constraints = [
            models.CheckConstraint(condition=Q(reason_code__in=[k for k, _ in REASONS]), name='cancel_follow_reason'),
            models.CheckConstraint(condition=Q(state__in=[k for k, _ in FOLLOW_STATES]), name='cancel_follow_state'),
            models.CheckConstraint(condition=~Q(state__in=['OPEN', 'WAITING']) | Q(due_on__isnull=False), name='cancel_follow_pending_due'),
            models.CheckConstraint(condition=~Q(state='REBOOKED') | Q(replacement_visit__isnull=False), name='cancel_follow_booking'),
        ]

class AppointmentImprovement(models.Model):
    clinic = models.ForeignKey('registry.Clinic', on_delete=models.PROTECT)
    weekday = models.PositiveSmallIntegerField()
    band = models.CharField(max_length=8, choices=BANDS)
    baseline_start = models.DateField()
    baseline_end = models.DateField()
    kind = models.CharField(max_length=16, choices=KINDS)
    plan = models.CharField(max_length=500)
    assigned_to = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT, related_name='appointment_improvements')
    due_on = models.DateField()
    state = models.CharField(max_length=12, choices=ACTION_STATES, default='OPEN')
    execution = models.CharField(max_length=500, blank=True, default='')
    submitted_by = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    reviewed_by = models.ForeignKey('accounts.UserAccount', null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    review_start = models.DateField(null=True, blank=True)
    review_end = models.DateField(null=True, blank=True)
    assessment = models.CharField(max_length=16, choices=ASSESSMENTS, blank=True, default='')
    review_note = models.CharField(max_length=500, blank=True, default='')
    baseline = models.JSONField()
    comparison = models.JSONField(default=dict)
    lock_version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_appointment_improvement'
        indexes = [models.Index(fields=['clinic', 'state', 'due_on'], name='improve_clinic_state_due')]
        constraints = [
            models.CheckConstraint(condition=Q(weekday__gte=1, weekday__lte=7), name='improve_weekday'),
            models.CheckConstraint(condition=Q(band__in=[k for k, _ in BANDS]), name='improve_band'),
            models.CheckConstraint(condition=Q(baseline_end__gte=F('baseline_start')), name='improve_period'),
            models.CheckConstraint(condition=Q(state__in=[k for k, _ in ACTION_STATES]), name='improve_state'),
            models.CheckConstraint(condition=~Q(state='CLOSED') | (Q(submitted_by__isnull=False, reviewed_by__isnull=False, review_start__isnull=False, review_end__isnull=False) & ~Q(reviewed_by=F('submitted_by')) & ~Q(reviewed_by=F('assigned_to'))), name='improve_review_independent'),
        ]

class AppointmentActionEvent(models.Model):
    """Append-only command receipt and business history; no clinical text."""
    followup = models.ForeignKey(CancellationFollowUp, null=True, blank=True, on_delete=models.PROTECT, related_name='history')
    improvement = models.ForeignKey(AppointmentImprovement, null=True, blank=True, on_delete=models.PROTECT, related_name='history')
    operation_id = models.UUIDField(unique=True)
    actor = models.ForeignKey('accounts.UserAccount', on_delete=models.PROTECT)
    action = models.CharField(max_length=16)
    snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'adc_appointment_action_event'
        constraints = [models.CheckConstraint(condition=(Q(followup__isnull=False, improvement__isnull=True) | Q(followup__isnull=True, improvement__isnull=False)), name='appointment_event_one_owner')]
