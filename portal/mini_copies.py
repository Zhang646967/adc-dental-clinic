"""Account-bound copy applications; no inherited appointment or medical-proxy read."""
from django.core.paginator import Paginator
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.rules import RuleError
from portal.mini_api import endpoint,result,validated
from portal.account_access import account_context
from clinical import record_copies as cmd
from clinical.copy_forms import CopyApplyForm,CopyMessageForm,CopyConfirmForm
from clinical.copy_views import patient_rows,file_response
from clinical.copy_projection import data


@endpoint(subject_optional=True)
def listing(request):
    account_context(request)
    page=Paginator(patient_rows(request.user),20).get_page(request.GET.get('page'))
    return result(request,dict(rows=[data(r) for r in page],page=page.number,pages=page.paginator.num_pages,
        previous=page.previous_page_number() if page.has_previous() else None,next=page.next_page_number() if page.has_next() else None))


@endpoint(subject_optional=True)
def options(request):
    account_context(request)
    form=CopyApplyForm(actor=request.user,clinic_id=request.GET.get('clinic'))
    return result(request,dict(clinics=[dict(id=c.pk,name=c.public_contact['name']) for c in form.fields['clinic'].queryset],
        clinic=form.fields['clinic'].initial,visits=[dict(id=k,label=v) for k,v in form.fields['visits'].choices],
        packages=[dict(id=k,label=v) for k,v in form.fields['package'].choices],sections=[dict(id=k,label=v) for k,v in cmd.SECTIONS.items()]))


@sensitive_post_parameters()
@endpoint(('POST',),subject_optional=True)
def submit_preview(request):
    account_context(request,unsafe=True);values=request.POST.copy()
    for key in ('visits','sections'):
        if len(values.getlist(key))==1:values.setlist(key,[x for x in values.get(key,'').split(',') if x])
    form=CopyApplyForm(values,actor=request.user,clinic_id=values.get('clinic'));validated(form)
    p=cmd.prepare(actor=request.user,action='SUBMIT',fields=form.values())
    return result(request,p)


@endpoint(subject_optional=True)
def detail(request,pk):
    account_context(request);row=get_object_or_404(patient_rows(request.user),pk=pk);cmd.recipient(row,request.user)
    return result(request,data(row))


@sensitive_post_parameters()
@endpoint(('POST',),subject_optional=True)
def action_preview(request,pk):
    account_context(request,unsafe=True)
    action=request.POST.get('action')
    if action not in ('RESUBMIT','WITHDRAW','CLAIM'):raise PermissionDenied
    fields={} if action=='CLAIM' else validated(CopyMessageForm(request.POST))
    return result(request,cmd.prepare(actor=request.user,action=action,request_id=pk,fields=fields))


@sensitive_post_parameters()
@endpoint(('POST',),subject_optional=True)
def confirm(request):
    account_context(request,unsafe=True);fields=validated(CopyConfirmForm(request.POST))
    try:p=signing.loads(fields['proposal_token'],salt=cmd.CONTRACT,max_age=900)
    except signing.BadSignature:raise RuleError('办理预览已失效，请重新核对。') from None
    if p['action'] not in ('SUBMIT','RESUBMIT','WITHDRAW','CLAIM'):raise PermissionDenied
    row,replay=cmd.confirm(actor=request.user,**fields);response=dict(id=row.pk,replayed=replay,state=row.state)
    if p['action']=='CLAIM':response['ticket']=cmd.pickup_token(request.user,row,fields['proposal_token'])
    return result(request,response)


@endpoint(subject_optional=True)
def download(request):
    account_context(request);row,pdf=cmd.pickup(actor=request.user,token=request.GET.get('ticket',''))
    return file_response(row,pdf)
