"""Own-account enrollment requests; an explicit clinic reviewer owns self-binding."""
from datetime import date
from uuid import uuid4
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.models import UserAccount
from accounts.external_identity import _account_actor
from accounts.policies import require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from adc_core.rules import RuleError,validate_birth
from care.audit import emit
from patients.models import Patient
from patients.services import create_patient,PATIENT_FIELDS
from patients.selectors import visible_patients
from portal.enrollment_models import PatientEnrollment,PatientEnrollmentEvent
from portal.models import PatientAccess
from portal.relationships import reviewer
from registry.models import Clinic

OWN='adc.patient.enrollment.account.v1'
REVIEW='adc.patient.enrollment.review.v1'
BASES=[('IN_PERSON','现场核对本人及账号'),('PATIENT_CONFIRMED','已通过原档案联络及本人核实')]


def own_cases(actor):
    _account_actor(actor)
    return PatientEnrollment.objects.filter(user=actor).select_related('clinic','patient').order_by('-created_at','-pk')


def clinic_cases(actor):
    reviewer(actor)
    return PatientEnrollment.objects.filter(clinic_id=actor._adc_workspace.clinic_id).select_related('user','clinic','patient').order_by('-created_at','-pk')


def _binding(actor):
    _account_actor(actor)
    ctx=getattr(actor,'_adc_workspace',None)
    return dict(actor=actor.pk,context=str(ctx.pk) if ctx else None,revision=ctx.revision if ctx else None)


def _eligible(actor,kind):
    if not actor.is_active:raise RuleError('请先完成原账号的安全恢复，再申请本人关联核验。')
    access=PatientAccess.objects.filter(user=actor).select_related('patient').first()
    if access and not (kind=='EXISTING' and not access.is_active and access.patient.is_active):
        raise RuleError('账号已有本人关联；暂停后仅可申请复核同一原关联，不能另建或改绑患者。')
    return access


@sensitive_variables()
def _details(kind,details,clinic_id):
    allowed=PATIENT_FIELDS|{'patient_reference'}
    if not isinstance(details,dict) or set(details)-allowed:raise RuleError('申请资料包含未知字段。')
    limits={'name':80,'billing_address':255,'phone':32,'email':254,'emergency_name':80,'emergency_phone':32,'patient_reference':40}
    if any(not isinstance(details.get(k,''),str) for k in limits):raise RuleError('请按字段填写文字资料。')
    clean={k:details.get(k,'').strip() for k in limits}
    if any(len(clean[k])>limit for k,limit in limits.items()):raise RuleError('资料超过允许长度，请核对。')
    try:birth=date.fromisoformat(str(details.get('date_of_birth','')))
    except ValueError:raise RuleError('请填写有效出生日期。') from None
    if not clean['name'] or not clean['phone'] or birth>timezone.localdate():raise RuleError('请填写姓名、联络号码及有效出生日期。')
    validate_birth(birth,timezone.localdate())
    clean['date_of_birth']=birth.isoformat()
    if kind=='NEW':
        obj=Patient(created_in_clinic_id=clinic_id,allergy_status='UNKNOWN',**{k:(birth if k=='date_of_birth' else clean[k]) for k in PATIENT_FIELDS})
        obj.full_clean(exclude=['patient_no'])
    elif kind!='EXISTING':raise RuleError('请选择新患者建档或已有档案关联。')
    return clean


@sensitive_variables()
def prepare_submit(*,actor,clinic_id,kind,details,case_id=None):
    binding=_binding(actor);_eligible(actor,kind)
    clinic=Clinic.objects.get(pk=clinic_id,is_active=True)
    clean=_details(kind,details,clinic.pk)
    row=own_cases(actor).get(pk=case_id) if case_id else None
    if row and (row.state!='NEED_INFO' or row.clinic_id!=clinic.pk or row.kind!=kind):raise RuleError('请从待补充申请继续；原诊所及申请类型不变。')
    token=signing.dumps(dict(**binding,operation=str(uuid4()),action='SUBMIT',clinic=clinic.pk,kind=kind,details=clean,case=row.pk if row else None,case_revision=row.revision if row else None),salt=OWN)
    from portal.enrollment_display import detail_rows
    return dict(proposal_token=token,clinic=clinic.public_contact['name'],kind=kind,kind_label=dict(PatientEnrollment.KINDS)[kind],details=clean,rows=detail_rows(clean))


