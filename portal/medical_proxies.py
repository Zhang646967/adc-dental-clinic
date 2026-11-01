"""Front-desk material verification followed by explicit clinical applicability."""
from datetime import datetime
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import OuterRef, Subquery, F
from django.utils import timezone
from accounts.models import UserAccount
from accounts.policies import bindings, lock_clinic_grant, require_writable
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import professional_scope, require_reviewer
from clinical.authority_services import lock_people
from clinical.consent_models import ConsentVersion
from clinical.consents import text as clinical_text
from clinical.plan_models import TreatmentPlan, TreatmentStep
from patients.models import Patient
from patients.selectors import visible_patients
from portal.medical_models import MedicalProxy, MedicalProxyVersion, MedicalProxyScope, MedicalProxyEvent
from portal.medical_authority import latest_version
from portal.models import PatientAccess
from workspaces.context import require_active

CONTRACT = 'adc.medical-proxy.c32b2.v1'
ROLES = ('FRONT_DESK','DENTIST','PATIENT')


def text(value, label, limit=1000):
    if not isinstance(value,str) or not 4 <= len(value.strip()) <= limit:
        raise RuleError(label + '请填写4至' + str(limit) + '字。')
    return value.strip()


def front(actor, *, lock=False):
    require_active(actor, ('FRONT_DESK',))
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or ctx.clinic_id is None: raise PermissionDenied('请先选择本店前台工作范围。')
    grant = lock_clinic_grant(actor,ctx.clinic_id) if lock else bindings(actor).filter(role='FRONT_DESK',clinic_id=ctx.clinic_id).first()
    if grant is None or not grant.can_verify_medical_proxy_identity:
        raise PermissionDenied('需要本店专项医疗代理资料核验职责。')
    return ctx.clinic_id


def can_read(actor, case):
    require_active(actor, ROLES)
    role = actor._adc_workspace.role
    if role == 'FRONT_DESK':
        if front(actor) != case.clinic_id: raise PermissionDenied('请在核验诊所办理。')
    elif role == 'DENTIST':
        version = latest_version(case)
        visit = version.plan.origin_encounter.visit
        if actor.dentist_id != visit.dentist_id: require_reviewer(actor,case.clinic_id)
        for step in version.scopes.select_related('step').all():
            row = step.step.versions.order_by('-version__revision').first()
            if row is None: raise RuleError('未找到指定步骤的保留版本，请由负责医师核对。')
            professional_scope(actor.pk,case.clinic_id,row.service_id,'READ')
    elif case.delegate_id != actor.pk and not PatientAccess.objects.filter(user=actor,patient=case.patient,is_active=True).exists():
        raise PermissionDenied('只能查看本人相关的医疗授权办理记录。')
    return case


def material_fields(actor, fields):
    clinic_id = front(actor)
    patient = visible_patients(actor).get(patient_no=fields.get('patient_no'),is_active=True)
    user = UserAccount.objects.get(username=fields.get('username'),is_active=True)
    if PatientAccess.objects.filter(user=user,patient=patient).exists():
        raise RuleError('本人账号不应登记为本人医疗代理，请走本人核验。')
    plan = TreatmentPlan.objects.select_related('origin_encounter__visit').get(pk=fields.get('plan'))
    if (plan.origin_encounter.visit.patient_id,plan.origin_encounter.visit.clinic_id)!=(patient.pk,clinic_id):
        raise PermissionDenied('请仅核对本店本患者的方案编号。')
    try:
        steps = sorted(set(int(v) for v in fields.get('steps',[])))
        start,end = [datetime.fromisoformat(str(fields[k])) for k in ('valid_from','valid_until')]
        if not 1 <= len(steps) <= 30 or TreatmentStep.objects.filter(plan=plan,pk__in=steps).count()!=len(steps): raise ValueError
        if not timezone.is_aware(start) or not timezone.is_aware(end) or not start < end or end <= timezone.now(): raise ValueError
    except (ValueError,TypeError,KeyError): raise RuleError('请明确本方案步骤及带时区的有效时间，不超过30步。') from None
    kind=fields.get('kind')
    if kind not in ('GUARDIAN','WRITTEN'): raise RuleError('请选择本批支持的监护或书面委托类型。')
    today=timezone.localdate();born=patient.date_of_birth
    adult=(today.year-born.year-((today.month,today.day)<(born.month,born.day)))>=18
    if adult != (kind=='WRITTEN'): raise RuleError('本批监护用于未成年场景，成年书面委托须另有适用依据；年龄本身不证明决定能力。')
    return dict(patient=patient.pk,clinic=clinic_id,delegate=user.pk,kind=kind,plan=plan.pk,steps=steps,
        patient_snapshot=dict(id=patient.pk,name=patient.name,date_of_birth=patient.date_of_birth.isoformat()),
        delegate_name=clinical_text(fields.get('delegate_name'),'已核对代理人姓名',100,True),
        identity_reference=text(fields.get('identity_reference'),'身份核对材料编号',500),
        authority_reference=text(fields.get('authority_reference'),'监护或书面委托依据编号',500),
        applicability=text(fields.get('applicability'),'本次适用情形'),valid_from=start.isoformat(),valid_until=end.isoformat())


