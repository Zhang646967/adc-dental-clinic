from django.utils import timezone
from care.models import AuditEvent

def emit(actor, event_type, subject, *, visit=None, reason="", summary=None, occurred_at=None):
    """Call inside the same transaction as the successful business change."""
    return AuditEvent.objects.create(
        actor=actor, event_type=event_type, subject_type=subject._meta.model_name,
        subject_key=str(subject.pk), visit=visit, reason=reason[:500],
        occurred_at=occurred_at or timezone.now(), change_summary=summary or {},
    )
