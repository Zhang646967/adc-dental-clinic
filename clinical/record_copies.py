"""One application, explicit scope and recipient, independent review, authenticated pickup."""
from datetime import datetime,timedelta
import hashlib,uuid
from django.conf import settings
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from accounts.models import UserAccount,RoleAssignment
from accounts.policies import require_writable
from accounts.external_identity import _account_actor
from adc_core.commands import business_errors
from adc_core.proposals import workspace_binding
from adc_core.rules import RuleError
from care.audit import emit
from clinical.authority import require_reviewer,professional_scope
from clinical.archive_models import ArchivePackage
from clinical.archive_sources import digest,required_services
from clinical.authority_services import text
from clinical.copy_models import RecordCopyRequest,RecordCopyItem,RecordCopyFile,RecordCopyEvent
from clinical.models import ClinicalReviewerAppointment
from patients.models import Patient
from portal.models import PatientAccess
from portal.policies import patient_access,has_patient_account
from scheduling.models import Visit
from workspaces.context import require_active

CONTRACT='adc.record-copy.c33b.v1'
PICKUP='adc.record-copy-pickup.c33b.v1'
SECTIONS={'DOCUMENT':'病历与检查','TREATMENT':'方案与实际治疗','CONSENT':'告知、问答与决定','FEES':'选定版本医疗费用'}
OPEN=['PENDING','NEED_INFO','REVIEW','APPROVED','FAILED','READY','DELIVERED']


def binding(actor):
    ctx=getattr(actor,'_adc_workspace',None)
    if ctx and ctx.role in ('FRONT_DESK','DENTIST'):
        return workspace_binding(actor,(ctx.role,))
    _account_actor(actor)
    return dict(user=actor.pk,context=str(ctx.pk) if ctx else None,revision=ctx.revision if ctx else None,channel='PATIENT')


def require_copy_write(actor):
    """Copy-only recipients use their account channel, without a new patient-chart grant."""
    ctx=getattr(actor,'_adc_workspace',None)
    if ctx and ctx.role in ('FRONT_DESK','DENTIST'):return require_writable(actor)
    if settings.ADC_READ_ONLY:raise PermissionDenied('当前环境只读。')
    _account_actor(actor)
    if ctx is None:raise PermissionDenied('请先从患者渠道登录领取账号。')
    from workspaces.models import WorkspaceContext
    current=WorkspaceContext.objects.select_for_update().get(pk=ctx.pk,user=actor)
    if current.revision!=ctx.revision or current.login_channel!='PATIENT' or current.role not in ('','PATIENT'):
        raise PermissionDenied('领取账号或工作范围已变化，请重新核对。')


def front(actor,clinic_id=None,*,lock=False):
    require_active(actor,('FRONT_DESK',),clinic_id)
    rows=RoleAssignment.objects.filter(user=actor,role='FRONT_DESK',clinic_id=actor._adc_workspace.clinic_id,
        scope_kind='CLINIC',is_active=True,can_verify_record_copies=True,clinic__is_active=True)
    if lock:rows=rows.select_for_update()
    duty=rows.first()
    if duty is None:raise PermissionDenied('尚未登记本店病历副本材料核验职责。')
    return duty


def identity(row):
    p=Patient.objects.get(pk=row.patient_id)
    return dict(patient=p.pk,name=p.name,birth=p.date_of_birth.isoformat(),active=p.is_active,
        recipient=row.recipient_id,recipient_name=row.recipient_name,kind=row.kind)


def recipient(row,actor,*,pickup=False):
    _account_actor(actor)
    if row.recipient_id!=actor.pk:raise PermissionDenied('本申请不属于当前领取账号。')
    if row.kind=='SELF':
        access=patient_access(actor,self_only=True)
        if access.patient_id!=row.patient_id:raise PermissionDenied('请切换至本申请的本人就诊档案。')
    if pickup:
        if row.state not in ('READY','DELIVERED') or not row.pickup_until or timezone.now()>=row.pickup_until:
            raise RuleError('当前不可领取或领取期限已到，请联系门店重新核验；原申请与文件保留。')
        if identity(row)!=row.identity_snapshot or not row.clinic.is_active:
            raise RuleError('身份或机构资料已变化，请联系门店重新核验。')
        if not review_valid(row):raise RuleError('本次独立审核职责或查阅范围已变化，请联系门店核对。')


