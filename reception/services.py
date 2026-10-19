"""Telephone reception owns communication, responsibility and booking linkage.

No telephone-number merge; no clinical-access grants; no treatment or money.
All money and care commands remain in their original modules.
"""
from datetime import datetime,date
from uuid import uuid4
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import RoleAssignment,UserAccount
from accounts.policies import require_clinic,lock_clinic_grant
from adc_core.rules import RuleError
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from care.audit import emit
from patients.models import Patient
from scheduling.resource_models import BookingService
from reception.models import ReceptionCase,ReceptionCommunication,REASONS

CONTRACT='adc.reception.action.v1'
TERMINAL={'BOOKED','UNBOOKED','WITHDRAWN'}

def clinic_for(actor,lock=False):
    ctx=getattr(actor,'_adc_workspace',None)
    if not ctx or ctx.role!='FRONT_DESK' or not ctx.clinic_id:raise PermissionDenied('请进入本店前台工作台。')
    (lock_clinic_grant if lock else require_clinic)(actor,ctx.clinic_id)
    return ctx.clinic_id

def cases_for(actor):
    return ReceptionCase.objects.filter(clinic_id=clinic_for(actor)).select_related('owner','service','preferred_dentist','visit','patient','wait_request')

def contact_owners(clinic):
    return UserAccount.objects.filter(is_active=True,role_assignments__is_active=True,
        role_assignments__role='FRONT_DESK',role_assignments__scope_kind='CLINIC',
        role_assignments__clinic_id=clinic).distinct().order_by('username')

def _owner(owner,clinic,lock=False):
    q=RoleAssignment.objects.filter(user_id=owner,is_active=True,role='FRONT_DESK',scope_kind='CLINIC',clinic_id=clinic)
    if lock:q=q.select_for_update()
    if not q.exists() or not UserAccount.objects.filter(pk=owner,is_active=True).exists():
        raise RuleError('负责人已停用或本店前台授权失效，请重新分配并保留交接说明。')

def _text(value,size,required=True):
    if type(value) is not str or len(value.strip())>size or (required and not value.strip()):raise RuleError('请填写完整且未超长的接待资料。')
    return value.strip()

def _at(value):
    if isinstance(value,str):value=datetime.fromisoformat(value)
    if not isinstance(value,datetime) or timezone.is_naive(value):raise RuleError('请填写明确的下次联系时间。')
    return value

def _patient(number):
    if not number:return None
    patient=Patient.objects.get(patient_no=number,is_active=True)
    patient.full_clean()
    return patient

