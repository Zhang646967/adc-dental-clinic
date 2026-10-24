"""A referral grants named, timed read access; it never creates care or money."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import RoleAssignment
from accounts.policies import bindings, lock_clinic_grant
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from care.audit import emit
from care.models import VisitRecordVersion
from clinical.authority import require_visit_authority, professional_scope
from clinical.authority_services import lock_people, text, date_time
from clinical.models import ClinicalReferral, ClinicalReferralEvent, ClinicalRecordVersion
from patients.models import Patient
from scheduling.models import Visit

CONTRACT = 'adc.clinical-referral.c21.v2'
ROLES = ('DENTIST', 'FRONT_DESK', 'MANAGER', 'PATIENT')


def visible_referrals(actor):
    from django.db.models import Q
    ctx = workspace_binding(actor, ROLES)
    qs = ClinicalReferral.objects.select_related('patient','source_clinic','destination_clinic','receiver','created_by')
    if ctx['role'] == 'DENTIST':
        return qs.filter(Q(created_by=actor) | Q(receiver=actor))
    if ctx['role'] == 'MANAGER':
        return qs.filter(Q(source_clinic_id=ctx['clinic']) | Q(destination_clinic_id=ctx['clinic']))
    if ctx['role'] == 'FRONT_DESK':
        return qs.filter(destination_clinic_id=ctx['clinic'])
    from portal.policies import patient_access
    return qs.filter(patient_id=patient_access(actor, self_only=True).patient_id)


def require_identity_reviewer(actor, row, *, lock=False):
    if lock:
        grant = lock_clinic_grant(actor, row.destination_clinic_id, ('FRONT_DESK',))
        allowed = grant.can_verify_patient_relationships
    else:
        allowed = bindings(actor).filter(role='FRONT_DESK', scope_kind='CLINIC',
            clinic_id=row.destination_clinic_id, can_verify_patient_relationships=True).exists()
    if not allowed:
        raise PermissionDenied('需要接收诊所的患者身份核验职责。')


def prepare_referral(*, actor, action, referral_id=None, fields=None):
    ctx = workspace_binding(actor, ROLES)
    fields = fields or {}
    if action == 'CREATE':
        if ctx['role'] != 'DENTIST':
            raise PermissionDenied('由负责医师发起跨店转诊。')
        data = validate_new(actor, fields)
        data = {'action': action, 'fields': data}
    else:
        row = visible_referrals(actor).get(pk=referral_id)
        check_action(actor, row, action)
        data = dict(action=action, referral_id=row.pk, revision=row.revision,
            note=text(fields.get('note'), '办理依据', 500))
        if action == 'IDENTITY_CONFIRM':
            # An exact existing identity is required. Similar names/phones never merge.
            number = fields.get('patient_no', '').strip()
            if number != row.patient.patient_no:
                raise RuleError('接收档案编号不一致，请登记身份待澄清；不能自动合并或转移病历。')
            data['patient_no'] = number
    return {'proposal_token': proposal(actor, CONTRACT, ROLES, data), 'data': data}


def validate_new(actor, fields, *, lock=False):
    visit = Visit.objects.get(pk=fields['source_visit_id'])
    require_visit_authority(actor, visit, 'REFER', lock=lock, always=True)
    if fields['destination_clinic_id'] == visit.clinic_id:
        raise RuleError('此入口用于跨诊所转诊，请选择不同的接收诊所。')
    if fields['receiver_id'] == actor.pk:
        raise RuleError('转出与接收医师须为不同账号，不能自行接收自己的转诊。')
    scope = professional_scope(fields['receiver_id'], fields['destination_clinic_id'], fields.get('destination_service_id'), 'READ', lock=lock)
    until = date_time(fields['valid_until'])
    if not timezone.now() < until <= scope.valid_until:
        raise RuleError('转诊查阅期限须在接收医师当前专业授权期限内。')
    if fields['consent_basis'] not in ('PATIENT', 'LEGAL_REPRESENTATIVE'):
        raise RuleError('须记录患者本人或另行核验的法定代理披露同意；代约授权不能代替此项。')
    source_record_id = fields.get('source_record_id')
    source_clinical_record_id=fields.get('source_clinical_record_id')
    if source_record_id is not None and source_clinical_record_id is not None:
        raise RuleError('请选择一种明确的历史版本来源；不能把两种记录合并为一次未区分的披露。')
    if source_clinical_record_id is not None and not ClinicalRecordVersion.objects.filter(
            pk=source_clinical_record_id,encounter__visit_id=visit.pk).exists():
        raise RuleError('只能选择本次就诊已确认的结构化检查版本；草稿和其他患者记录不在此披露范围。')
    if source_record_id is not None and not VisitRecordVersion.objects.filter(pk=source_record_id,
        visit=visit, state='PUBLISHED').exists():
        raise RuleError('只能明确选择原就诊已发布的记录版本，不能披露草稿或其他患者的记录。')
    if not Patient.objects.filter(pk=visit.patient_id, is_active=True).exists():
        raise RuleError('患者资料已停用，请先核对身份。')
    return dict(patient_id=visit.patient_id, source_visit_id=visit.pk, source_record_id=source_record_id,
        source_clinical_record_id=source_clinical_record_id,
        source_clinic_id=visit.clinic_id, destination_clinic_id=fields['destination_clinic_id'],
        destination_service_id=fields.get('destination_service_id'), receiver_id=fields['receiver_id'],
        consent_basis=fields['consent_basis'], consent_reference=text(fields['consent_reference'], '披露同意依据编号'),
        purpose=text(fields['purpose'], '转诊目的', 500), valid_until=until.isoformat())


def check_action(actor, row, action, *, lock=False):
    ctx = workspace_binding(actor, ROLES)
    if action in ('IDENTITY_CONFIRM', 'IDENTITY_DISPUTE'):
        require_identity_reviewer(actor, row, lock=lock)
        if row.state not in ('REQUESTED', 'IDENTITY_DISPUTED', 'IDENTITY_CONFIRMED'):
            raise RuleError('当前转诊已处理，不能重新核对或覆盖原身份结果。')
    elif action in ('ACCEPT', 'DECLINE'):
        if ctx['role'] != 'DENTIST' or actor.pk != row.receiver_id:
            raise PermissionDenied('只有此单明确指定的接收医师可以处理。')
        if row.state != 'IDENTITY_CONFIRMED':
            raise RuleError('须先由接收店核对患者身份，当前不能接收。')
        professional_scope(actor.pk, row.destination_clinic_id, row.destination_service_id, 'READ', lock=lock)
    elif action in ('WITHDRAW', 'REVOKE'):
        allowed = ctx['role'] == 'DENTIST' and row.created_by_id == actor.pk
        if ctx['role'] == 'MANAGER' and ctx['clinic'] == row.source_clinic_id:
            allowed = True  # Stop disclosure without acquiring clinical chart access.
            if lock:
                lock_clinic_grant(actor, row.source_clinic_id, ('MANAGER',))
        if ctx['role'] == 'PATIENT':
            from portal.policies import patient_access
            allowed = patient_access(actor, self_only=True).patient_id == row.patient_id
        if not allowed:
            raise PermissionDenied('只有患者本人、转出医师或转出店主管可以终止此披露。')
        expected = ('ACCEPTED',) if action == 'REVOKE' else ('REQUESTED', 'IDENTITY_CONFIRMED', 'IDENTITY_DISPUTED')
        if row.state not in expected:
            raise RuleError('当前状态不接受此操作，请核对已保存的结果。')
    else:
        raise PermissionDenied('未知转诊操作。')
    if action not in ('WITHDRAW', 'REVOKE') and row.valid_until <= timezone.now():
        raise RuleError('转诊查阅期限已过，请由原负责医师重新取得依据并另行发起。')


@business_errors
@transaction.atomic
def confirm_referral(*, actor, proposal_token, confirmed):
    if confirmed is not True:
        raise RuleError('请明确确认转诊内容。')
    payload = read_proposal(actor, CONTRACT, ROLES, proposal_token)
    data = payload['data']; action = data['action']
    old = ClinicalReferral.objects.get(pk=data['referral_id']) if 'referral_id' in data else None
    peers = (old.created_by_id, old.receiver_id) if old else (data['fields']['receiver_id'],)
    lock_people(actor, *peers)
    read_proposal(actor, CONTRACT, ROLES, proposal_token)
    previous = ClinicalReferralEvent.objects.filter(actor=actor, operation_id=payload['operation']).first()
    if previous:
        # A successful request is history, not permission to revive a later withdrawal.
        row = visible_referrals(actor).get(pk=previous.referral_id)
        return row, True
    before = ''
    if action == 'CREATE':
        fields = validate_new(actor, data['fields'], lock=True)
        fields['valid_until'] = date_time(fields['valid_until'])
        row = ClinicalReferral.objects.create(created_by=actor, **fields)
        note = '转出医师记录独立的披露同意依据，指定接收医师与记录版本。'
    else:
        row = ClinicalReferral.objects.select_for_update().select_related('patient').get(pk=old.pk)
        if row.revision != data['revision']:
            raise RuleError('转诊已由其他人处理，请重新核对；本次没有覆盖结果。')
        check_action(actor, row, action, lock=True)
        if action == 'IDENTITY_CONFIRM' and row.patient.patient_no != data['patient_no']:
            raise RuleError('患者标识已变化，请重新核对。')
        before = row.state
        row.state = {'IDENTITY_CONFIRM':'IDENTITY_CONFIRMED', 'IDENTITY_DISPUTE':'IDENTITY_DISPUTED',
            'ACCEPT':'ACCEPTED', 'DECLINE':'DECLINED', 'WITHDRAW':'WITHDRAWN', 'REVOKE':'REVOKED'}[action]
        row.revision += 1
        row.save(update_fields=['state','revision'])
        note = data['note']
    ClinicalReferralEvent.objects.create(actor=actor, referral=row, operation_id=payload['operation'], action=action,
        prior_state=before, resulting_state=row.state, note=note,
        snapshot={'revision':row.revision,'source_record_id':row.source_record_id,'source_clinical_record_id':row.source_clinical_record_id,'valid_until':row.valid_until.isoformat()})
    emit(actor, 'CLINICAL_REFERRAL_CHANGED', row, summary={'action':action,'state':row.state})
    return row, False


def require_referral_read(actor, row):
    workspace_binding(actor, ('DENTIST',))
    if row.state != 'ACCEPTED' or row.receiver_id != actor.pk or row.valid_until <= timezone.now():
        raise PermissionDenied('此转诊未接收、已到期或已终止，没有可查阅的披露内容。')
    professional_scope(actor.pk, row.destination_clinic_id, row.destination_service_id, 'READ')


def released_record(actor, row):
    """Private, minimal projection. No invoice amounts, billing header or chain query."""
    require_referral_read(actor,row)
    result = {'purpose':row.purpose, 'record':None,'clinical_record':None}
    if row.source_record_id:
        record = VisitRecordVersion.objects.get(pk=row.source_record_id, visit_id=row.source_visit_id, state='PUBLISHED')
        result['record'] = {'revision':record.revision_no, 'published_at':record.published_at,
            'clinical_note':record.clinical_note, 'allergy_review':record.allergy_review_snapshot,
            'treatments':list(record.treatment_lines.values('name_snapshot','unit_snapshot','quantity'))}
    if row.source_clinical_record_id:
        from clinical.tooth_rules import KINDS,DENTITIONS
        from clinical.encounter_models import HISTORY_STATES
        record=ClinicalRecordVersion.objects.select_related('history').get(pk=row.source_clinical_record_id,encounter__visit_id=row.source_visit_id)
        history=None
        if record.history_id:
            h=record.history
            if h.patient_id!=row.patient_id:raise PermissionDenied('引用的患者自述对象需要重新核对。')
            history=dict(source=h.get_source_display(),revision=h.revision,recorded_at=h.recorded_at,
                medical_status=dict(HISTORY_STATES)[h.medical_status],medical_history=h.medical_history,
                medication_status=dict(HISTORY_STATES)[h.medication_status],medications=h.medications,
                allergy_status=dict(HISTORY_STATES)[h.allergy_status],reported_allergies=h.reported_allergies)
        result['clinical_record']=dict(revision=record.revision,recorded_at=record.recorded_at,observed_at=record.observed_at,
            chief_complaint=record.chief_complaint,examination=record.examination,history_assessment=record.history_assessment,
            history_discrepancy=record.history_discrepancy,history=history,dentition=DENTITIONS[record.dentition],
            findings=[dict(tooth=f.tooth,surface=f.surface,kind=KINDS[f.kind],detail=f.detail) for f in record.findings.all()])
    return result