@transaction.atomic
def prepare_submit(*,actor,fields,case_id=None):
    require_writable(actor);values=material_fields(actor,fields);case=None
    if case_id:
        case=can_read(actor,MedicalProxy.objects.get(pk=case_id))
        if (case.patient_id,case.clinic_id,case.delegate_id,case.kind)!=(values['patient'],values['clinic'],values['delegate'],values['kind']):
            raise RuleError('患者、诊所、代理人与依据类型不得覆盖；请另行办理。')
        if case.state not in ('RETURNED','SUSPENDED'): raise RuleError('请先退回或暂停原授权，再补充新版资料。')
    return dict(proposal_token=proposal(actor,CONTRACT,('FRONT_DESK',),dict(action='SUBMIT',case=case_id,
        revision=case.revision if case else 0,values=values)))


@transaction.atomic
def prepare_action(*,actor,case_id,action,note,applicable=False):
    case=can_read(actor,MedicalProxy.objects.get(pk=case_id));require_writable(actor)
    return dict(proposal_token=proposal(actor,CONTRACT,ROLES,dict(action=action,case=case.pk,revision=case.revision,
        version=latest_version(case).pk,note=text(note,'办理依据'),applicable=applicable)))


def record(actor,case,version,operation,action,note,reviewer=None):
    case.revision+=1;case.save(update_fields=['state','revision'])
    event=MedicalProxyEvent.objects.create(proxy=case,version=version,sequence=case.revision,action=action,
        resulting_state=case.state,actor=actor,note=note,reviewer=reviewer,operation_id=operation)
    emit(actor,'MEDICAL_PROXY_'+action,event,summary=dict(proxy=case.pk,version=version.pk,action=action))
    return case


