from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.policies import lock_clinic_grant, require_writable
from adc_core.rules import RuleError, validate_birth, validate_allergies
from care.audit import emit
from patients.models import Patient, PatientAllergy
from patients.selectors import visible_patients
from registry.models import Allergy, Clinic

PATIENT_FIELDS = {"name", "date_of_birth", "billing_address", "phone", "email", "emergency_name", "emergency_phone"}

@transaction.atomic
def create_patient(*, actor, clinic_id: int, details: dict, allergy_status: str, allergy_ids=()):
    lock_clinic_grant(actor, clinic_id)
    clinic = Clinic.objects.get(pk=clinic_id, is_active=True)
    if set(details) - PATIENT_FIELDS:
        raise RuleError("患者资料包含不允许写入的字段。")
    ids = validate_allergies(allergy_status, allergy_ids)
    validate_birth(details["date_of_birth"], timezone.localdate())
    if Allergy.objects.filter(pk__in=ids, is_active=True).count() != len(ids):
        raise RuleError("选用的过敏目录项目已失效。")
    patient = Patient(created_in_clinic=clinic, allergy_status=allergy_status, **details)
    patient.full_clean()
    patient.save()
    PatientAllergy.objects.bulk_create([PatientAllergy(patient=patient, allergy_id=i) for i in ids])
    emit(actor, "PATIENT_CREATED", patient, summary={"clinic_id": clinic_id, "allergy_status": allergy_status})
    return patient

@transaction.atomic
def update_allergies(*, actor, patient_id: int, clinic_id: int, expected_version: int, status: str, allergy_ids=()):
    lock_clinic_grant(actor, clinic_id)
    if not visible_patients(actor).filter(pk=patient_id).exists():
        raise PermissionDenied("没有该患者档案权限。")
    patient = Patient.objects.select_for_update().get(pk=patient_id, is_active=True)
    if patient.allergy_info_version != expected_version:
        raise RuleError("过敏资料已由其他操作更新，请刷新后复核。")
    # Require a business association to this very grant, not an unrelated clinic grant.
    if patient.created_in_clinic_id != clinic_id and not patient.visits.filter(clinic_id=clinic_id).exists():
        raise PermissionDenied("患者与目标授权诊所没有业务关联。")
    ids = validate_allergies(status, allergy_ids)
    if Allergy.objects.filter(pk__in=ids, is_active=True).count() != len(ids):
        raise RuleError("过敏目录项目已失效。")
    patient.allergy_links.update(is_active=False)
    for item_id in ids:
        PatientAllergy.objects.update_or_create(patient=patient, allergy_id=item_id, defaults={"is_active": True})
    patient.allergy_status = status
    patient.allergy_info_version += 1
    patient.save(update_fields=["allergy_status", "allergy_info_version"])
    emit(actor, "ALLERGIES_UPDATED", patient, summary={"information_version": patient.allergy_info_version})
    return patient
