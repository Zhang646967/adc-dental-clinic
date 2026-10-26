from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404,HttpResponse,JsonResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_GET,require_POST,require_http_methods
from django.views.decorators.cache import never_cache
from django import forms
from datetime import datetime,time,timedelta
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import workspace_binding
from registry.profile_models import PublicProfile,ProfileVersion,ProfileMedia,DentistClinicAffiliation,ProfileAction
from registry.profile_forms import DentistProfileForm,ClinicProfileForm,AffiliationForm,ProfileConfirmForm,MediaForm
from registry import profile_services as commands
from registry.models import Dentist


def staff_role(actor):return workspace_binding(actor,('DENTIST','MANAGER'))['role']


@login_required
@never_cache
@require_GET
def home(request):
    role=staff_role(request.user);kind='dentist' if role=='DENTIST' else 'clinic'
    lookup=commands.owner(request.user,kind)
    profile=PublicProfile.objects.filter(**lookup).select_related('submitted_version','published_version').first()
    qs=DentistClinicAffiliation.objects.select_related('dentist','clinic','published_version')
    qs=qs.filter(dentist_id=request.user.dentist_id) if role=='DENTIST' else qs.filter(clinic_id=lookup['clinic_id'])
    affiliations=list(qs)
    pending={p.dentist_id:p.submitted_version for p in PublicProfile.objects.filter(
        dentist_id__in=[a.dentist_id for a in affiliations]).select_related('submitted_version')}
    from scheduling.models import Visit,AvailabilitySlot
    from coordination.models import WaitOffer
    from django.utils import timezone
    rows=[]
    for a in affiliations:
        rows.append(dict(affiliation=a,pending=pending.get(a.dentist_id),
            commitments=Visit.objects.filter(clinic_id=a.clinic_id,dentist_id=a.dentist_id,
                status__in=['SCHEDULED','CHECKED_IN'],scheduled_end__gt=timezone.now()).count(),
            holds=WaitOffer.objects.filter(request__clinic_id=a.clinic_id,slot__dentist_id=a.dentist_id,
                state='PENDING',expires_at__gt=timezone.now()).count()))
    history=ProfileAction.objects.filter(profile=profile) if role=='DENTIST' else ProfileAction.objects.filter(clinic_id=lookup['clinic_id'])
    return render(request,'registry/profile_home.html',dict(kind=kind,profile=profile,rows=rows,
        history=history.select_related('actor').order_by('-pk')[:30],is_manager=role=='MANAGER'))


def preview_response(request,preview,confirm_route):
    labels={'kind':'资料类型','action':'办理动作','clinic':'门店','dentist':'医师','kind_label':'接诊类型',
        'starts_on':'开始日期','ends_on':'结束日期','note':'审核意见','version':'提交版本'}
    actions={'SAVE':'保存草稿','SUBMIT':'提交审核','PUBLISH':'发布介绍','RETURN':'退回修改','WITHDRAW':'撤回介绍',
        'UPSERT':'登记／调整任职','END':'结束任职并协调原承诺','ACTIVATE':'启用统一任职控制'}
    content=preview['data'].get('content',{})
    source_form=DentistProfileForm() if preview['data'].get('kind')=='dentist' else ClinicProfileForm()
    items=[]
    for k,value in content.items():
        if k not in source_form.fields or k=='media_ids':continue
        field=source_form.fields[k]
        if isinstance(field,forms.MultipleChoiceField):value='、'.join(dict(field.choices).get(v,v) for v in value)
        elif isinstance(field,forms.ChoiceField):value=dict(field.choices).get(value,value)
        items.append((field.label,value))
    if content:items.append(('已选图片',str(len(content.get('media_ids',[])))+'张'))
    if not items:
        for k,label in labels.items():
            if k in preview['data']:
                value=preview['data'][k]
                items.append((label,actions.get(value,value) if k=='action' else value))
    preview['display_items']=items
    return render(request,'registry/profile_confirm.html',{'preview':preview,'confirm_route':confirm_route,
        'form':ProfileConfirmForm(initial={'proposal_token':preview['proposal_token']})})


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def edit(request,kind):
    lookup=commands.owner(request.user,kind)
    profile=PublicProfile.objects.filter(**lookup).first()
    initial=dict(profile.draft) if profile else {}
    initial['media_ids']=','.join(map(str,initial.get('media_ids',[])))
    form=(DentistProfileForm if kind=='dentist' else ClinicProfileForm)(request.POST or None,initial=initial)
    media_form=MediaForm()
    if request.method=='POST' and form.is_valid():
        try:
            if request.POST.get('action')=='SAVE_DRAFT':
                row,replay=commands.save_draft(actor=request.user,token=request.POST.get('draft_token',''),fields=request.POST)
                if request.headers.get('Accept')=='application/json':
                    return JsonResponse({'ok':True,'revision':row.revision,'replay':replay,'draft_token':commands.draft_token(request.user,kind)})
                messages.success(request,'草稿已保存，公开版本保持。')
                return redirect('profile_edit',kind=kind)
            prepared=commands.prepare_profile(actor=request.user,kind=kind,action=request.POST.get('action','SAVE'),fields=request.POST)
            return preview_response(request,prepared,'profile_confirm')
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_edit.html',dict(form=form,kind=kind,profile=profile,media_form=media_form,
        draft_token=commands.draft_token(request.user,kind),
        images=profile.images.defer('image').order_by('-pk')[:15] if profile else []))


