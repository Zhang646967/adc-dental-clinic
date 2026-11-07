"""C4.1 commands for submitted versions and attributed review decisions."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from accounts.models import UserAccount
from accounts.policies import require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import professional_scope, visit_service_id
from clinical.encounter_models import ClinicalRecordVersion
from clinical.encounters import history_cursor
from clinical.locking import lock_clinical_visit
from clinical.prescription_access import active_duties, pharmacist, prescriber, require_rehearsal
from clinical.prescription_models import Prescription, PrescriptionDecision, PrescriptionVersion
from clinical.prescription_payload import normalize_items, required_text
from patients.models import Patient
from scheduling.coordination import lock_slots
from scheduling.models import Visit

CONTRACT = 'adc.prescriptions.c41.v1'
ROLES = ('DENTIST', 'PHARMACIST')
ACTION = PrescriptionDecision.Action
REOPENABLE = {ACTION.RETURNED, ACTION.WITHDRAWN}


def current_version(case):
    return case.versions.select_related('record__history', 'decision__actor').order_by('-number').first()


def current_record(visit):
    return ClinicalRecordVersion.objects.filter(encounter__visit=visit).order_by('-revision').first()


def _eligible_record(visit, *, lock=False):
    if lock:
        visit.patient = Patient.objects.select_for_update().get(pk=visit.patient_id)
    record = current_record(visit)
    if visit.status != 'CHECKED_IN' or not visit.attended_at or visit.attended_at > timezone.now():
        raise RuleError('请先核对本次到诊状态。开方与通过审方须在本次接诊期间完成。')
    if not visit.patient.is_active or not record:
        raise RuleError('请先核对患者档案并完成本次检查记录确认。')
    if record.history_cursor != history_cursor(visit.patient_id, visit.clinic_id):
        raise RuleError('自述资料已有更新，请先核对用药与过敏信息并确认病历版本。')
    return record


def _submit_data(actor, visit, expected_record, previous, indication, entries, *, lock=False):
    duty, scope = prescriber(actor, visit, lock=lock)
    record = _eligible_record(visit, lock=lock)
    if record.pk != expected_record:
        raise RuleError('病历已有新版本，请重新核对后填写处方。')
    cases = Prescription.objects.filter(visit=visit)
    if lock:
        cases = cases.select_for_update()
    case = cases.first()
    latest = current_version(case) if case else None
    if (latest.pk if latest else None) != previous:
        raise RuleError('本次就诊已有新处方进度，请刷新后查看。')
    if case and (case.prescriber_id != actor.pk or not latest or latest.state not in REOPENABLE):
        raise RuleError('请在当前版本退回或撤回后重新提交。')
    return dict(
        kind='SUBMIT', visit=visit.pk, patient=visit.patient_id, record=record.pk, previous=previous,
        duty=duty.pk, scope=scope.pk, scope_revision=scope.revision,
        indication=required_text(indication, '临床依据'), items=normalize_items(visit.clinic_id, entries, lock=lock),
    )


@sensitive_variables()
def prepare_submit(actor, visit, expected_record, previous, indication, entries):
    data = _submit_data(actor, visit, expected_record, previous, indication, entries)
    return data, proposal(actor, CONTRACT, ('DENTIST',), data)


def _decision_duty(actor, version, action, *, lock=False):
    visit = version.prescription.visit
    author = version.prescription.prescriber_id
    if action == ACTION.WITHDRAWN:
        if actor.pk != author:
            raise PermissionDenied('须由原开方医师办理撤回。')
        return prescriber(actor, visit, lock=lock)[0]
    if action not in {ACTION.APPROVED, ACTION.RETURNED, ACTION.REJECTED}:
        raise RuleError('请选择有效的审核决定。')
    duty = pharmacist(actor, visit.clinic_id, lock=lock)
    if actor.pk == author:
        raise PermissionDenied('须由不同于开方人的药师独立审核。')
    return duty


def _approval_basis(version, *, lock=False):
    case = version.prescription
    visit = case.visit
    if case.prescriber.dentist_id != visit.dentist_id or _eligible_record(visit, lock=lock).pk != version.record_id:
        raise RuleError('开方依据已变化，请退回给负责医师核对并重新提交。')
    if not active_duties(case.prescriber_id, 'PRESCRIBE').filter(
        pk=version.prescriber_duty_id, clinic_id=visit.clinic_id,
    ).exists():
        raise RuleError('本版本的开方职责已变化，请退回后重新核对。')
    try:
        scope = professional_scope(case.prescriber_id, visit.clinic_id, visit_service_id(visit), 'RECORD', lock=lock)
    except PermissionDenied as exc:
        raise RuleError('原医师的专业授权已失效，请退回后重新核对。') from exc
    if (scope.pk, scope.revision) != (version.clinical_scope_id, version.clinical_scope_revision):
        raise RuleError('本版本的专业授权已变化，请退回后重新核对。')
    if normalize_items(visit.clinic_id, version.items, lock=lock) != version.items:
        raise RuleError('目录资料已变化，请退回给开方医师核对。')


def _decision_data(actor, version, action, reason, *, lock=False):
    duty = _decision_duty(actor, version, action, lock=lock)
    latest = current_version(version.prescription)
    if not latest or latest.pk != version.pk or latest.state != 'PENDING':
        raise RuleError('当前版本已有办理结果，请刷新查看。')
    if action == ACTION.APPROVED:
        _approval_basis(version, lock=lock)
    return dict(kind='DECIDE', case=version.prescription_id, version=version.pk,
                action=action, duty=duty.pk, reason=required_text(reason, '决定依据'))


@sensitive_variables()
def prepare_decision(actor, version, action, reason):
    data = _decision_data(actor, version, action, reason)
    return data, proposal(actor, CONTRACT, ROLES, data)


def _confirm_submit(actor, op, data):
    visit = lock_clinical_visit(actor, data['visit'])
    prescriber(actor, visit, lock=True)
    previous = PrescriptionVersion.objects.filter(operation_id=op, prescription__visit=visit,
                                                    prescription__prescriber=actor).first()
    if previous:
        return previous, True
    actual = _submit_data(actor, visit, data['record'], data['previous'], data['indication'], data['items'], lock=True)
    if actual != data:
        raise RuleError('目录、患者或开方授权已变化，请重新预览。')
    case = Prescription.objects.filter(visit=visit).first()
    if case is None:
        case = Prescription.objects.create(visit=visit, prescriber=actor)
        number = 1
    else:
        number = current_version(case).number + 1
    version = PrescriptionVersion.objects.create(
        prescription=case, number=number, record_id=data['record'], prescriber_duty_id=data['duty'],
        clinical_scope_id=data['scope'], clinical_scope_revision=data['scope_revision'],
        indication=data['indication'], items=data['items'], operation_id=op,
    )
    emit(actor, 'PRESCRIPTION_SUBMITTED', version, visit=visit, summary={'version': number})
    return version, False


def _confirm_decision(actor, op, data):
    case = Prescription.objects.get(pk=data['case'])
    # The same account order applies when a prescriber's authority is being changed.
    list(UserAccount.objects.select_for_update().filter(pk__in=[actor.pk, case.prescriber_id]).order_by('pk'))
    require_writable(actor)
    if data['action'] == ACTION.WITHDRAWN:
        visit = lock_clinical_visit(actor, case.visit_id)
    else:
        preview = Visit.objects.get(pk=case.visit_id)
        pharmacist(actor, preview.clinic_id, lock=True)
        lock_slots([preview.availability_slot_id])
        visit = Visit.objects.select_for_update().get(pk=case.visit_id)
    case = Prescription.objects.select_for_update().get(pk=case.pk)
    case.visit = visit
    version = PrescriptionVersion.objects.get(pk=data['version'], prescription=case)
    version.prescription = case
    duty = _decision_duty(actor, version, data['action'], lock=True)
    if duty.pk != data['duty']:
        raise RuleError('处方职责已变化，请重新预览。')
    if PrescriptionDecision.objects.filter(operation_id=op, version=version, actor=actor).exists():
        return version, True
    actual = _decision_data(actor, version, data['action'], data['reason'], lock=True)
    if actual != data:
        raise RuleError('审核条件已变化，请重新预览。')
    PrescriptionDecision.objects.create(version=version, actor=actor, duty=duty, action=data['action'],
                                        reason=data['reason'], operation_id=op)
    emit(actor, 'PRESCRIPTION_DECIDED', version, visit=visit,
         summary={'version': version.number, 'action': data['action']})
    return version, False


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(actor, proposal_token, confirmed):
    require_rehearsal()
    if confirmed is not True:
        raise RuleError('请核对内容并明确确认。')
    payload = read_proposal(actor, CONTRACT, ROLES, proposal_token)
    data, operation = payload['data'], payload['operation']
    if data['kind'] == 'SUBMIT' and payload['binding']['role'] == 'DENTIST':
        return _confirm_submit(actor, operation, data)
    if data['kind'] == 'DECIDE':
        return _confirm_decision(actor, operation, data)
    raise RuleError('处方确认内容无效，请重新预览。')