@business_errors
@transaction.atomic
def confirm(*,actor,proposal_token,confirmed):
    if confirmed is not True: raise RuleError('请明确核对本次医疗授权办理；不自动授予预约或病历权限。')
    p=read_proposal(actor,CONTRACT,ROLES,proposal_token);d=p['data'];case=MedicalProxy.objects.filter(pk=d['case']).first() if d['case'] else None
    delegate=d['values']['delegate'] if d['action']=='SUBMIT' else case.delegate_id
    lock_people(actor,delegate)
    if case:case=MedicalProxy.objects.select_for_update().get(pk=case.pk)
    read_proposal(actor,CONTRACT,ROLES,proposal_token)
    old=MedicalProxyEvent.objects.filter(operation_id=p['operation']).first()
    if old:
        if old.actor_id!=actor.pk:raise PermissionDenied('原提交属于其他账号。')
        return old.proxy,True
    if case and case.revision!=d['revision']:raise RuleError('医疗代理记录已变化，请重新核对。')
    action=d['action'];reviewer=None
    if action=='SUBMIT':
        v=d['values'];front(actor,lock=True)
        patient=Patient.objects.select_for_update().get(pk=v['patient'],is_active=True)
        if v['patient_snapshot']!=dict(id=patient.pk,name=patient.name,date_of_birth=patient.date_of_birth.isoformat()):
            raise RuleError('患者身份资料已变化，请重新核对材料后预览。')
        if not UserAccount.objects.filter(pk=delegate,is_active=True).exists():raise RuleError('代理账号已停用。')
        plan=TreatmentPlan.objects.select_for_update().select_related('origin_encounter__visit').get(pk=v['plan'])
        if (plan.origin_encounter.visit.patient_id,plan.origin_encounter.visit.clinic_id)!=(v['patient'],v['clinic']):raise PermissionDenied('原方案归属已变化。')
        if case is None:
            if MedicalProxy.objects.filter(patient_id=v['patient'],clinic_id=v['clinic'],delegate_id=delegate,kind=v['kind']).exclude(state__in=['REJECTED','REVOKED']).exists():
                raise RuleError('已有本患者与代理人的办理单，请继续原记录。')
            case=MedicalProxy.objects.create(patient_id=v['patient'],clinic_id=v['clinic'],delegate_id=delegate,kind=v['kind'],created_by=actor)
        elif case.state not in ('RETURNED','SUSPENDED'):raise RuleError('当前状态不能替换资料版本。')
        number=(latest_version(case).number+1) if latest_version(case) else 1
        version=MedicalProxyVersion.objects.create(proxy=case,number=number,plan_id=v['plan'],submitted_by=actor,
            **{k:v[k] for k in ('identity_reference','authority_reference','applicability','valid_from','valid_until','patient_snapshot','delegate_name')})
        for step in v['steps']:MedicalProxyScope.objects.create(version=version,step_id=step)
        case.state='MATERIALS';note='已受理独立医疗代理资料，尚未核验或生效。'
    else:
        version=latest_version(case);can_read(actor,case);role=actor._adc_workspace.role;note=d['note']
        if version.pk!=d['version']:raise RuleError('代理资料已有新版本，请重新核对。')
        if action=='MATERIALS_OK':
            if front(actor,lock=True)!=case.clinic_id or actor.pk==delegate:raise PermissionDenied('不得核验自己作为代理人的资料。')
            if case.state!='MATERIALS':raise RuleError('仅待资料核对记录可提交医师。')
            case.state='DOCTOR'
        elif action in ('APPROVE','RETURN','REJECT','ESCALATE'):
            require_active(actor,('DENTIST',))
            if actor.pk==delegate:raise PermissionDenied('不得确认自己作为代理人的医疗适用性。')
            if case.state not in ('DOCTOR','REVIEW'):raise RuleError('请先由前台完成专项资料核对。')
            if case.state=='REVIEW' or actor.dentist_id!=version.plan.origin_encounter.visit.dentist_id:
                reviewer=require_reviewer(actor,case.clinic_id,lock=True)
                previous=case.events.filter(action='ESCALATE').order_by('-pk').first()
                if previous and previous.actor_id==actor.pk:raise RuleError('疑难事项须由另一名有职责的审核医师确认。')
            for scope in version.scopes.select_related('step'):
                from clinical.plans import current_version
                row=current_version(version.plan).steps.filter(step=scope.step).first()
                if row is None:raise RuleError('指定步骤已不在当前方案中，请退回核对本次代理范围。')
                professional_scope(actor.pk,case.clinic_id,row.service_id,'RECORD',lock=True)
            if action=='APPROVE':
                identity_review=case.events.filter(version=version,action='MATERIALS_OK').order_by('-pk').first()
                if actor.pk==version.submitted_by_id or (identity_review and identity_review.actor_id==actor.pk):
                    raise PermissionDenied('资料整理或身份核验人不能切换身份确认自己的办理，请转另一名有职责的医师。')
                if d['applicable'] is not True:raise RuleError('医师须明确核对本次医疗代理适用情形和范围。')
                patient=Patient.objects.select_for_update().get(pk=case.patient_id,is_active=True)
                if version.patient_snapshot!=dict(id=patient.pk,name=patient.name,date_of_birth=patient.date_of_birth.isoformat()):
                    raise RuleError('患者身份资料在材料核对后发生变化，请退回重新核对。')
                if version.valid_until<=timezone.now():raise RuleError('材料授权期限已到，请退回核对。')
                latest=MedicalProxyVersion.objects.filter(proxy_id=OuterRef('version__proxy_id')).order_by('-number').values('number')[:1]
                conflicts=MedicalProxyScope.objects.annotate(current_number=Subquery(latest)).filter(
                    version__number=F('current_number'),step_id__in=version.scopes.values('step_id'),
                    version__proxy__patient=case.patient,version__proxy__clinic=case.clinic,version__proxy__state='ACTIVE',
                    version__valid_from__lt=version.valid_until,version__valid_until__gt=version.valid_from).exclude(version__proxy=case)
                if conflicts.exists():raise RuleError('这些步骤另有有效医疗代理，请先核对签署人并明确暂停或撤销原依据。')
                case.state='ACTIVE'
            else:case.state={'RETURN':'RETURNED','REJECT':'REJECTED','ESCALATE':'REVIEW'}[action]
        elif action in ('SUSPEND','REVOKE'):
            if role=='FRONT_DESK':front(actor,lock=True)
            elif role=='PATIENT':
                if action!='REVOKE':raise PermissionDenied('患者端只能明确撤销／放弃本项授权。')
            elif role!='DENTIST':raise PermissionDenied('没有本项授权处置权限。')
            if case.state not in ('ACTIVE','SUSPENDED','MATERIALS','DOCTOR','REVIEW','RETURNED'):raise RuleError('此记录已经结束。')
            case.state='SUSPENDED' if action=='SUSPEND' else 'REVOKED'
        else:raise RuleError('请选择明确的医疗代理办理动作。')
    return record(actor,case,version,p['operation'],action,note,reviewer),False