def items(row):return row.items.select_related('visit__dentist','package__submission','package__archive__encounter__visit').order_by('visit_id')


def review_authority(actor,row,*,lock=False):
    appointed=require_reviewer(actor,row.clinic_id,lock=lock)
    if not appointed.can_review_copies:raise PermissionDenied('没有本店病历副本独立审核职责。')
    if actor.pk in (row.recipient_id,row.created_by_id,row.verified_by_id) or row.items.filter(visit__dentist_id=actor.dentist_id).exists():
        raise PermissionDenied('须由不同于申请人、材料核验人及原负责医师的指定医师独立审核。')
    scopes=[]
    for item in items(row):
        if not item.package_id:raise RuleError('所申请就诊尚无固定文件，请先完成归档；本申请继续保留。')
        for service in required_services(item.visit,item.package.manifest['source_snapshot']):
            auth=professional_scope(actor.pk,row.clinic_id,service,'READ',lock=lock)
            scopes.append([auth.pk,auth.revision])
    return appointed,sorted({tuple(s) for s in scopes})


def review_valid(row):
    if not row.reviewed_by_id:return False
    now=timezone.now();a=row.approval
    if not UserAccount.objects.filter(pk=row.reviewed_by_id,is_active=True,dentist__is_active=True).exists():return False
    if not ClinicalReviewerAppointment.objects.filter(pk=a.get('reviewer'),user_id=row.reviewed_by_id,clinic_id=row.clinic_id,
        revision=a.get('revision'),is_active=True,can_review_copies=True,valid_from__lte=now,valid_until__gt=now).exists():return False
    from clinical.models import ProfessionalAuthorization
    try:
        for pk,revision in a['scopes']:
            old=ProfessionalAuthorization.objects.get(pk=pk)
            current=professional_scope(row.reviewed_by_id,row.clinic_id,old.service_id,'READ')
            if [current.pk,current.revision]!=[pk,revision]:return False
    except (PermissionDenied,ProfessionalAuthorization.DoesNotExist,KeyError):return False
    return True


def source_stamp(row):
    return [[i.pk,i.visit_id,i.package_id,list(i.sections),i.package.pdf_sha256 if i.package_id else None] for i in items(row)]


def record(actor,row,action,operation,snapshot=None):
    e=RecordCopyEvent.objects.create(request=row,actor=actor,action=action,operation_id=operation,
        snapshot=dict(state=row.state,revision=row.revision,**(snapshot or {})))
    emit(actor,'RECORD_COPY_CHANGED',row,summary={'action':action,'clinic_id':row.clinic_id,'state':row.state})
    return e


def _create_data(actor,fields,staff):
    if staff:
        duty=front(actor)
        patient=Patient.objects.get(patient_no=fields['patient_no'],is_active=True)
        clinic=duty.clinic
        user=UserAccount.objects.get(username=fields['recipient_account'],is_active=True)
        if not has_patient_account(user):raise RuleError('领取人须先注册患者渠道账号，本操作不创建或重置账号。')
        kind=fields['kind']
        if kind not in ('GUARDIAN','WRITTEN'):raise RuleError('前台代办仅登记本用途监护或书面委托，不转换已有代约授权。')
    else:
        access=patient_access(actor,self_only=True);patient=access.patient;user=actor;kind='SELF'
        from registry.models import Clinic
        clinic=Clinic.objects.get(pk=fields['clinic'],is_active=True)
    ids=sorted(set(int(x) for x in fields['visits']))
    groups=sorted(set(fields['sections']))
    if not 1<=len(ids)<=10 or not groups or set(groups)-SECTIONS.keys():raise RuleError('请选择1至10次同店就诊及所需资料类别。')
    visits=list(Visit.objects.filter(pk__in=ids,patient=patient,clinic=clinic,status__in=['COMPLETED','CLOSED_NO_TREATMENT']).order_by('pk'))
    if len(visits)!=len(ids):raise PermissionDenied('就诊范围必须属于已核对患者和当前诊所的已结束接诊。')
    selected_package=fields.get('package')
    if selected_package and len(visits)!=1:raise RuleError('指定历史归档版本时请单独申请该次就诊。')
    sources=[]
    for v in visits:
        packages=ArchivePackage.objects.filter(archive__encounter__visit=v)
        package=packages.get(pk=selected_package) if selected_package else packages.order_by('-number').first()
        sources.append(dict(visit=v.pk,package=package.pk if package else None,sections=groups))
    name=patient.name if kind=='SELF' else str(fields['recipient_name']).strip()
    if not 1<=len(name)<=80:raise RuleError('请填写经核对的领取人姓名。')
    return dict(patient=patient.pk,clinic=clinic.pk,recipient=user.pk,kind=kind,
        purpose=text(fields['purpose'],'复制用途',500),recipient_name=name,sources=sources)


