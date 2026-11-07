"""Actor and object scope for the synthetic prescribing pilot."""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.utils import timezone
from accounts.policies import bindings
from clinical.authority import require_visit_authority
from clinical.prescription_models import PrescriptionDuty
from workspaces.context import require_active


def rehearsal_enabled():
    return settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_PRESCRIPTION_REHEARSAL


def require_rehearsal():
    if not rehearsal_enabled():
        raise Http404('处方演练当前未启用。')


def active_duties(user_id, kind):
    now = timezone.now()
    return PrescriptionDuty.objects.filter(
        user_id=user_id, kind=kind, revoked_at__isnull=True,
        valid_from__lte=now, valid_until__gt=now, clinic__is_active=True,
    )


def _duty(actor, clinic_id, kind, *, lock=False):
    require_rehearsal()
    rows = active_duties(actor.pk, kind).filter(clinic_id=clinic_id)
    if lock:
        rows = rows.select_for_update(of=('self',))
    duty = rows.first()
    if duty is None:
        raise PermissionDenied('当前诊所的处方职责未开通或已失效。')
    return duty


def prescriber(actor, visit, *, lock=False):
    require_rehearsal()
    scope = require_visit_authority(actor, visit, 'RECORD', always=True, lock=lock)
    return _duty(actor, visit.clinic_id, PrescriptionDuty.Kind.PRESCRIBE, lock=lock), scope


def pharmacist(actor, clinic_id, *, lock=False):
    require_active(actor, ('PHARMACIST',), clinic_id)
    grants = bindings(actor).filter(role='PHARMACIST', scope_kind='CLINIC', clinic_id=clinic_id)
    if lock:
        grants = grants.select_for_update(of=('self',))
    if not grants.exists():
        raise PermissionDenied('当前工作身份没有本诊所药师权限。')
    return _duty(actor, clinic_id, PrescriptionDuty.Kind.REVIEW, lock=lock)