@login_required
@require_POST
def upload(request,kind):
    form=MediaForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            media=commands.upload_media(actor=request.user,kind=kind,uploaded=form.cleaned_data['image'],alt_text=form.cleaned_data['alt_text'])
            messages.success(request,'图片已保存。请在资料表单中勾选后提交，当前公开版本保持。')
            return redirect('profile_edit',kind=kind)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_upload_error.html',{'form':form,'kind':kind},status=400)


@login_required
@require_POST
def transition(request,kind,action):
    form=ProfileConfirmForm()
    try:return preview_response(request,commands.prepare_profile(actor=request.user,kind=kind,action=action),'profile_confirm')
    except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_confirm.html',{'form':form},status=409)


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def affiliation(request):
    from equipment.policies import manager_clinic
    manager_clinic(request.user)
    form=AffiliationForm(request.POST or None)
    form.fields['dentist_id']=forms.ModelChoiceField(label='医师',queryset=Dentist.objects.filter(is_active=True))
    if request.method=='POST' and form.is_valid():
        try:
            data=request.POST.copy();data['dentist_id']=form.cleaned_data['dentist_id'].pk
            return preview_response(request,commands.prepare_affiliation(actor=request.user,action='UPSERT',fields=data),'profile_affiliation_confirm')
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_simple_form.html',{'form':form,'title':'登记／调整本店医师接诊安排'})


@login_required
@require_POST
def roster_transition(request,pk,action):
    form=ProfileConfirmForm()
    try:return preview_response(request,commands.prepare_affiliation(actor=request.user,action=action,affiliation_id=pk or None),'profile_affiliation_confirm')
    except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_confirm.html',{'form':form},status=409)


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def review(request,pk):
    from equipment.policies import manager_clinic
    clinic=manager_clinic(request.user)
    a=get_object_or_404(DentistClinicAffiliation,pk=pk,clinic_id=clinic)
    profile=PublicProfile.objects.filter(dentist_id=a.dentist_id).select_related('submitted_version').first()
    versions=ProfileVersion.objects.filter(profile=profile).order_by('-sequence')
    class ReviewForm(forms.Form):
        version_id=forms.ModelChoiceField(label='医师提交版本',queryset=versions)
        action=forms.ChoiceField(label='审核决定',choices=[('PUBLISH','发布本店介绍'),('RETURN','退回修改'),('WITHDRAW','撤回公开介绍')])
        note=forms.CharField(label='审核意见',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    form=ReviewForm(request.POST or None,initial={'version_id':profile.submitted_version_id if profile else None})
    if request.method=='POST' and form.is_valid():
        try:return preview_response(request,commands.prepare_review(actor=request.user,affiliation_id=pk,
            action=form.cleaned_data['action'],version_id=form.cleaned_data['version_id'].pk,note=form.cleaned_data['note']),'profile_review_confirm')
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_review.html',dict(form=form,affiliation=a,versions=versions))


def _confirm(request,command):
    form=ProfileConfirmForm(request.POST)
    if form.is_valid():
        try:
            _,replay=command(actor=request.user,**form.cleaned_data)
            messages.success(request,'已返回原办理结果。' if replay else '办理完成。')
            return redirect('profile_home')
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'registry/profile_confirm.html',{'form':form},status=409)