def _record(actor,row,operation,action,*,basis='',reference='',effect=''):
    PatientEnrollmentEvent.objects.create(enrollment=row,actor=actor,operation_id=operation,action=action,basis=basis,reference=reference,
        snapshot=dict(state=row.state,revision=row.revision,details=row.details,patient=row.patient_id,patient_message=row.patient_message,effect=effect))
    emit(actor,'PATIENT_ENROLLMENT_CHANGED',row,summary={'action':action,'state':row.state,'clinic_id':row.clinic_id})


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_submit(*,actor,token,confirmed):
    if settings.ADC_READ_ONLY:raise PermissionDenied('当前实例只读。')
    if confirmed is not True:raise RuleError('请核对申请资料并明确确认。')
    UserAccount.objects.select_for_update().get(pk=actor.pk,is_active=True)
    binding=_binding(actor)
    try:p=signing.loads(token,salt=OWN,max_age=900)
    except (signing.BadSignature,TypeError,ValueError):raise RuleError('申请预览已失效，请重新核对。') from None
    if any(p.get(k)!=v for k,v in binding.items()):raise PermissionDenied('账号通道已变化，请重新核对。')
    prior=PatientEnrollmentEvent.objects.filter(operation_id=p['operation'],actor=actor,action='SUBMIT').select_related('enrollment').first()
    if prior:return prior.enrollment,True
    _eligible(actor,p['kind']);Clinic.objects.get(pk=p['clinic'],is_active=True)
    clean=_details(p['kind'],p['details'],p['clinic'])
    if p['case']:
        row=own_cases(actor).select_for_update(of=('self',)).get(pk=p['case'])
        if row.state!='NEED_INFO' or row.revision!=p['case_revision']:raise RuleError('申请已变化，请打开当前状态继续。')
        row.details=clean;row.state='PENDING';row.patient_message='';row.revision+=1;row.save(update_fields=['details','state','patient_message','revision','updated_at'])
    else:
        if PatientEnrollment.objects.filter(user=actor,state__in=['PENDING','NEED_INFO']).exists():raise RuleError('已有办理中的申请，请从原申请继续。')
        row=PatientEnrollment.objects.create(user=actor,clinic_id=p['clinic'],kind=p['kind'],details=clean)
    _record(actor,row,p['operation'],'SUBMIT')
    return row,False


@business_errors
@transaction.atomic
def withdraw(*,actor,case_id,expected_revision):
    if settings.ADC_READ_ONLY:raise PermissionDenied('当前实例只读。')
    UserAccount.objects.select_for_update().get(pk=actor.pk,is_active=True)
    row=own_cases(actor).select_for_update(of=('self',)).get(pk=case_id)
    if row.state=='WITHDRAWN':return row
    if row.revision!=expected_revision or row.state not in ['PENDING','NEED_INFO']:raise RuleError('当前申请不能撤回，请查看最新状态。')
    row.state='WITHDRAWN';row.revision+=1;row.save(update_fields=['state','revision','updated_at'])
    _record(actor,row,uuid4(),'WITHDRAW');return row


