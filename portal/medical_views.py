from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import read_proposal
from clinical.encounter_views import clinical_render
from clinical.models import ClinicalReviewerAppointment
from clinical.plan_forms import ConfirmPlanActionForm
from portal import medical_proxies as svc
from portal.medical_forms import ProxyMaterialsForm,ProxyActionForm
from portal.medical_models import MedicalProxy
from portal.medical_projection import case_data
from portal.medical_authority import latest_version
from workspaces.context import require_active


@login_required
@never_cache
@require_http_methods(['GET'])
def listing(request):
    require_active(request.user,('FRONT_DESK','DENTIST'))
    if request.workspace.role=='FRONT_DESK':qs=MedicalProxy.objects.filter(clinic_id=svc.front(request.user))
    else:
        now=timezone.now();clinics=ClinicalReviewerAppointment.objects.filter(user=request.user,is_active=True,valid_from__lte=now,valid_until__gt=now).values('clinic_id')
        qs=MedicalProxy.objects.filter(Q(versions__plan__origin_encounter__visit__dentist_id=request.user.dentist_id)|Q(clinic_id__in=clinics)).distinct()
    page=Paginator(qs.select_related('patient','clinic','delegate').order_by('state','pk'),20).get_page(request.GET.get('page'))
    rows=[]
    for case in page:
        try:rows.append(case_data(request.user,case))
        except PermissionDenied:continue
    return clinical_render(request,'portal/medical_queue.html',dict(rows=rows,page=page,front=request.workspace.role=='FRONT_DESK'))


def confirmation(request,*,case_id,back,base='base.html'):
    form=ConfirmPlanActionForm(request.POST)
    if form.is_valid():
        try:
            d=read_proposal(request.user,svc.CONTRACT,svc.ROLES,form.cleaned_data['proposal_token'])['data']
            if d['case']!=case_id:raise PermissionDenied('请从原医疗授权办理页确认。')
            case,replay=svc.confirm(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:messages.success(request,'医疗授权办理记录已保留。');return redirect('medical_proxy_detail' if base=='base.html' else 'portal_medical_proxy',pk=case.pk)
    return clinical_render(request,'portal/medical_confirm.html',dict(form=form,back=back,base_template=base),status=409)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def create(request):
    svc.front(request.user);back=reverse('medical_proxies')
    if request.method=='POST' and request.POST.get('phase')=='confirm':return confirmation(request,case_id=None,back=back)
    form=ProxyMaterialsForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:p=svc.prepare_submit(actor=request.user,fields=form.values())
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return clinical_render(request,'portal/medical_confirm.html',dict(form=ConfirmPlanActionForm(initial=p),preview=read_proposal(request.user,svc.CONTRACT,svc.ROLES,p['proposal_token'])['data'],back=back,base_template='base.html'))
    return clinical_render(request,'portal/medical_materials.html',dict(form=form,back=back))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def detail(request,pk,patient_view=False):
    if patient_view:
        from portal.account_access import account_context
        account_context(request)
    case=get_object_or_404(MedicalProxy,pk=pk);data=case_data(request.user,case,account=patient_view);base='portal/base.html' if patient_view else 'base.html'
    if not patient_view:require_active(request.user,('FRONT_DESK','DENTIST'))
    elif request.method=='POST':require_active(request.user,('PATIENT',))
    back=reverse('portal_medical_proxy' if patient_view else 'medical_proxy_detail',kwargs={'pk':pk})
    if request.method=='POST' and request.POST.get('phase')=='confirm':return confirmation(request,case_id=pk,back=back,base=base)
    edit=request.GET.get('edit')=='1' and data['can_edit']
    if edit:
        v=latest_version(case)
        initial=dict(patient_no=case.patient.patient_no,username=case.delegate.username,delegate_name=v.delegate_name,kind=case.kind,plan=v.plan_id,
            steps=','.join(str(x) for x in data['steps']),identity_reference=v.identity_reference,authority_reference=v.authority_reference,applicability=v.applicability,
            valid_from=timezone.localtime(v.valid_from),valid_until=timezone.localtime(v.valid_until))
        form=ProxyMaterialsForm(request.POST or None,initial=initial)
    else:form=ProxyActionForm(request.POST or None,role=request.workspace.role,state=case.state) if not data.get('status_only') else None
    if request.method=='POST' and form and form.is_valid():
        try:p=svc.prepare_submit(actor=request.user,case_id=pk,fields=form.values()) if edit else svc.prepare_action(actor=request.user,case_id=pk,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return clinical_render(request,'portal/medical_confirm.html',dict(form=ConfirmPlanActionForm(initial=p),preview=read_proposal(request.user,svc.CONTRACT,svc.ROLES,p['proposal_token'])['data'],back=back,base_template=base))
    return clinical_render(request,'portal/medical_materials.html' if edit else 'portal/medical_detail.html',dict(form=form,back=back,medical=data,base_template=base))


@login_required
@never_cache
@require_http_methods(['GET'])
def patient_listing(request):
    from portal.models import PatientAccess
    from portal.account_access import account_context
    account_context(request)
    own=PatientAccess.objects.filter(user=request.user,is_active=True).values('patient_id')
    cases=MedicalProxy.objects.filter(Q(delegate=request.user)|Q(patient_id__in=own)).select_related('patient','clinic','delegate').order_by('-pk')[:50]
    return clinical_render(request,'portal/medical_patient_list.html',dict(rows=[case_data(request.user,c,account=True) for c in cases]))
