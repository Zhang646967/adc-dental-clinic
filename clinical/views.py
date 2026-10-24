from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_POST,require_http_methods
from django.utils import timezone
from adc_core.proposals import workspace_binding
from adc_core.http_support import EXPECTED_ERRORS,add_error
from clinical import authority_services as svc,referrals
from clinical.authority import require_reviewer,require_visit_authority
from clinical.models import ProfessionalAuthorization,ClinicalAuthorityPolicy,ClinicalReviewerAppointment
from clinical.forms import ProfessionalCaseForm,DecisionForm,ConfirmForm,ActivationForm,ReferralForm,IdentityForm
from scheduling.models import Visit

AUTH_LABELS={'APPROVE':'批准专业范围','REJECT':'不予批准','SUSPEND':'暂停操作范围','RESUME':'重新批准范围','REVOKE':'撤销操作范围'}
REF_LABELS={'IDENTITY_CONFIRM':'核对现有患者身份','IDENTITY_DISPUTE':'登记身份待澄清','ACCEPT':'接收限定转诊','DECLINE':'不接收转诊','WITHDRAW':'撤回转诊','REVOKE':'终止转诊查阅'}


def authority_cases(actor):
    ctx=workspace_binding(actor,('MANAGER','DENTIST'))
    rows=ProfessionalAuthorization.objects.select_related('user__dentist','clinic','service','created_by')
    if ctx['role']=='MANAGER':return rows.filter(clinic_id=ctx['clinic'])
    now=timezone.now()
    clinics=ClinicalReviewerAppointment.objects.filter(user=actor,is_active=True,valid_from__lte=now,valid_until__gt=now).values('clinic_id')
    return rows.filter(Q(user=actor)|Q(clinic_id__in=clinics))


def preview(request,title,token,values,*,mode):
    return render(request,'clinical/confirm.html',dict(title=title,values=values,
        form=ConfirmForm(initial={'proposal_token':token}),mode=mode))


@login_required
@never_cache
@require_GET
def authority_home(request):
    rows=authority_cases(request.user).order_by('clinic_id','user_id','-created_at')
    return render(request,'clinical/authority_list.html',{'page':Paginator(rows,30).get_page(request.GET.get('page')),
        'is_manager':workspace_binding(request.user,('MANAGER','DENTIST'))['role']=='MANAGER'})


@login_required
@never_cache
@require_GET
def authority_detail(request,pk):
    row=get_object_or_404(authority_cases(request.user),pk=pk)
    actions=[]
    try:require_reviewer(request.user,row.clinic_id)
    except PermissionDenied:pass
    else:
        if request.user.pk not in (row.user_id,row.created_by_id):
            actions={'PENDING':['APPROVE','REJECT'],'APPROVED':['SUSPEND','REVOKE'],'SUSPENDED':['RESUME','REVOKE']}.get(row.state,[])
    events=list(row.events.select_related('actor').order_by('pk'))
    for event in events:
        event.action_label={'PROPOSE':'整理申请',**AUTH_LABELS}.get(event.action,event.action)
        event.state_label=dict(ProfessionalAuthorization.STATES).get(event.resulting_state,event.resulting_state)
    return render(request,'clinical/authority_detail.html',{'case':row,
        'actions':[(a,AUTH_LABELS[a]) for a in actions],'events':events})


@sensitive_post_parameters()
@login_required
@never_cache
@require_http_methods(['GET','POST'])
def authority_new(request):
    ctx=workspace_binding(request.user,('MANAGER',))
    form=ProfessionalCaseForm(request.POST or None,clinic_id=ctx['clinic'])
    if request.method=='POST' and form.is_valid():
        try:p=svc.prepare_authority(actor=request.user,action='PROPOSE',fields=form.fields_data())
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,'核对专业授权申请',p['proposal_token'],[(f.label,form.cleaned_data.get(n)) for n,f in form.fields.items()],mode='authority')
    return render(request,'clinical/form.html',{'title':'整理专业授权申请','form':form,
        'description':'以本店已核验的资质来源申请限定操作范围，提交后由另一名受委任医师审核。'})


