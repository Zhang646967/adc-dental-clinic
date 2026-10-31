"""Version-bound own-patient decisions. No treatment, booking or cash effects."""
from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.policies import require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import professional_scope
from clinical.authority_services import lock_people
from clinical.clinical_payload import draft_digest
from clinical.consent_models import MedicalConsent, ConsentVersion, ConsentEvent
from clinical.disclosures import projection
from clinical.models import ClinicalRecordVersion
from clinical.plan_locks import lock_plan_visit, lock_self_plan
from clinical.plan_models import PlanStepVersion
from clinical.plans import current_version, latest_decision
from portal.policies import patient_access
from workspaces.context import require_active

CONTRACT = 'adc.medical-consent.c32b1.v1'
DECISIONS = ('AGREED', 'DECLINED', 'DEFERRED', 'WITHDRAWN')


def latest(consent):
    return consent.versions.order_by('-revision').first() if consent else None


def text(value, label, limit, required=False):
    if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
        raise RuleError(label + '请填写' + ('1至' if required else '不超过') + str(limit) + '字。')
    return value.strip()


def patient_snapshot(patient):
    return dict(id=patient.pk, name=patient.name, date_of_birth=patient.date_of_birth.isoformat())


def adult_self(patient):
    today = timezone.localdate(); born = patient.date_of_birth
    if today.year - born.year - ((today.month, today.day) < (born.month, born.day)) < 18:
        raise RuleError('本批仅办理经医师核对的成年患者本人决定；请由医师安排适格代理核验。')


def step_for(actor, step_id, visit_id=None):
    require_active(actor, ('PATIENT', 'DENTIST'))
    if actor._adc_workspace.role == 'PATIENT':
        access = patient_access(actor, self_only=True)
        step = PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit__patient', 'step').get(
            pk=step_id, version__plan__origin_encounter__visit__patient_id=access.patient_id)
        patient = access.patient
    else:
        from clinical.encounter_selectors import _encounter_details
        visit = _encounter_details(actor, visit_id)['visit']
        step = PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit__patient', 'step').get(
            pk=step_id, version__plan__origin_encounter__visit__patient_id=visit.patient_id,
            version__plan__origin_encounter__visit__clinic_id=visit.clinic_id)
        professional_scope(actor.pk, visit.clinic_id, step.service_id, 'READ')
        patient = visit.patient
    return step, patient


def current_scope(step, patient, version=None, *, lock=False):
    plan = step.version.plan
    if current_version(plan).pk != step.version_id:
        raise RuleError('方案已有新版本，请与医师重新核对本步骤说明。')
    if version:
        if patient_snapshot(patient) != version.patient_snapshot:
            raise RuleError('患者身份资料已变化，请医师重新核对。')
        current_record = ClinicalRecordVersion.objects.filter(encounter_id=version.source_record.encounter_id).order_by('-revision').first()
        if current_record.pk != version.source_record_id:
            raise RuleError('检查依据已更正，请医师重新告知。')
        professional_scope(version.prepared_by_id, plan.origin_encounter.visit.clinic_id, step.service_id, 'RECORD', lock=lock)
    chosen = latest_decision(step)
    if not chosen or chosen.decision != 'ACCEPTED':
        raise RuleError('请先核对本版本的方案选择；认可方案与医疗同意分别办理。')
    adult_self(patient)