def _fields(clinic,action,fields,row=None,lock=False):
    d=dict(fields);clean={}
    clean['note']=_text(d.get('note',''),2000)
    if action in ('CREATE','UPDATE'):
        for k,n in [('caller_name',80),('relationship',80),('contact',120),('patient_hint',80)]:clean[k]=_text(d.get(k,''),n,k!='patient_hint')
    if action in ('CREATE','UPDATE','ASSIGN'):
        clean['owner']=int(d['owner']);_owner(clean['owner'],clinic,lock)
        clean['due_at']=_at(d['due_at']) if d.get('due_at') else None
        if action!='ASSIGN':
            clean['state']=d.get('state','VERIFY')
            if clean['state'] not in ('VERIFY','CONTACT','CONFIRM'):raise RuleError('请选择待核对、待联系或待患者确认。')
            if row and row.state=='WAITLIST':clean['state']='WAITLIST'
            clean['patient_no']=_text(d.get('patient_no',''),40,False)
            patient=_patient(clean['patient_no'])
            if row and row.wait_request_id and patient and patient.pk!=row.patient_id:
                raise RuleError('已有候补关联，不能更换患者；请保留原记录并重新受理。')
            clean['service_id']=int(d['service_id']) if d.get('service_id') else None
            service=BookingService.objects.get(pk=clean['service_id'],department__clinic_id=clinic) if clean['service_id'] else None
            clean['dentist_id']=int(d['dentist_id']) if d.get('dentist_id') else None
            if row and row.wait_request_id and (not patient or patient.pk!=row.patient_id or clean['service_id']!=row.service_id or clean['dentist_id']!=row.preferred_dentist_id):
                raise RuleError('已转候补的患者、服务和医师偏好须通过原候补核对，不能在接待单另行覆盖。')
            if clean['dentist_id']:
                from registry.models import Dentist
                Dentist.objects.get(pk=clean['dentist_id'],is_active=True)
                if service and not service.dentists.filter(pk=clean['dentist_id']).exists():raise RuleError('偏好医师不接收该预约服务，请与患者重新协商。')
            clean['preferred_day']=date.fromisoformat(d['preferred_day']) if d.get('preferred_day') else None
        if (clean.get('state') in ('CONTACT','CONFIRM','WAITLIST') or (row and row.state=='WAITLIST')) and not clean['due_at']:
            raise RuleError('待联系、待确认和候补等待必须有负责人及下次联系期限。')
    elif action=='UNBOOKED':
        clean['reason_code']=d.get('reason_code','')
        if clean['reason_code'] not in dict(REASONS):raise RuleError('请选择未成约原因。')
    elif action in ('WITHDRAW','NOTE','LINK_WAITLIST'):
        pass
    elif action=='WAITLIST':
        if not row or not row.patient_id or not row.service_id:raise RuleError('转候补前请完成患者建档并核实预约服务。')
        _patient(row.patient.patient_no)
        clean['earliest']=_at(d['earliest']);clean['latest']=_at(d['latest'])
        from coordination.windows import validate_wait_window,WindowError
        from datetime import timedelta
        try:
            validate_wait_window(clean['earliest'],clean['latest'],now=timezone.now(),minimum=timedelta(minutes=row.service.duration_minutes))
        except WindowError as exc:
            raise RuleError(str(exc)) from exc
        clean['due_at']=_at(d['due_at']);_owner(row.owner_id,clinic,lock)
    elif action=='BOOK':
        if not row or not row.patient_id or not row.service_id:raise RuleError('成约前请完成患者建档并核实预约服务。')
        if row.wait_request_id:raise RuleError('该接待已转候补，请处理原邀约并关联成功结果，不能再次直接创建。')
        if d.get('consent') is not True:raise RuleError('请复述诊所、服务、医师、起止时间并取得患者明确同意。')
        from scheduling.booking import prepare_booking
        result=prepare_booking(actor=d['_actor'],patient_no=row.patient.patient_no,slot_id=int(d['slot_id']),
            start=_at(d['start']),end=_at(d['end']),service_id=row.service_id,consent=True)
        clean['booking_token']=result['proposal_token']
        clean['booking_summary']={'clinic':result['slot'].clinic.name,'dentist':result['slot'].dentist.name,
            'service':result['resources']['service']['name'] if result['resources'] else row.service.name,
            'start':result['start'].isoformat(),'end':result['end'].isoformat(),
            'room':result['resources']['room']['name'] if result['resources'] else '尚未纳入资源模式'}
    else:raise RuleError('接待操作无效。')
    return clean

def _serial(d):
    return {k:(v.isoformat() if isinstance(v,(date,datetime)) else v) for k,v in d.items()}

def prepare_case(*,actor,action,fields,case_id=None,expected_revision=None):
    clinic=clinic_for(actor);row=cases_for(actor).get(pk=case_id) if case_id else None
    if (action=='CREATE')!=(row is None):raise RuleError('接待来源无效。')
    if row and row.revision!=expected_revision:raise RuleError('接待单已变化，请刷新核对沟通记录。')
    if row and row.state in TERMINAL and action not in ('NOTE','ASSIGN'):
        raise RuleError('接待已结束，成约事实与结果继续保留；后续取消或改期请打开原预约。')
    clean=_fields(clinic,action,dict(fields,_actor=actor),row)
    data={'case':row.pk if row else None,'revision':row.revision if row else None,'action':action,'fields':_serial(clean)}
    return {'case':row,'action':action,'fields':clean,'proposal_token':proposal(actor,CONTRACT,('FRONT_DESK',),data)}

def _append(row,actor,action,note,operation):
    row.revision+=1;row.save()
    event=ReceptionCommunication.objects.create(case=row,actor=actor,kind=action,note=note,sequence=row.revision,
        operation_id=operation,snapshot={'caller_name':row.caller_name,'relationship':row.relationship,'contact':row.contact,'patient_hint':row.patient_hint,'state':row.state,'owner':row.owner_id,'due_at':row.due_at.isoformat() if row.due_at else None,
            'patient':row.patient_id,'service':row.service_id,'visit':row.visit_id,'wait_request':row.wait_request_id,'reason':row.reason_code})
    emit(actor,'RECEPTION_RECORDED',event,summary={'clinic_id':row.clinic_id,'action':action,'revision':row.revision})
    return row