@sensitive_post_parameters()
@login_required
@never_cache
@require_http_methods(['GET','POST'])
def authority_action(request,pk,action):
    row=get_object_or_404(authority_cases(request.user),pk=pk)
    if action not in AUTH_LABELS:raise PermissionDenied
    require_reviewer(request.user,row.clinic_id);svc.check_decision(request.user,row,action)
    form=DecisionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:p=svc.prepare_authority(actor=request.user,action=action,case_id=pk,fields=form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,AUTH_LABELS[action],p['proposal_token'],[('医师',row.user.username),('诊所',row.clinic.name),('服务',row.service.name if row.service_id else '无服务旧记录'),('办理依据',form.cleaned_data['note'])],mode='authority')
    return render(request,'clinical/form.html',{'title':AUTH_LABELS[action],'form':form,
        'description':'审核人与申请对象、申请整理人必须为不同账号。暂停或撤销保留历史，已有预约需另行交接。'})


@sensitive_post_parameters()
@login_required
@never_cache
@require_http_methods(['GET','POST'])
def authority_activate(request):
    workspace_binding(request.user,('DENTIST',))
    form=ActivationForm(request.POST or None,actor=request.user)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:p=svc.prepare_authority(actor=request.user,action='ACTIVATE',fields={'clinic_id':d['clinic'].pk,'note':d['note']})
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,'核对本店专业范围控制启用',p['proposal_token'],[('诊所',d['clinic'].name),('依据',d['note'])],mode='authority')
    return render(request,'clinical/form.html',{'title':'启用本店专业范围控制','form':form,
        'description':'由本店受委任的专业审核人员核对。启用后临床操作持续检查专业范围及期限，启用事实保留。'})


@sensitive_post_parameters()
@login_required
@require_POST
def authority_confirm(request):
    form=ConfirmForm(request.POST)
    if form.is_valid():
        try:row,replay=svc.confirm_authority(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'已保存专业范围办理结果。' if not replay else '此前已保存本次决定，以下为当前结果。')
            return redirect('clinical_authority_detail',pk=row.pk) if isinstance(row,ProfessionalAuthorization) else redirect('clinical_authority_home')
    return render(request,'clinical/confirm.html',{'title':'请重新核对专业范围','form':form,'mode':'authority'},status=409)


def referral_projection(actor,row):
    ctx=workspace_binding(actor,referrals.ROLES)
    return dict(id=row.pk,patient_no=row.patient.patient_no,
        patient_name=row.patient.name if ctx['role']!='MANAGER' else '',
        dob=row.patient.date_of_birth if ctx['role']=='FRONT_DESK' else None,
        source=row.source_clinic.name,destination=row.destination_clinic.name,receiver=row.receiver.username,
        state=row.get_state_display(),valid_until=row.valid_until,revision=row.revision,
        purpose=row.purpose if ctx['role']=='DENTIST' and row.created_by_id==actor.pk else '',
        consent_basis=row.get_consent_basis_display() if ctx['role']!='MANAGER' else '',
        source_visit_id=row.source_visit_id if ctx['role']=='DENTIST' and row.created_by_id==actor.pk else None)


@login_required
@never_cache
@require_GET
def referral_home(request):
    page=Paginator(referrals.visible_referrals(request.user).order_by('-created_at'),25).get_page(request.GET.get('page'))
    return render(request,'clinical/referral_list.html',{'page':page,'rows':[referral_projection(request.user,r) for r in page]})