@login_required
@require_POST
def confirm(request):return _confirm(request,commands.confirm_profile)

@login_required
@require_POST
def affiliation_confirm(request):return _confirm(request,commands.confirm_affiliation)

@login_required
@require_POST
def review_confirm(request):return _confirm(request,commands.confirm_review)


@login_required
@never_cache
@require_GET
def coordination(request):
    from adc_core.proposals import workspace_binding
    from scheduling.models import Visit,AvailabilitySlot
    from coordination.models import WaitOffer
    from django.utils import timezone
    binding=workspace_binding(request.user,('FRONT_DESK','MANAGER'));clinic=binding['clinic']
    now=timezone.now();rows=[]
    for a in DentistClinicAffiliation.objects.filter(clinic_id=clinic).select_related('dentist'):
        if a.state=='ACTIVE' and a.ends_on is None:continue
        visits=Visit.objects.filter(clinic_id=clinic,dentist_id=a.dentist_id,status__in=['SCHEDULED','CHECKED_IN'],scheduled_end__gt=now)
        holds=WaitOffer.objects.filter(request__clinic_id=clinic,slot__dentist_id=a.dentist_id,state='PENDING',expires_at__gt=now)
        if a.state=='ACTIVE':
            boundary=timezone.make_aware(datetime.combine(a.ends_on+timedelta(days=1),time.min))
            visits=visits.filter(scheduled_end__gt=boundary);holds=holds.filter(ends_at__gt=boundary)
        slots=AvailabilitySlot.objects.filter(clinic_id=clinic,dentist_id=a.dentist_id,is_active=True,ends_at__gt=now)
        if a.state=='ACTIVE':slots=slots.filter(ends_at__gt=boundary)
        if visits.exists() or holds.exists() or slots.exists():rows.append(dict(affiliation=a,
            visits=visits.order_by('scheduled_start')[:50] if binding['role']=='FRONT_DESK' else [],
            visit_count=visits.count(),hold_count=holds.count(),slots=slots.order_by('starts_at')[:30]))
    return render(request,'registry/roster_coordination.html',{'rows':rows,'frontdesk':binding['role']=='FRONT_DESK'})


@require_GET
def media(request,pk):
    from django.db.models import Q
    from django.utils import timezone
    row=get_object_or_404(ProfileMedia.objects.defer('image').select_related('profile'),pk=pk)
    today=timezone.localdate()
    visible=PublicProfile.objects.filter(clinic__is_active=True,clinic__public_directory__is_published=True,
        published_version__content__media_ids__contains=[pk]).exists()
    visible=visible or DentistClinicAffiliation.objects.filter(state='ACTIVE',listing_published=True,
        dentist__is_active=True,clinic__is_active=True,clinic__public_directory__is_published=True,
        starts_on__lte=today,published_version__content__media_ids__contains=[pk]).filter(
            Q(ends_on__isnull=True)|Q(ends_on__gte=today)).exists()
    ctx=getattr(request.user,'_adc_workspace',None)
    if not visible and request.user.is_authenticated and ctx is None:
        from workspaces.context import existing_context,attach
        ctx=existing_context(request)
        if ctx:attach(request,ctx)
    if not visible and request.user.is_authenticated and ctx:
        if ctx.role=='DENTIST' and row.profile.dentist_id==request.user.dentist_id:
            workspace_binding(request.user,('DENTIST',));visible=True
        elif ctx.role=='MANAGER' and (row.profile.clinic_id==ctx.clinic_id or
            DentistClinicAffiliation.objects.filter(clinic_id=ctx.clinic_id,dentist_id=row.profile.dentist_id).exists()):
            workspace_binding(request.user,('MANAGER',));visible=True
    if not visible:raise Http404
    return HttpResponse(bytes(row.image),content_type='image/jpeg',headers={'Cache-Control':'no-store','ETag':'"'+row.digest+'"'})