def _validate(actor,row,action,fields):
    if action in ('VERIFY','REVOKE','RETRY'):
        front(actor,row.clinic_id)
        if actor.pk==row.recipient_id:raise PermissionDenied('不能受理或撤销本人作为领取人的申请，请交另一有职责前台。')
    elif action=='REVIEW':review_authority(actor,row)
    else:recipient(row,actor,pickup=action=='CLAIM')
    if action=='VERIFY':
        if row.state!='PENDING':raise RuleError('请在待核验申请上办理；退回后由申请人明确补充再提交。')
        decision=fields['decision']
        if decision not in ('VERIFY','RETURN','REJECT'):raise RuleError('请选择核验、退回或不通过。')
        if decision!='VERIFY':return dict(decision=decision,message=text(fields['message'],'患者可见说明',500))
        if not fields.get('purpose_checked'):raise RuleError('请明确核对本用途、范围、领取账号及领取人。')
        if fields['basis'] not in ('IN_PERSON','ORIGINAL_CONTACT'):raise RuleError('请选择实际采用的身份核对方式。')
        if row.kind!='SELF' and not fields.get('authority_reference'):raise RuleError('请登记本用途的监护或书面委托原件编号。')
        if row.kind=='SELF' and not PatientAccess.objects.filter(user=row.recipient_id,patient=row.patient_id,is_active=True,patient__is_active=True).exists():raise RuleError('本人档案关联已失效，请先恢复原本人关联。')
        if row.kind=='GUARDIAN':
            birth=row.patient.date_of_birth;today=timezone.localdate()
            if (today.year-birth.year-((today.month,today.day)<(birth.month,birth.day)))>=18:raise RuleError('本批监护复制适用于未成年患者；其他主体资格请转人工专门核验。')
        until=fields['pickup_until']
        if not isinstance(until,datetime) or not timezone.is_aware(until) or not timezone.now()<until<=timezone.now()+timedelta(days=30):raise RuleError('请填写未来30日内的领取期限。')
        sources=[]
        for i in items(row):
            package=i.package or ArchivePackage.objects.filter(archive__encounter__visit=i.visit).order_by('-number').first()
            if not package:raise RuleError('所申请就诊缺少固定文件，请联系负责医师完成归档；申请保留且不受欠费影响。')
            sources.append([i.pk,package.pk,package.pdf_sha256])
        if not fields.get('reviewer'):raise RuleError('请选择本店独立医务审核人。')
        reviewer=ClinicalReviewerAppointment.objects.get(pk=fields['reviewer'],clinic=row.clinic)
        # Check the same selected sources without exposing their clinical contents to front desk.
        candidate_sources=[s[1] for s in sources]
        if not reviewer.can_review_copies or not reviewer.is_active or not reviewer.valid_from<=timezone.now()<reviewer.valid_until:raise RuleError('所选医务审核职责无效。')
        if reviewer.user_id in (row.recipient_id,actor.pk,row.created_by_id) or row.items.filter(visit__dentist_id=reviewer.user.dentist_id).exists():raise RuleError('请选择独立于申请、材料受理及原负责医师的审核人。')
        for pkg in ArchivePackage.objects.filter(pk__in=candidate_sources).select_related('archive__encounter__visit'):
            for service in required_services(pkg.archive.encounter.visit,pkg.manifest['source_snapshot']):professional_scope(reviewer.user_id,row.clinic_id,service,'READ')
        return dict(decision=decision,basis=fields['basis'],identity_reference=text(fields['identity_reference'],'身份材料编号',160),
            authority_reference=text(fields['authority_reference'],'复制授权原件编号',160) if row.kind!='SELF' else '',
            identity=identity(row),sources=sources,reviewer=reviewer.pk,reviewer_revision=reviewer.revision,pickup_until=until.isoformat())
    if action=='REVIEW':
        if row.state!='REVIEW' or row.assigned_reviewer.user_id!=actor.pk:raise PermissionDenied('请由本申请指定的独立医务审核人办理。')
        if fields['decision']=='APPROVE' and identity(row)!=row.identity_snapshot:raise RuleError('身份资料发生变化，请退回材料核验。')
        if fields['decision'] not in ('APPROVE','RETURN','REJECT'):raise RuleError('请选择明确的审核结论。')
        return dict(decision=fields['decision'],message=text(fields['message'],'申请人可见审核说明',500),sources=source_stamp(row))
    if action=='RESUBMIT':
        if row.state!='NEED_INFO':raise RuleError('请从待补充申请继续。')
        return dict(message=text(fields['message'],'补充材料办理说明',500))
    if action in ('WITHDRAW','REVOKE'):
        if row.state not in OPEN:raise RuleError('原申请已结束，原记录保留。')
        return dict(message=text(fields['message'],'办理原因',500))
    if action=='RETRY':
        if row.state!='FAILED' or not review_valid(row):raise RuleError('请在审核仍有效的生成失败事项上重试。')
        return {}
    if action=='CLAIM':return dict(file=row.file.pk,sha256=row.file.sha256)
    raise RuleError('未知副本办理动作。')


