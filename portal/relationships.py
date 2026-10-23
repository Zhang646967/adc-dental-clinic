"""Clinic-scoped relationship cases and reviewed appointment authority."""
from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.models import UserAccount
from accounts.policies import lock_clinic_grant, require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from patients.contact_services import require_contact_actor, _subject
from patients.selectors import visible_patients
from portal.models import PatientRelationship, PatientRelationshipEvent, PatientAppointmentGrant
from portal.policies import active_grants, PatientAccess

CONTRACT = 'adc.patient.relationship.v1'
DELEGATING = {'PARENT','GUARDIAN','DELEGATE'}
BASES = [('IN_PERSON','现场核对身份与关系依据'),('PATIENT_CONFIRMED','已与患者核实预约委托'),('GUARDIAN_CONFIRMED','已核实监护关系及预约委托')]

def cases(actor):
    ctx=require_contact_actor(actor)
    return PatientRelationship.objects.filter(clinic_id=ctx.clinic_id).select_related('patient','clinic','delegate_user')

def reviewer(actor, *, lock=False):
    ctx=require_contact_actor(actor)
    if lock:
        role=lock_clinic_grant(actor,ctx.clinic_id)
        allowed=role.can_verify_patient_relationships
    else:
        from accounts.policies import bindings
        allowed=bindings(actor).filter(role='FRONT_DESK',clinic_id=ctx.clinic_id,can_verify_patient_relationships=True).exists()
    if not allowed:
        raise PermissionDenied('需要本店明确授予的患者关系核验职责；请联系核验人员。')

def account(username):
    if not username:return None
    try:return UserAccount.objects.get(username=username,is_active=True)
    except UserAccount.DoesNotExist:
        raise RuleError('该登录账号不存在或已停用。请先由技术人员创建账号，再核对本人及账号归属。') from None

def text(value,limit,required=True):
    value=(value or '').strip()
    if len(value)>limit or (required and not value):raise RuleError('请填写完整且符合长度要求的核验信息。')
    return value

@sensitive_variables()
def prepare_create(*,actor,patient_no,related_name,kind,username='',note=''):
    ctx=require_contact_actor(actor)
    patient=visible_patients(actor).get(patient_no=patient_no,is_active=True)
    _subject(actor,patient.pk)
    if kind not in dict(PatientRelationship.KINDS):raise RuleError('请选择有效关系。')
    user=account(username)
    d=dict(action='CREATE',patient=patient.pk,related_name=text(related_name,100),kind=kind,
        account=user.pk if user else None,note=text(note,500))
    return proposal(actor,CONTRACT,('FRONT_DESK',),d)

@sensitive_variables()
def prepare_action(*,actor,case_id,action,basis='',reference='',note='',valid_until=None,username=''):
    case=cases(actor).get(pk=case_id)
    if action not in {'LINK_ACCOUNT','VERIFY','REJECT','SUSPEND','REVOKE','WITHDRAW'}:raise RuleError('未知关系操作。')
    if action in {'VERIFY','REJECT'}:reviewer(actor)
    d=dict(action=action,case=case.pk,revision=case.revision,basis=basis,
        reference=text(reference,160,False),note=text(note,500),valid_until=None,account=None)
    if action=='LINK_ACCOUNT':
        user=account(username)
        if not user:raise RuleError('请填写已核对的登录账号。')
        d['account']=user.pk
    if action=='VERIFY':
        if basis not in dict(BASES) or not d['reference']:raise RuleError('请记录核验方式和内部依据编号，不要输入完整证件号码。')
        if case.kind in DELEGATING:
            if not case.delegate_user_id:raise RuleError('请先关联已核对的代约账号，再核验授权。')
            if not valid_until or timezone.is_naive(valid_until) or valid_until<=timezone.now():raise RuleError('请明确未来的授权截止时间。')
            d['valid_until']=valid_until.isoformat()
    return proposal(actor,CONTRACT,('FRONT_DESK',),d)


