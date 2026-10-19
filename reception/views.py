from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_http_methods,require_GET
from django.views.decorators.debug import sensitive_post_parameters
from django.utils import timezone
from adc_core.http_support import EXPECTED_ERRORS,add_error
from reception.services import cases_for,clinic_for,prepare_case,confirm_case,contact_owners
from reception.models import STATES,REASONS
from reception.forms import CaseForm,NoteForm,AssignForm,CloseForm,WaitForm,BookingForm
from scheduling.resource_forms import ConfirmForm
from scheduling.resource_candidates import candidates

@login_required
@require_GET
def listing(request):
    qs=cases_for(request.user);queue=request.GET.get('queue','open')
    if queue=='overdue':qs=qs.filter(due_at__lt=timezone.now()).exclude(state__in=['BOOKED','UNBOOKED','WITHDRAWN'])
    elif queue=='mine':qs=qs.filter(owner=request.user).exclude(state__in=['BOOKED','UNBOOKED','WITHDRAWN'])
    elif queue=='open':qs=qs.exclude(state__in=['BOOKED','UNBOOKED','WITHDRAWN'])
    return render(request,'reception/list.html',{'page':Paginator(qs,20).get_page(request.GET.get('page')),'queue':queue,'now':timezone.now()})

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def create(request):
    clinic=clinic_for(request.user);form=CaseForm(request.POST or None,clinic=clinic,initial={'owner':request.user.pk,'state':'VERIFY'})
    if request.method=='POST' and request.POST.get('action')=='confirm':return confirmation(request)
    if request.method=='POST' and form.is_valid():
        try:preview=prepare_case(actor=request.user,action='CREATE',fields=form.business_fields())
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'reception/confirm.html',{'preview':_display(preview,clinic),'form':ConfirmForm(initial={'proposal_token':preview['proposal_token']})})
    return render(request,'reception/form.html',{'title':'登记电话接待','form':form,'button':'核对接待资料'})

def confirmation(request,case_id=None):
    form=ConfirmForm(request.POST)
    if form.is_valid():
        try:
            row,repeated=confirm_case(actor=request.user,proposal_token=form.cleaned_data['proposal_token'],confirmed=form.cleaned_data['confirmed'],expected_case_id=case_id)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'此前已办理，已返回当前结果。' if repeated else '接待办理已保存，沟通历史继续保留。')
            return redirect('reception_detail',pk=row.pk)
    return render(request,'reception/confirm.html',{'form':form,'failed':True},status=409)

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def detail(request,pk):
    row=get_object_or_404(cases_for(request.user),pk=pk);clinic=row.clinic_id
    if request.method=='POST' and request.POST.get('action')=='confirm':return confirmation(request,pk)
    action=request.POST.get('case_action') if request.method=='POST' else request.GET.get('do','UPDATE')
    classes={'CREATE':CaseForm,'UPDATE':CaseForm,'NOTE':NoteForm,'ASSIGN':AssignForm,'UNBOOKED':CloseForm,
        'WITHDRAW':NoteForm,'WAITLIST':WaitForm,'BOOK':BookingForm,'LINK_WAITLIST':NoteForm}
    if action not in classes:action='UPDATE'
    if row.state in ('BOOKED','UNBOOKED','WITHDRAWN') and action=='UPDATE':action='NOTE'
    initial={'caller_name':row.caller_name,'relationship':row.relationship,'contact':row.contact,'patient_hint':row.patient_hint,'owner':row.owner_id,'due_at':row.due_at,'state':row.state if row.state!='WAITLIST' else 'CONTACT',
        'patient_no':request.GET.get('patient_no',row.patient.patient_no if row.patient else ''),'service_id':row.service_id,
        'dentist_id':row.preferred_dentist_id,'preferred_day':row.preferred_day}
    if action=='BOOK':
        for k in ('slot_id','start','end'):
            if request.GET.get(k):initial[k]=request.GET[k]
    kwargs={'initial':initial}
    if action in ('UPDATE','ASSIGN'):kwargs['clinic']=clinic
    if action=='UPDATE':kwargs['existing']=True
    form=classes[action](request.POST or None,**kwargs)
    if request.method=='POST' and form.is_valid():
        d=form.business_fields() if action=='UPDATE' else dict(form.cleaned_data)
        if action=='ASSIGN':d['owner']=d['owner'].pk
        try:preview=prepare_case(actor=request.user,case_id=row.pk,expected_revision=int(request.POST.get('revision','-1')),action=action,fields=d)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'reception/confirm.html',{'preview':_display(preview,clinic),'form':ConfirmForm(initial={'proposal_token':preview['proposal_token']})})
    choices=[];problem='';day=row.preferred_day or timezone.localdate()
    try:
        from datetime import date
        if request.GET.get('day'):day=date.fromisoformat(request.GET['day'])
        if row.service_id:
            choices=candidates(clinic_id=clinic,service_id=row.service_id,day=day,patient_id=row.patient_id,
                dentist_id=row.preferred_dentist_id,horizon=False)
    except (ValueError,*EXPECTED_ERRORS) as exc:problem=str(exc)
    for choice in choices:
        choice['url']='?'+urlencode({'do':'BOOK','slot_id':choice['slot_id'],'start':timezone.localtime(choice['start']).strftime('%Y-%m-%dT%H:%M'),
            'end':timezone.localtime(choice['end']).strftime('%Y-%m-%dT%H:%M')})
    eligible=contact_owners(clinic).filter(pk=row.owner_id).exists()
    return render(request,'reception/detail.html',{'case':row,'history':row.communications.select_related('actor'),
        'form':form,'case_action':action,'choices':choices,'day':day,'problem':problem,'owner_valid':eligible,'now':timezone.now()})


def _display(preview,clinic):
    from accounts.models import UserAccount
    from registry.models import Dentist
    from scheduling.resource_models import BookingService
    labels={'caller_name':'来电者','relationship':'与患者关系','contact':'待核实联络','patient_hint':'患者称呼','owner':'负责人','due_at':'联系期限',
        'state':'办理状态','patient_no':'患者业务编号','service_id':'预约服务','dentist_id':'医师偏好','preferred_day':'日期偏好',
        'reason_code':'未成约原因','earliest':'最早开始','latest':'最晚结束'}
    states=dict(STATES)
    rows=[]
    for k,v in preview['fields'].items():
        if k not in labels:continue
        if k=='owner' and v:v=UserAccount.objects.get(pk=v).username
        if k=='service_id' and v:v=BookingService.objects.get(pk=v,department__clinic_id=clinic).name
        if k=='dentist_id' and v:v=Dentist.objects.get(pk=v).name
        if k=='state':v=states.get(v,v)
        if k=='reason_code':v=dict(REASONS).get(v,v)
        rows.append((labels[k],v))
    preview['display_fields']=rows
    preview['action_label']={'CREATE':'登记来电','UPDATE':'核实资料','ASSIGN':'责任交接','NOTE':'追加沟通','BOOK':'明确成约','WAITLIST':'转入候补',
        'LINK_WAITLIST':'核对原候补结果','UNBOOKED':'登记未成约','WITHDRAW':'撤回接待'}.get(preview['action'],preview['action'])
    return preview