@business_errors
@transaction.atomic
def confirm_case(*,actor,proposal_token,confirmed,expected_case_id=None):
    if confirmed is not True:raise RuleError('请核对本次沟通与办理结果后明确确认。')
    p=read_proposal(actor,CONTRACT,('FRONT_DESK',),proposal_token);d=p['data']
    if expected_case_id is not None and d['case']!=expected_case_id:raise RuleError('确认内容不属于此接待单，请重新打开原记录。')
    clinic=clinic_for(actor,lock=True)
    old=ReceptionCommunication.objects.filter(operation_id=p['operation'],actor=actor,case__clinic_id=clinic).first()
    if old:return cases_for(actor).get(pk=old.case_id),True
    row=ReceptionCase.objects.select_for_update().get(pk=d['case'],clinic_id=clinic) if d['case'] else None
    if row and row.revision!=d['revision']:raise RuleError('接待单已有新沟通，请刷新后继续办理。')
    action=d['action'];fields=d['fields']
    if row and row.state in TERMINAL and action not in ('NOTE','ASSIGN'):raise RuleError('接待已结束，请核对原预约及后续关联结果。')
    # Booking token already binds the observed resources and patient's explicit
    # consent. Do not regenerate a fresh proposal from hidden confirmation data.
    if action=='BOOK':
        if not row.patient_id or row.wait_request_id:raise RuleError('请通过原候补办理，不能重复成约。')
        from scheduling.booking import confirm_booking
        visit,_=confirm_booking(actor=actor,proposal_token=fields['booking_token'],confirmed=True)
        if visit.patient_id!=row.patient_id or visit.clinic_id!=clinic:raise RuleError('预约与接待来源不一致。')
        row.visit=visit;row.state='BOOKED';row.due_at=None
    else:
        # Revalidate directory, owner, patient identity and deadlines inside the
        # same transaction; signed data is a proposal, not current authority.
        clean=_fields(clinic,action,fields,row,lock=True)
        if action=='CREATE':
            row=ReceptionCase(clinic_id=clinic,created_by=actor)
        if action in ('CREATE','UPDATE'):
            for k in ('caller_name','relationship','contact','patient_hint'):setattr(row,k,clean[k])
        if action in ('CREATE','UPDATE','ASSIGN'):
            row.owner_id=clean['owner'];row.due_at=clean['due_at']
            if action!='ASSIGN':
                row.state=clean['state'];row.patient=_patient(clean['patient_no']);row.service_id=clean['service_id']
                row.preferred_dentist_id=clean['dentist_id'];row.preferred_day=clean['preferred_day']
        elif action=='UNBOOKED':
            if row.wait_request_id:
                from coordination.services import withdraw
                withdraw(actor=actor,entry_id=row.wait_request_id)
            row.state='UNBOOKED';row.reason_code=clean['reason_code'];row.due_at=None
        elif action=='WITHDRAW':
            if row.wait_request_id:
                from coordination.services import withdraw
                withdraw(actor=actor,entry_id=row.wait_request_id)
            row.state='WITHDRAWN';row.due_at=None
        elif action=='WAITLIST':
            if row.wait_request_id:raise RuleError('已有候补关联，请处理原候补。')
            from coordination.services import join_waitlist
            entry=join_waitlist(actor=actor,clinic_id=clinic,earliest=clean['earliest'],latest=clean['latest'],
                patient_no=row.patient.patient_no,dentist_id=row.preferred_dentist_id,service_id=row.service_id)
            row.wait_request=entry;row.state='WAITLIST';row.due_at=clean['due_at']
        elif action=='LINK_WAITLIST':
            if not row.wait_request_id:raise RuleError('没有关联候补。')
            from coordination.models import WaitOffer
            offer=WaitOffer.objects.filter(request_id=row.wait_request_id,state='ACCEPTED',visit__isnull=False).first()
            if not offer:raise RuleError('候补尚未形成成功预约，请继续联系患者确认原邀约。')
            row.visit=offer.visit;row.state='BOOKED';row.due_at=None
    row.full_clean()
    return _append(row,actor,action,fields['note'],p['operation']),False

def lock_waitlist_case(entry_id):
    # Called after offer authorization, before slot/advisory locks. The link is
    # an internal business result, never a grant to read private caller details.
    return ReceptionCase.objects.select_for_update().filter(wait_request_id=entry_id).first()

def link_waitlist_result_locked(row,entry,visit,actor):
    if row is None:return
    if row.visit_id:
        if row.visit_id!=visit.pk:raise RuleError('接待已有其他成约事实，请核对原结果。')
        return
    if row.state!='WAITLIST' or row.patient_id!=visit.patient_id or row.clinic_id!=visit.clinic_id:
        raise RuleError('原接待与候补成约结果不一致，未重复创建预约。')
    row.visit=visit;row.state='BOOKED';row.due_at=None
    _append(row,actor,'WAIT_ACCEPTED','患者或授权前台明确接受原邀约；关联同一成功预约。',uuid4())
