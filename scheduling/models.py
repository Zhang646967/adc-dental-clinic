from django.db import models
from django.db.models import F, Q
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from adc_core.identifiers import visit_no
from adc_core.rules import STATUS_CHOICES, ATTENDED_STATUSES, CLOSED_STATUSES, OCCUPYING_STATUSES

from adc_core.db import TsTzRange

class AvailabilitySlot(models.Model):
    dentist = models.ForeignKey("registry.Dentist", on_delete=models.PROTECT)
    clinic = models.ForeignKey("registry.Clinic", on_delete=models.PROTECT)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    # A pause never invalidates visits/holds or releases dentist availability.
    booking_paused = models.BooleanField(default=False)
    intake_revision = models.PositiveIntegerField(default=0)
    class Meta:
        db_table = "adc_availability_slot"
        ordering = ["starts_at", "id"]
        indexes = [models.Index(fields=['clinic','starts_at'],name='slot_clinic_start_idx')]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="slot_time_order"),
            ExclusionConstraint(name="slot_dentist_no_overlap", expressions=[(TsTzRange("starts_at", "ends_at", RangeBoundary()), RangeOperators.OVERLAPS), ("dentist", RangeOperators.EQUAL)], condition=Q(is_active=True)),
        ]
    def __str__(self):
        from django.utils.timezone import localtime
        return f"{self.clinic.name} / {self.dentist.name} / {localtime(self.starts_at):%m-%d %H:%M}–{localtime(self.ends_at):%H:%M}"

class Visit(models.Model):
    visit_no = models.CharField(max_length=40, unique=True, default=visit_no, editable=False)
    patient = models.ForeignKey("patients.Patient", on_delete=models.PROTECT, related_name="visits")
    dentist = models.ForeignKey("registry.Dentist", on_delete=models.PROTECT, related_name="visits")
    clinic = models.ForeignKey("registry.Clinic", on_delete=models.PROTECT, related_name="visits")
    availability_slot = models.ForeignKey("scheduling.AvailabilitySlot", on_delete=models.PROTECT, related_name="visits")
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="SCHEDULED")
    attended = models.BooleanField(default=False)
    attended_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    chief_complaint = models.TextField(blank=True, default="")
    special_needs = models.TextField(blank=True, default="")
    cancellation_party = models.CharField(max_length=8, blank=True, default="", choices=[("", "不适用"), ("PATIENT", "患者"), ("CLINIC", "诊所")])
    cancellation_reason = models.TextField(blank=True, default="")
    replaces_visit = models.OneToOneField("scheduling.Visit", on_delete=models.PROTECT, null=True, blank=True, related_name="replacement")
    lock_version = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = "adc_visit"
        ordering = ["-scheduled_start", "-id"]
        indexes = [models.Index(fields=["clinic", "scheduled_start"], name="visit_clinic_time_idx"), models.Index(fields=["dentist", "completed_at"], name="visit_dentist_completed_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=["SCHEDULED", "CHECKED_IN", "COMPLETED", "CLOSED_NO_TREATMENT", "CANCELLED", "NO_SHOW", "RESCHEDULED"]), name="visit_status_valid"),
            models.CheckConstraint(condition=Q(scheduled_end__gt=F("scheduled_start")), name="visit_time_order"),
            models.CheckConstraint(condition=(Q(status__in=ATTENDED_STATUSES, attended=True, attended_at__isnull=False) | (~Q(status__in=ATTENDED_STATUSES) & Q(attended=False, attended_at__isnull=True))), name="visit_attendance_consistent"),
            models.CheckConstraint(condition=((Q(status__in=CLOSED_STATUSES) & Q(completed_at__isnull=False, completed_at__gte=F("attended_at"))) | (~Q(status__in=CLOSED_STATUSES) & Q(completed_at__isnull=True))), name="visit_completion_consistent"),
            models.CheckConstraint(condition=((Q(status="CANCELLED", cancellation_party__in=["PATIENT", "CLINIC"]) & ~Q(cancellation_reason="")) | (~Q(status="CANCELLED") & Q(cancellation_party="", cancellation_reason=""))), name="visit_cancellation_consistent"),
            models.CheckConstraint(condition=~Q(replaces_visit=F("id")), name="visit_not_replace_self"),
            ExclusionConstraint(name="visit_dentist_no_overlap", expressions=[(TsTzRange("scheduled_start", "scheduled_end", RangeBoundary()), RangeOperators.OVERLAPS), ("dentist", RangeOperators.EQUAL)], condition=Q(status__in=OCCUPYING_STATUSES)),
            ExclusionConstraint(name="visit_patient_no_overlap", expressions=[(TsTzRange("scheduled_start", "scheduled_end", RangeBoundary()), RangeOperators.OVERLAPS), ("patient", RangeOperators.EQUAL)], condition=Q(status__in=OCCUPYING_STATUSES)),
        ]

class VisitRequest(models.Model):
    visit = models.ForeignKey("scheduling.Visit", on_delete=models.PROTECT, related_name="requests")
    description = models.CharField(max_length=500)
    treatment_type = models.ForeignKey("registry.TreatmentType", on_delete=models.PROTECT, null=True, blank=True)
    class Meta:
        db_table = "adc_visit_request"

# Scheduling owns resource calendars; assets remain owned by equipment.
from scheduling.resource_models import (ResourcePolicy, Department, DepartmentHours, TreatmentRoom,
    BookingService, ServicePresentation, ServiceRequirement, ResourceBinding, ResourceBlock, ResourcePlan,
    ResourceClaim, ResourceCoordination, ResourceAction)