def prepare_review(*,actor,case_id,action,basis='',reference='',patient_no='',patient_message=''):
    row=clinic_cases(actor).get(pk=case_id)
    if row.user_id==actor.pk:raise PermissionDenied('不能核验本人的申请；请由另一名有本店职责的前台办理。')
    if row.state!='PENDING' or action not in ['APPROVE','NEED_INFO','REJECT']:raise RuleError('请核对当前申请及办理动作。')
    if basis not in dict(BASES) or not isinstance(reference,str) or not 1<=len(reference.strip())<=160:raise RuleError('请记录核验方式和内部依据编号，不填写完整证件号。')
    if not isinstance(patient_message,str) or len(patient_message.strip())>500 or (action!='APPROVE' and not patient_message.strip()):raise RuleError('请填写患者可见的补充要求或未通过说明。')
    patient=None
    if action=='APPROVE' and row.kind=='EXISTING':patient=visible_patients(actor).get(patient_no=patient_no,is_active=True)
    if action=='APPROVE':
        original=_eligible(row.user,row.kind)
        if original and original.patient_id!=patient.pk:raise RuleError('只能复核同一原本人档案，不能选择另一患者。')
    if action=='APPROVE' and row.kind=='NEW':_details(row.kind,row.details,row.clinic_id)
    return proposal(actor,REVIEW,('FRONT_DESK',),dict(case=row.pk,revision=row.revision,action=action,basis=basis,reference=reference.strip(),
        patient=patient.pk if patient else None,patient_facts=_patient_facts(patient) if patient else None,patient_message=patient_message.strip()))


def _patient_facts(patient):
    return dict(name=patient.name,date_of_birth=patient.date_of_birth.isoformat(),phone=patient.phone,active=patient.is_active,clinic=patient.created_in_clinic_id)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm_review(*,actor,token,confirmed):
    if confirmed is not True:raise RuleError('请确认已核对本人、账号及申请诊所。')
    p=read_proposal(actor,REVIEW,('FRONT_DESK',),token);d=p['data']
    # Same canonical account order as account governance; then clinic duty/case.
    owner=PatientEnrollment.objects.get(pk=d['case']).user_id
    list(UserAccount.objects.select_for_update().filter(pk__in=[actor.pk,owner]).order_by('pk'))
    require_writable(actor);reviewer(actor,lock=True)
    prior=PatientEnrollmentEvent.objects.filter(operation_id=p['operation'],actor=actor).select_related('enrollment').first()
    if prior:
        if prior.enrollment.clinic_id!=actor._adc_workspace.clinic_id:raise PermissionDenied
        return prior.enrollment,True
    row=clinic_cases(actor).select_for_update(of=('self',)).get(pk=d['case'])
    if row.user_id==actor.pk:raise PermissionDenied('不能切换岗位核验本人的申请。')
    if row.state!='PENDING' or row.revision!=d['revision']:raise RuleError('申请已变化，请重新核对；原决定保留。')
    user=UserAccount.objects.get(pk=row.user_id,is_active=True)
    effect=''
    if d['action']=='APPROVE':
        original_access=_eligible(user,row.kind)
        if row.kind=='NEW':
            clean=_details(row.kind,row.details,row.clinic_id)
            patient=create_patient(actor=actor,clinic_id=row.clinic_id,details={k:date.fromisoformat(clean[k]) if k=='date_of_birth' else clean[k] for k in PATIENT_FIELDS},allergy_status='UNKNOWN')
            effect='REGISTER_NEW'
        else:
            patient=visible_patients(actor).select_for_update().get(pk=d['patient'],is_active=True)
            if _patient_facts(patient)!=d['patient_facts']:raise RuleError('原档案已变化，请重新核对本人依据。')
            if original_access and original_access.patient_id!=patient.pk:raise RuleError('恢复只能针对同一原本人档案，不能改绑患者。')
            if original_access:
                original_access=PatientAccess.objects.select_for_update().get(pk=original_access.pk,user=user,patient=patient,is_active=False)
                original_access.is_active=True;original_access.save(update_fields=['is_active']);effect='RESTORE_EXISTING'
            elif PatientAccess.objects.filter(patient=patient).exists():raise RuleError('此档案已有本人关联，不能由另一账号认领。')
            else:effect='LINK_EXISTING'
        if not original_access:PatientAccess.objects.create(user=user,patient=patient)
        row.patient=patient;row.state='APPROVED'
    else:row.state=d['action']
    row.patient_message=d['patient_message'];row.revision+=1;row.save(update_fields=['patient','state','patient_message','revision','updated_at'])
    _record(actor,row,p['operation'],d['action'],basis=d['basis'],reference=d['reference'],effect=effect)
    return row,False