@login_required
@never_cache
@require_GET
def referral_detail(request,pk):
    row=get_object_or_404(referrals.visible_referrals(request.user),pk=pk)
    actions=[]
    for action in REF_LABELS:
        try:referrals.check_action(request.user,row,action)
        except (PermissionDenied,*EXPECTED_ERRORS):continue
        actions.append((action,REF_LABELS[action]))
    can_read=False
    if request.user.pk==row.receiver_id:
        try:referrals.require_referral_read(request.user,row)
        except PermissionDenied:pass
        else:can_read=True
    # Managers/front desk see state/actor/time only; no clinical purpose or raw history note.
    events=list(row.events.select_related('actor').order_by('pk').values('created_at','actor__username','action','resulting_state'))
    for event in events:
        event['action_label']={'CREATE':'原医师发起',**REF_LABELS}.get(event['action'],event['action'])
        event['state_label']=dict(referrals.ClinicalReferral.STATES)[event['resulting_state']]
    return render(request,'clinical/referral_detail.html',{'case':referral_projection(request.user,row),
        'actions':actions,'can_read':can_read,'events':events})


@sensitive_post_parameters()
@login_required
@never_cache
@require_http_methods(['GET','POST'])
def referral_new(request,pk):
    visit=get_object_or_404(Visit.objects.select_related('patient','clinic'),pk=pk)
    require_visit_authority(request.user,visit,'REFER',always=True)
    form=ReferralForm(request.POST or None,visit=visit)
    if request.method=='POST' and form.is_valid():
        try:p=referrals.prepare_referral(actor=request.user,action='CREATE',fields=form.fields_data())
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            from django.forms import ModelChoiceField,ChoiceField
            from datetime import datetime
            from django.utils import timezone
            values=[]
            for name,field in form.fields.items():
                value=form.cleaned_data.get(name)
                if value is not None and isinstance(field,ModelChoiceField):value=field.label_from_instance(value)
                elif isinstance(field,ChoiceField):value=dict(field.choices).get(value,value)
                elif isinstance(value,datetime):value=timezone.localtime(value).strftime('%Y-%m-%d %H:%M')+'（北京时间）'
                values.append((field.label,value))
            return preview(request,'核对限定跨店转诊',p['proposal_token'],values,mode='referral')
    return render(request,'clinical/form.html',{'title':'发起限定跨店转诊','form':form,
        'description':f'{visit.patient.patient_no} · {visit.clinic.name}。明确接收人、期限、披露依据和具体记录；预约授权不能代替临床同意。'})


@sensitive_post_parameters()
@login_required
@never_cache
@require_http_methods(['GET','POST'])
def referral_action(request,pk,action):
    row=get_object_or_404(referrals.visible_referrals(request.user),pk=pk)
    if action not in REF_LABELS:raise PermissionDenied
    referrals.check_action(request.user,row,action)
    form=(IdentityForm if action=='IDENTITY_CONFIRM' else DecisionForm)(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:p=referrals.prepare_referral(actor=request.user,action=action,referral_id=pk,fields=form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,REF_LABELS[action],p['proposal_token'],[('患者编号',row.patient.patient_no),('接收店',row.destination_clinic.name),('办理依据',form.cleaned_data['note'])],mode='referral')
    return render(request,'clinical/form.html',{'title':REF_LABELS[action],'form':form,
        'description':'同名、联系电话或亲属代约均不能自动授权披露。身份有疑问时先登记待澄清。'})


@sensitive_post_parameters()
@login_required
@require_POST
def referral_confirm(request):
    form=ConfirmForm(request.POST)
    if form.is_valid():
        try:row,replay=referrals.confirm_referral(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'转诊办理结果已保存。' if not replay else '本次已办理，以下为当前结果。')
            return redirect('clinical_referral_detail',pk=row.pk)
    return render(request,'clinical/confirm.html',{'title':'转诊需要重新核对','form':form,'mode':'referral'},status=409)


@login_required
@never_cache
@require_GET
def referral_record(request,pk):
    row=get_object_or_404(referrals.visible_referrals(request.user),pk=pk)
    content=referrals.released_record(request.user,row)
    return render(request,'clinical/referral_record.html',{'case':referral_projection(request.user,row),'content':content})
