import io
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods,require_GET,require_POST
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.http_support import EXPECTED_ERRORS,add_error
from clinical import record_copies as cmd
from clinical.copy_models import RecordCopyRequest
from clinical.copy_forms import CopyApplyForm,CopyVerifyForm,CopyReviewForm,CopyMessageForm,CopyConfirmForm
from clinical.copy_projection import data,packet
from clinical.encounter_views import clinical_render
from portal.account_access import account_context,account_data
from workspaces.context import require_active


def copy_login(view):
    from functools import wraps
    @wraps(view)
    def handle(request,*args,**kw):
        return login_required(login_url='login' if kw.get('staff') else 'portal_login')(view)(request,*args,**kw)
    return handle


def patient_rows(actor):
    from accounts.external_identity import _account_actor
    _account_actor(actor)
    return RecordCopyRequest.objects.filter(recipient=actor).select_related('patient','clinic').order_by('-pk')


def staff_row(actor,pk):
    row=get_object_or_404(RecordCopyRequest.objects.select_related('patient','clinic','assigned_reviewer'),pk=pk)
    if actor._adc_workspace.role=='FRONT_DESK':cmd.front(actor,row.clinic_id)
    else:
        cmd.review_authority(actor,row)
        if row.assigned_reviewer.user_id!=actor.pk:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('本申请由指定独立医务审核人办理。')
    return row


def preview(request,prepared,*,patient):
    return render(request,'clinical/copy_preview.html',dict(copy_base='portal/account_base.html' if patient else 'base.html',prepared=prepared,patient_channel=patient,
        account_token=account_data(request)['account_token'] if patient else '',form=CopyConfirmForm(initial={'proposal_token':prepared['proposal_token']})))


@login_required(login_url='portal_login')
@never_cache
@require_GET
def patient_list(request):
    account_context(request)
    return render(request,'portal/copies.html',dict(page=Paginator(patient_rows(request.user),20).get_page(request.GET.get('page'))))


@login_required
@never_cache
@require_GET
def staff_list(request):
    require_active(request.user,('FRONT_DESK','DENTIST'))
    rows=RecordCopyRequest.objects.select_related('patient','clinic').order_by('-pk')
    if request.user._adc_workspace.role=='FRONT_DESK':rows=rows.filter(clinic_id=cmd.front(request.user).clinic_id)
    else:rows=rows.filter(assigned_reviewer__user=request.user,assigned_reviewer__can_review_copies=True)
    page=Paginator(rows,25).get_page(request.GET.get('page'))
    if request.user._adc_workspace.role=='DENTIST':
        readable=[]
        from django.core.exceptions import PermissionDenied
        from adc_core.rules import RuleError
        for row in page:
            try:cmd.review_authority(request.user,row)
            except (PermissionDenied,RuleError):continue
            readable.append(row)
        page.object_list=readable
    return clinical_render(request,'clinical/copy_list.html',dict(page=page,front=request.user._adc_workspace.role=='FRONT_DESK'))


@copy_login
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def apply(request,staff=False):
    if staff:cmd.front(request.user)
    else:account_context(request,unsafe=request.method=='POST')
    source=request.POST if request.method=='POST' else request.GET
    form=CopyApplyForm(request.POST if request.method=='POST' else None,actor=request.user,clinic_id=source.get('clinic'),staff=staff,patient_no=source.get('patient_no',''))
    if request.method=='POST' and form.is_valid():
        try:p=cmd.prepare(actor=request.user,action='REGISTER' if staff else 'SUBMIT',fields=form.values())
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,p,patient=not staff)
    return render(request,'clinical/copy_apply.html',dict(copy_base='portal/account_base.html' if not staff else 'base.html',form=form,patient_channel=not staff,
        account_token=account_data(request)['account_token'] if not staff else '',front=staff),status=400 if request.method=='POST' else 200)


@copy_login
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def detail(request,pk,staff=False):
    if staff:row=staff_row(request.user,pk)
    else:
        account_context(request,unsafe=request.method=='POST');row=get_object_or_404(patient_rows(request.user),pk=pk);cmd.recipient(row,request.user)
    front=staff and request.user._adc_workspace.role=='FRONT_DESK'
    action=request.POST.get('action','')
    if front:form=CopyVerifyForm(request.POST if action=='VERIFY' else None,row=row)
    elif staff:form=CopyReviewForm(request.POST if action=='REVIEW' else None)
    else:form=None
    message_form=CopyMessageForm(request.POST if action in ('RESUBMIT','WITHDRAW','REVOKE') else None)
    if request.method=='POST':
        chosen=form if action in ('VERIFY','REVIEW') else message_form
        allowed=('VERIFY','REVOKE','RETRY') if front else ('REVIEW',) if staff else ('CLAIM','RESUBMIT','WITHDRAW')
        if action not in allowed:
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('此岗位不能办理所选动作。')
        if action in ('CLAIM','RETRY') or chosen.is_valid():
            try:p=cmd.prepare(actor=request.user,action=action,request_id=row.pk,fields={} if action in ('CLAIM','RETRY') else chosen.values() if hasattr(chosen,'values') else chosen.cleaned_data)
            except EXPECTED_ERRORS as exc:
                if chosen is None:chosen=CopyMessageForm(data={});message_form=chosen
                add_error(chosen,exc)
            else:return preview(request,p,patient=not staff)
    return render(request,'clinical/copy_detail.html',dict(copy_base='portal/account_base.html' if not staff else 'base.html',row=row,copy=data(row),form=form,message_form=message_form,
        patient_channel=not staff,front=front,clinical_packet=packet(row) if staff and not front else None,
        account_token=account_data(request)['account_token'] if not staff else ''),status=400 if request.method=='POST' else 200)


@copy_login
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request,staff=False):
    if not staff:account_context(request,unsafe=True)
    form=CopyConfirmForm(request.POST)
    if form.is_valid():
        try:row,replay=cmd.confirm(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            import django.core.signing as signing
            p=signing.loads(form.cleaned_data['proposal_token'],salt=cmd.CONTRACT,max_age=900)
            if p['action']=='CLAIM':
                token=cmd.pickup_token(request.user,row,form.cleaned_data['proposal_token'])
                return render(request,'portal/copy_pickup.html',dict(row=row,pickup_token=token))
            messages.success(request,'原办理结果已保留。' if replay else '本次办理已记录。')
            return redirect('record_copy_detail' if staff else 'portal_record_copy',pk=row.pk)
    return render(request,'clinical/copy_preview.html',dict(copy_base='portal/account_base.html' if not staff else 'base.html',form=form,patient_channel=not staff,failed=True,
        account_token=account_data(request)['account_token'] if not staff else ''),status=409)


@login_required(login_url='portal_login')
@never_cache
@require_GET
def download(request):
    account_context(request)
    try:row,pdf=cmd.pickup(actor=request.user,token=request.GET.get('ticket',''))
    except EXPECTED_ERRORS as exc:
        return render(request,'portal/copy_pickup.html',dict(error=str(exc)),status=409)
    return file_response(row,pdf)


def file_response(row,pdf):
    response=FileResponse(io.BytesIO(pdf),as_attachment=True,filename='病历电子副本-'+str(row.pk)+'.pdf',content_type='application/pdf')
    response['Cache-Control']='private, no-store';response['X-Content-Type-Options']='nosniff';return response