@sensitive_variables()
def prepare(*,actor,action,fields=None,request_id=None):
    fields=fields or {};b=binding(actor)
    if action in ('SUBMIT','REGISTER'):data=_create_data(actor,fields,action=='REGISTER');revision=None
    else:
        row=RecordCopyRequest.objects.select_related('patient','clinic','assigned_reviewer').get(pk=request_id)
        data=_validate(actor,row,action,fields);revision=row.revision
    payload=dict(binding=b,operation=str(uuid.uuid4()),action=action,request=request_id,revision=revision,data=data)
    patient=Patient.objects.get(pk=data['patient']) if action in ('SUBMIT','REGISTER') else row.patient
    if action in ('SUBMIT','REGISTER'):
        from registry.models import Clinic
        clinic=Clinic.objects.get(pk=data['clinic']);purpose=data['purpose'];name=data['recipient_name'];recipient_id=data['recipient']
        scope=data['sources']
    else:
        clinic=row.clinic;purpose=row.purpose;name=row.recipient_name;recipient_id=row.recipient_id
        scope=[dict(visit=i.visit_id,package=i.package_id,sections=i.sections) for i in items(row)]
        if action=='VERIFY' and data.get('sources'):
            selected={entry[0]:entry[1] for entry in data['sources']}
            for source,item in zip(scope,items(row)):source['package']=selected[item.pk]
    labels={'SUBMIT':'提交本人申请','REGISTER':'登记本用途代理申请','VERIFY':'核对身份与用途','REVIEW':'独立医务审核',
        'RESUBMIT':'补充后再次提交','WITHDRAW':'撤回本申请','REVOKE':'撤销新领取','RETRY':'重试原生成任务','CLAIM':'确认领取电子副本'}
    summary=[dict(label='本次办理',value=labels[action]),dict(label='患者',value=patient.name+' · '+patient.patient_no),
        dict(label='门店',value=clinic.public_contact['name']),dict(label='实际领取人',value=name),
        dict(label='指定领取账号',value=UserAccount.objects.get(pk=recipient_id).username),dict(label='用途',value=purpose)]
    for source in scope:
        visit=Visit.objects.get(pk=source['visit']);pkg=ArchivePackage.objects.get(pk=source['package']) if source['package'] else None
        summary.append(dict(label=visit.visit_no,value=('固定第'+str(pkg.number)+'包' if pkg else '固定材料尚未就绪，申请保留')+' · '+'、'.join(SECTIONS[k] for k in source['sections'])))
    for key,title in [('message','本次办理说明'),('identity_reference','身份材料编号'),('authority_reference','本用途代理原件编号'),('pickup_until','领取期限')]:
        if data.get(key):summary.append(dict(label=title,value=data[key]))
    if 'decision' in data:summary.append(dict(label='办理结论',value={'VERIFY':'材料核验通过','APPROVE':'批准准确范围','RETURN':'退回补充','REJECT':'不通过'}[data['decision']]))
    return dict(proposal_token=signing.dumps(payload,salt=CONTRACT,compress=True),action=action,summary=summary)