def _record(actor,case,operation,action,prior,d):
    grant=PatientAppointmentGrant.objects.filter(relationship=case).first()
    snapshot=dict(revision=case.revision,account=case.delegate_user_id,kind=case.kind,
        grant=grant.pk if grant else None,grant_revision=grant.revision if grant else None,
        active=grant.is_active if grant else False,
        valid_from=grant.valid_from.isoformat() if grant else None,
        valid_until=grant.valid_until.isoformat() if grant else None)
    PatientRelationshipEvent.objects.create(relationship=case,actor=actor,operation_id=operation,
        action=action,prior_state=prior,resulting_state=case.state,basis=d.get('basis',''),
        reference=d.get('reference',''),note=d.get('note',''),snapshot=snapshot)
    emit(actor,'PATIENT_RELATIONSHIP_CHANGED',case,summary={'action':action,'state':case.state,'revision':case.revision})


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(*,actor,token,confirmed):
    require_writable(actor)
    if confirmed is not True:raise RuleError('请核对就诊人、关联人、账号及授权范围后明确确认。')
    ctx=require_contact_actor(actor)
    lock_clinic_grant(actor,ctx.clinic_id)
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),token);d=p['data'];action=d['action']
    if action in {'VERIFY','REJECT'}:reviewer(actor,lock=True)
    prior=PatientRelationshipEvent.objects.filter(operation_id=p['operation'],actor=actor,
        relationship__clinic_id=ctx.clinic_id).select_related('relationship').first()
    if prior:return prior.relationship,True
    if action=='CREATE':
        patient=_subject(actor,d['patient'],locked=True)
        user=UserAccount.objects.get(pk=d['account'],is_active=True) if d['account'] else None
        if user and PatientRelationship.objects.filter(patient=patient,clinic_id=ctx.clinic_id,delegate_user=user,
                state__in=['PENDING','VERIFIED','SUSPENDED']).exists():
            raise RuleError('该患者与账号在本店已有办理中的关系，请从清单继续处理。')
        case=PatientRelationship.objects.create(clinic_id=ctx.clinic_id,patient=patient,related_name=d['related_name'],
            kind=d['kind'],delegate_user=user,created_by=actor)
        _record(actor,case,p['operation'],action,'',d)
        return case,False
    case=cases(actor).select_for_update(of=('self',)).get(pk=d['case'])
    if case.revision!=d['revision']:raise RuleError('关系记录已变化，请重新核对；没有覆盖原决定。')
    state=case.state
    grant=PatientAppointmentGrant.objects.select_for_update().filter(relationship=case).first()
    if action=='LINK_ACCOUNT':
        if state!='PENDING' or case.delegate_user_id:raise RuleError('仅待核验且尚未关联账号的记录可补充账号；原关联不能覆盖。')
        user=UserAccount.objects.get(pk=d['account'],is_active=True)
        if PatientRelationship.objects.filter(patient=case.patient,clinic=case.clinic,delegate_user=user,state__in=['PENDING','VERIFIED','SUSPENDED']).exists():
            raise RuleError('该患者与账号已有办理中的关系，请核对原记录。')
        case.delegate_user=user
    elif action=='VERIFY':
        if state not in {'PENDING','SUSPENDED'}:raise RuleError('当前关系不能重新核验，请核对历史结果。')
        if not case.patient.is_active or not case.clinic.is_active:raise RuleError('患者或诊所已停用。')
        if case.kind in DELEGATING:
            if not UserAccount.objects.filter(pk=case.delegate_user_id,is_active=True).exists():raise RuleError('代约账号已失效，请重新核对。')
            until=datetime.fromisoformat(d['valid_until'])
            if until<=timezone.now():raise RuleError('授权截止时间已到，请重新核验。')
            if grant:
                grant.is_active=True;grant.valid_from=timezone.now();grant.valid_until=until;grant.revision+=1
                grant.save(update_fields=['is_active','valid_from','valid_until','revision'])
            else:
                PatientAppointmentGrant.objects.create(relationship=case,valid_from=timezone.now(),valid_until=until,created_by=actor)
        case.state='VERIFIED'
    else:
        transitions={'REJECT':({'PENDING'},'REJECTED'),'WITHDRAW':({'PENDING'},'WITHDRAWN'),
            'SUSPEND':({'VERIFIED'},'SUSPENDED'),'REVOKE':({'VERIFIED','SUSPENDED'},'REVOKED')}
        if action not in transitions or state not in transitions[action][0]:raise RuleError('当前状态不能执行此操作，请核对历史。')
        case.state=transitions[action][1]
        if grant:
            grant.is_active=False;grant.revision+=1;grant.save(update_fields=['is_active','revision'])
    case.revision+=1;case.save(update_fields=['delegate_user','state','revision'])
    _record(actor,case,p['operation'],action,state,d)
    return case,False


@transaction.atomic
def select_subject(*,actor,key):
    from workspaces.context import require_active
    require_writable(actor);require_active(actor,('PATIENT',))
    ctx=getattr(actor,'_adc_workspace',None)
    if ctx is None:raise PermissionDenied('请先进入患者服务。')
    if key=='self':
        if not PatientAccess.objects.filter(user=actor,is_active=True,patient__is_active=True).exists():raise PermissionDenied('没有有效本人入口。')
        selected=None
    else:
        try:
            prefix,pk=key.split(':',1)
            if prefix!='grant':raise ValueError
            pk=int(pk)
        except (ValueError,AttributeError):raise RuleError('请选择清单中的就诊人。') from None
        # Same case -> grant order as revocation and booking confirmation.
        case_id=active_grants(actor).filter(pk=pk).values_list('relationship_id',flat=True).first()
        PatientRelationship.objects.select_for_update().filter(pk=case_id).first()
        selected=active_grants(actor).select_for_update(of=('self',)).filter(pk=pk).first()
        if selected is None:raise PermissionDenied('这项代约授权已失效，请刷新清单。')
    ctx.patient_grant=selected;ctx.revision+=1
    ctx.save(update_fields=['patient_grant','revision','updated_at'])
    emit(actor,'PATIENT_SUBJECT_SELECTED',ctx,summary={'capacity':'DELEGATE' if selected else 'SELF'})
    return ctx