def normalized(action, fields):
    values = dict(text=text(fields.get('text', ''), '沟通内容／原因', 2000, action in ('QUESTION', 'ANSWER', 'DECLINED', 'DEFERRED', 'WITHDRAWN')),
                  reference=text(fields.get('reference', ''), '原件参考编号', 500))
    if action == 'PUBLISH':
        values.update(identity_reference=text(fields.get('identity_reference', ''), '本人身份及理解表达核对依据', 500, True),
                      amendment_reason=text(fields.get('amendment_reason', ''), '重新告知原因', 500))
        if fields.get('self_qualified') is not True:
            raise RuleError('医师须明确核对本人身份与理解表达条件，不能由微信或年龄自动判定。')
    if action == 'ANSWER':
        try:values['reply_to'] = int(fields.get('reply_to'))
        except (TypeError, ValueError):raise RuleError('请明确答复哪一条患者疑问。')
    values['paper'] = fields.get('paper', False)
    if type(values['paper']) is not bool:raise RuleError('请明确决定的记录来源。')
    if values['paper']:
        if action not in DECISIONS or not values['reference'] or fields.get('paper_verified') is not True:
            raise RuleError('请核对患者本人纸质决定原件、实际时间与原件参考编号。')
        try:
            moment = datetime.fromisoformat(fields.get('occurred_at', ''))
            if not timezone.is_aware(moment) or moment > timezone.now():raise ValueError
        except (TypeError, ValueError):raise RuleError('请填写不晚于当前时间、带时区的纸质决定实际时间。')
        values['occurred_at'] = moment.isoformat()
    return values


def check_action(actor, action, values, step, patient, consent, version, *, lock=False):
    doctor = actor._adc_workspace.role == 'DENTIST'
    if doctor:
        professional_scope(actor.pk, step.version.plan.origin_encounter.visit.clinic_id, step.service_id, 'RECORD', lock=lock)
        if action not in ('PUBLISH', 'ANSWER') and not values['paper']:
            raise PermissionDenied('医师不能代点患者账号决定，请明确登记纸质原件来源。')
    elif action not in ('QUESTION',) + DECISIONS or values['paper']:
        raise PermissionDenied('本人账号只能办理本人提问与决定。')
    if action == 'PUBLISH':
        current_scope(step, patient)
        notice = projection(step.version.disclosures.get(str(step.step.step_key)))
        if not notice['available']:raise RuleError('请先在当前方案中完善并确认本步骤治疗说明。')
        if version and not values['amendment_reason']:raise RuleError('重新告知须说明原因，保留原版本与决定。')
        return
    if version is None:raise RuleError('医师尚未确认本步骤告知，请联系负责医师。')
    if version.step_version_id != step.pk:raise RuleError('请使用这份告知对应的准确方案步骤。')
    if action in ('QUESTION', 'AGREED'):
        if latest(consent).pk != version.pk:raise RuleError('已有新的医疗告知，请重新查看。')
        current_scope(step, patient, version, lock=lock)
    if action == 'ANSWER':
        question = ConsentEvent.objects.filter(pk=values['reply_to'], consent=consent, action='QUESTION').first()
        if not question or ConsentEvent.objects.filter(reply_to=question).exists():
            raise RuleError('该疑问不存在或已经答复，请刷新沟通记录。')
    if action == 'AGREED':
        if consent.events.filter(action='QUESTION', answer__isnull=True).exists():
            raise RuleError('还有未答复的疑问，请先与医师沟通，再明确决定。')
    if action in DECISIONS:
        previous = version.events.filter(action__in=DECISIONS).order_by('-sequence').first()
        if action == 'WITHDRAWN':
            if not previous or previous.action != 'AGREED':raise RuleError('本版本没有可撤回的本人同意。')
        elif previous:
            raise RuleError('此告知版本已有明确决定；如需改变决定，请医师重新告知，原决定保留。')
        if values['paper'] and datetime.fromisoformat(values['occurred_at']) < version.recorded_at:
            raise RuleError('纸质决定早于本份告知，不能倒签；请由医师核对原始资料另行补记。')