@business_errors
@transaction.atomic
@sensitive_variables()
def confirm(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对申请人、用途、材料范围及本次办理后果并明确确认。')
    try:p=signing.loads(proposal_token,salt=CONTRACT,max_age=900)
    except (signing.BadSignature,TypeError):raise RuleError('办理预览已过期，请重新核对。') from None
    if p['binding']!=binding(actor):raise RuleError('当前账号、就诊人或工作范围已变化，请重新预览。')
    peek=RecordCopyRequest.objects.get(pk=p['request']) if p['request'] else None
    ids=sorted({actor.pk,p['data'].get('recipient',actor.pk),*([] if not peek else [peek.recipient_id,peek.reviewed_by_id or actor.pk])})
    list(UserAccount.objects.select_for_update().filter(pk__in=ids).order_by('pk'));require_copy_write(actor)
    old=RecordCopyEvent.objects.select_related('request').filter(operation_id=p['operation']).first()
    if old:
        if old.actor_id!=actor.pk or old.action!=p['action']:raise PermissionDenied
        return old.request,True
    action=p['action'];d=p['data']
    if action in ('SUBMIT','REGISTER'):
        if action=='SUBMIT':
            access=patient_access(actor,self_only=True,lock=True)
            if access.patient_id!=d['patient'] or d['recipient']!=actor.pk:raise PermissionDenied
        else:front(actor,d['clinic'],lock=True)
        visits=list(Visit.objects.filter(pk__in=[s['visit'] for s in d['sources']],patient_id=d['patient'],clinic_id=d['clinic'],status__in=['COMPLETED','CLOSED_NO_TREATMENT']))
        if len(visits)!=len(d['sources']):raise RuleError('就诊资料发生变化，请重新核对范围。')
        if RecordCopyRequest.objects.filter(patient_id=d['patient'],clinic_id=d['clinic'],recipient_id=d['recipient'],state__in=['PENDING','NEED_INFO','REVIEW','APPROVED','FAILED']).exists():raise RuleError('已有办理中的同店申请，请从原申请继续。')
        row=RecordCopyRequest.objects.create(patient_id=d['patient'],clinic_id=d['clinic'],recipient_id=d['recipient'],created_by=actor,
            kind=d['kind'],purpose=d['purpose'],recipient_name=d['recipient_name'])
        for source in d['sources']:RecordCopyItem.objects.create(request=row,visit_id=source['visit'],package_id=source['package'],sections=source['sections'])
    else:
        row=RecordCopyRequest.objects.select_for_update(of=('self',)).select_related('patient','clinic','assigned_reviewer').get(pk=p['request'])
        if row.revision!=p['revision']:raise RuleError('申请状态或依据已变化，请打开最新记录继续。')
        if action=='VERIFY':
            replay_fields=dict(d,pickup_until=timezone.datetime.fromisoformat(d['pickup_until']) if d.get('pickup_until') else None,purpose_checked=True)
        else:replay_fields=d
        current=_validate(actor,row,action,replay_fields)
        if action=='VERIFY' and current!=d:raise RuleError('身份、固定版本或审核职责已变化，请重新核验。')
        if action=='REVIEW' and current!=d:raise RuleError('固定清单已变化，请重新核对。')
        if action=='VERIFY':
            if d['decision']=='VERIFY':
                for pk,package,sha in d['sources']:RecordCopyItem.objects.filter(pk=pk,request=row,package__isnull=True).update(package_id=package)
                row.state='REVIEW';row.verified_by=actor;row.verified_at=timezone.now();row.verification=d
                row.identity_snapshot=d['identity'];row.assigned_reviewer_id=d['reviewer'];row.pickup_until=timezone.datetime.fromisoformat(d['pickup_until']);row.patient_message='身份与本用途材料已核对，等待独立医务审核。'
            else:row.state='NEED_INFO' if d['decision']=='RETURN' else 'REJECTED';row.patient_message=d['message']
        elif action=='REVIEW':
            row.patient_message=d['message']
            if d['decision']=='APPROVE':
                appointed,scopes=review_authority(actor,row,lock=True)
                row.state='APPROVED';row.reviewed_by=actor;row.reviewed_at=timezone.now()
                row.approval=dict(reviewer=appointed.pk,revision=appointed.revision,scopes=[list(s) for s in scopes],sources=d['sources'])
            else:row.state='NEED_INFO' if d['decision']=='RETURN' else 'REJECTED'
        elif action=='RESUBMIT':row.state='PENDING';row.patient_message='已补充办理说明，等待材料重新核验。'
        elif action in ('WITHDRAW','REVOKE'):row.state='WITHDRAWN' if action=='WITHDRAW' else 'REVOKED';row.patient_message=d['message']
        elif action=='RETRY':row.state='APPROVED';row.generation_error=''
        elif action=='CLAIM':
            record(actor,row,action,p['operation'],d);return row,False
        row.revision+=1;row.save()
    record(actor,row,action,p['operation'],d);return row,False


def pickup_token(actor,row,proposal_token):
    p=signing.loads(proposal_token,salt=CONTRACT,max_age=900)
    recipient(row,actor,pickup=True)
    event=RecordCopyEvent.objects.get(request=row,actor=actor,operation_id=p['operation'],action='CLAIM')
    return signing.dumps(dict(binding=binding(actor),request=row.pk,revision=row.revision,claim=str(event.operation_id),sha256=row.file.sha256),salt=PICKUP)


@business_errors
@transaction.atomic
def pickup(*,actor,token):
    try:p=signing.loads(token,salt=PICKUP,max_age=120)
    except (signing.BadSignature,TypeError):raise RuleError('领取凭据已过期，请在原申请重新确认领取。') from None
    if p['binding']!=binding(actor):raise PermissionDenied('领取账号或就诊人已变化。')
    peek=RecordCopyRequest.objects.get(pk=p['request'])
    list(UserAccount.objects.select_for_update().filter(pk__in=sorted({actor.pk,peek.reviewed_by_id})).order_by('pk'))
    require_copy_write(actor)
    row=RecordCopyRequest.objects.select_for_update(of=('self',)).select_related('patient','clinic').get(pk=peek.pk)
    recipient(row,actor,pickup=True)
    if row.revision!=p['revision'] or row.file.sha256!=p['sha256']:raise RuleError('领取依据已变化，请重新核对申请。')
    RecordCopyEvent.objects.get(request=row,actor=actor,operation_id=p['claim'],action='CLAIM')
    data=bytes(row.file.pdf)
    if hashlib.sha256(data).hexdigest()!=row.file.sha256:raise RuleError('固定文件校验异常，请联系门店核对，不返回不完整文件。')
    op=uuid.uuid5(uuid.UUID(p['claim']),'server-file-response')
    if not RecordCopyEvent.objects.filter(operation_id=op).exists():
        row.state='DELIVERED';row.save(update_fields=['state'])
        record(actor,row,'FILE_RESPONSE',op,dict(file=row.file.pk,sha256=row.file.sha256,delivery='SERVER_RESPONSE_PREPARED_NOT_READ_PROOF'))
    return row,data
