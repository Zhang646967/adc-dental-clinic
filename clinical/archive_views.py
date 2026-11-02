import io,json
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import FileResponse,HttpResponse
from django.shortcuts import redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET,require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import read_proposal
from clinical import archives,archive_corrections,archive_selectors
from clinical.archive_models import ArchiveSubmission,ArchiveAmendment,ArchivePackage
from clinical.archive_forms import ArchiveRequestForm,AmendmentRequestForm,ArchiveReviewForm,ArchiveActionForm,ArchiveConfirmForm
from clinical.encounter_views import clinical_render

COMMANDS={
 'submit':(archives.SUBMIT,archives.confirm_submit),
 'review':(archives.REVIEW,archives.confirm_review),
 'action':(archives.ACTION,archives.confirm_action),
 'amend':(archive_corrections.SUBMIT,archive_corrections.confirm_submit),
 'amend-review':(archive_corrections.REVIEW,archive_corrections.confirm_review),
 'amend-cancel':(archive_corrections.CANCEL,archive_corrections.confirm_cancel)}


@login_required
@never_cache
@require_GET
def listing(request):
    d=archive_selectors.worklist(request.user)
    for key in ('owned','reviews','correction_reviews'):d[key]=Paginator(d[key],25).get_page(request.GET.get(key+'_page'))
    return clinical_render(request,'clinical/archive_worklist.html',d)


@login_required
@never_cache
@require_GET
def summary(request):
    d=archive_selectors.summary(request.user)
    d['front_rows']=Paginator(d['front_rows'],25).get_page(request.GET.get('page'))
    return clinical_render(request,'clinical/archive_summary.html',d)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def workspace(request,pk):
    d=archive_selectors.details(request.user,pk);action=request.POST.get('action') if request.method=='POST' else None
    if request.method=='POST' and action not in ('submit','amend'):raise PermissionDenied('未知归档办理操作。')
    form=ArchiveRequestForm(request.POST if action=='submit' else None,details=d)
    amend=AmendmentRequestForm(request.POST if action=='amend' else None,details=d)
    if request.method=='POST':
        chosen=amend if action=='amend' else form
        if chosen.is_valid():
            try:
                values=chosen.cleaned_data
                if action=='submit':p=archives.prepare_submit(actor=request.user,visit_id=pk,kind=values['kind'],reason=values['reason'],fee_version_id=values['fee_version'] or None,reviewer_id=values['reviewer'])
                elif action=='amend':p=archive_corrections.prepare_submit(actor=request.user,visit_id=pk,target=values['target'],reason=values['reason'],reviewer_id=values['reviewer'])
                else:raise ValueError('Unknown archive action')
            except EXPECTED_ERRORS as exc:add_error(chosen,exc)
            else:return preview_response(request,action,p,visit=d['visit'])
    return clinical_render(request,'clinical/archive_workspace.html',dict(d,form=form,amend_form=amend),status=400 if request.method=='POST' else 200)


def preview_response(request,action,p,**context):
    return clinical_render(request,'clinical/archive_confirm.html',dict(context,prepared=p,action=action,
        form=ArchiveConfirmForm(initial={'proposal_token':p['proposal_token']})))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def request_detail(request,pk,amendment=False):
    row=get_object_or_404(ArchiveAmendment if amendment else ArchiveSubmission,pk=pk)
    d=archive_selectors.details(request.user,row.archive.encounter.visit_id)
    form=ArchiveReviewForm(request.POST if request.method=='POST' and request.POST.get('action')=='review' else None)
    action_form=ArchiveActionForm(request.POST if request.method=='POST' and request.POST.get('action')=='action' else None)
    if amendment:action_form.fields['action'].choices=[('WITHDRAW','撤回未实施的补正申请')]
    error_form=form
    if request.method=='POST':
        try:
            action=request.POST.get('action')
            if action=='review' and form.is_valid():
                if amendment:p=archive_corrections.prepare_review(actor=request.user,amendment_id=pk,**form.cleaned_data)
                else:p=archives.prepare_review(actor=request.user,submission_id=pk,**form.cleaned_data)
                return preview_response(request,'amend-review' if amendment else 'review',p,visit=d['visit'])
            if action=='action' and action_form.is_valid():
                error_form=action_form;values=action_form.cleaned_data
                if amendment:p=archive_corrections.prepare_cancel(actor=request.user,amendment_id=pk,reason=values['reason'])
                else:p=archives.prepare_action(actor=request.user,submission_id=pk,**values)
                return preview_response(request,'amend-cancel' if amendment else 'action',p,visit=d['visit'])
        except EXPECTED_ERRORS as exc:add_error(error_form,exc)
    return clinical_render(request,'clinical/archive_request.html',dict(d,row=row,is_amendment=amendment,
        form=form,action_form=action_form,assigned_to_me=row.assigned_reviewer.user_id==request.user.pk),status=400 if request.method=='POST' else 200)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['POST'])
def confirm(request,action):
    form=ArchiveConfirmForm(request.POST)
    if action not in COMMANDS:from django.http import Http404;raise Http404()
    if form.is_valid():
        try:
            contract,command=COMMANDS[action]
            read_proposal(request.user,contract,('DENTIST',),form.cleaned_data['proposal_token'])
            row,replayed=command(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'该次办理已保留，未产生重复结果。' if replayed else '本次归档办理已记录；原文书、实际治疗及资金事实保留。')
            return redirect('clinical_archive',pk=row.archive.encounter.visit_id)
    return clinical_render(request,'clinical/archive_confirm.html',dict(form=form,action=action),status=409)


@login_required
@never_cache
@require_GET
def download(request,pk,manifest=False):
    row=get_object_or_404(ArchivePackage.objects.select_related('archive__encounter__visit__dentist'),pk=pk)
    archive_selectors.authorize_read(request.user,row.archive.encounter.visit)
    if manifest:
        response=HttpResponse(json.dumps(row.manifest,ensure_ascii=False,indent=2),content_type='application/json; charset=utf-8')
        response['Content-Disposition']='attachment; filename="archive-manifest-'+str(row.pk)+'.json"'
        return response
    return FileResponse(io.BytesIO(bytes(row.pdf)),as_attachment=True,filename='病历归档-第'+str(row.number)+'包.pdf',content_type='application/pdf')