@sensitive_variables()
def prepare(*, actor, action, step_id, fields, visit_id=None, version_id=None):
    if action not in ('PUBLISH', 'QUESTION', 'ANSWER') + DECISIONS:raise RuleError('请选择明确的医疗沟通或决定操作。')
    step, patient = step_for(actor, step_id, visit_id)
    consent = MedicalConsent.objects.filter(step=step.step).first()
    version = ConsentVersion.objects.get(pk=version_id, consent=consent) if version_id else latest(consent)
    values = normalized(action, fields)
    check_action(actor, action, values, step, patient, consent, version)
    record = None
    if action == 'PUBLISH':
        record = ClinicalRecordVersion.objects.filter(encounter__visit_id=visit_id).order_by('-revision').first()
        if record is None:raise RuleError('请先确认本次检查依据。')
        if record.pk != step.version.source_record_id:
            raise RuleError('当前检查与治疗说明依据不同，请先刷新方案依据并重新确认治疗说明。')
    data = dict(action=action, plan=step.version.plan_id, plan_revision=step.version.plan.revision,
                step=step.pk, visit=visit_id, consent_revision=consent.revision if consent else 0,
                version=version.pk if version else None, publisher=version.prepared_by_id if version else actor.pk,
                source_record=record.pk if record else None, patient=patient_snapshot(patient), values=values)
    return dict(proposal_token=proposal(actor, CONTRACT, ('DENTIST', 'PATIENT'), data), data=data, step=step)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(*, actor, proposal_token, confirmed):
    if confirmed is not True:raise RuleError('请核对准确版本、记录来源及决定后明确确认。')
    p = read_proposal(actor, CONTRACT, ('DENTIST', 'PATIENT'), proposal_token);data = p['data']
    lock_people(actor, data['publisher'])
    if actor._adc_workspace.role == 'DENTIST':
        visit, patient, head, record, plan = lock_plan_visit(actor, data['visit'], data['plan']);access = None
    else:
        access, patient, plan = lock_self_plan(actor, data['plan']);record = None
    read_proposal(actor, CONTRACT, ('DENTIST', 'PATIENT'), proposal_token)
    step = PlanStepVersion.objects.select_related('version__plan__origin_encounter__visit', 'step').get(pk=data['step'], version__plan=plan)
    consent = MedicalConsent.objects.select_for_update().filter(step=step.step).first()
    prior = ConsentEvent.objects.filter(operation_id=p['operation']).first()
    if prior:
        if prior.actor_id != actor.pk or prior.consent_id != (consent.pk if consent else None):raise RuleError('原操作属于其他事项，请重新核对。')
        return prior, True
    if plan.revision != data['plan_revision'] or (consent.revision if consent else 0) != data['consent_revision'] or patient_snapshot(patient) != data['patient']:
        raise RuleError('方案、沟通记录或患者资料已变化，请重新预览。')
    version = ConsentVersion.objects.get(pk=data['version'], consent=consent) if data['version'] else None
    values = dict(data['values']);action = data['action']
    check_action(actor, action, values, step, patient, consent, version, lock=True)
    if action == 'PUBLISH':
        if record.pk != data['source_record']:raise RuleError('检查依据已更新，请重新预览告知。')
        if consent is None:consent = MedicalConsent.objects.create(step=step.step, opened_by=actor)
        latest_version = latest(consent)
        version = ConsentVersion.objects.create(consent=consent, revision=(latest_version.revision + 1 if latest_version else 1),
            previous=latest_version, step_version=step, source_record=record, prepared_by=actor,
            identity_reference=values['identity_reference'], patient_snapshot=data['patient'],
            amendment_reason=values['amendment_reason'], scope_digest=draft_digest(dict(step=step.pk, record=record.pk,
                patient=data['patient'], disclosure=step.version.disclosures.get(str(step.step.step_key)))))
    consent.revision += 1;consent.save(update_fields=['revision'])
    event = ConsentEvent.objects.create(consent=consent, version=version, sequence=consent.revision,
        operation_id=p['operation'], actor=actor, self_access=access, action='PUBLISHED' if action == 'PUBLISH' else action,
        source='PAPER_REFERENCE' if values['paper'] else 'DOCTOR_ACCOUNT' if actor._adc_workspace.role == 'DENTIST' else 'SELF_ACCOUNT',
        text=values['text'], reference=values['reference'], reply_to_id=values.get('reply_to'),
        occurred_at=datetime.fromisoformat(values['occurred_at']) if values['paper'] else timezone.now())
    emit(actor, 'MEDICAL_CONSENT_' + event.action, event, summary=dict(consent=consent.pk, version=version.pk,
        action=event.action, source=event.source))
    return event, False
