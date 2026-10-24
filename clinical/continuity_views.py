from datetime import timedelta,datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404,redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from clinical import recall,laboratory
from clinical.continuity_forms import (RecallOpenForm,RecallContactForm,RecallResponsibilityForm,RecallCompletionForm,
    RecallWithdrawalForm,LabRequestForm,LabLogisticsForm,LabReviewForm,LabWithdrawalForm)
from clinical.continuity_selectors import recall_instructions,recall_projection,lab_projection,clinician_cases,coordination_summary,doctor_lab_queue
from clinical.encounter_views import clinical_render
from clinical.form_binding import patient_form_binding,check_patient_form
from clinical.plan_forms import ConfirmPlanActionForm
from clinical.plan_views import confirmation

RECALL_TITLES={'OPEN':'认领复诊联系责任','CONTACT':'记录实际联系与协调','REASSIGN':'接续失效的前台联系责任','RESUME':'明确恢复复诊协调','COMPLETE':'核对实际复诊完成依据','WITHDRAW':'按医师撤回指示结束协调'}
LAB_TITLES={'CREATE':'登记手工加工需求','CLAIM':'认领加工件协调责任','DISPATCH':'手工登记本周期送出','RECEIVE':'手工登记本周期返回','DELAY':'记录加工延误与下次跟进','REVIEW':'核对具体步骤并做临床验收','WITHDRAW':'明确撤回原加工请求'}


def work_preview(request,title,p,back,*,instruction=None,case=None,visit=None):
    source=visit or (instruction.source_record.encounter.visit if instruction else case.source_record.encounter.visit)
    safe=dict(values=p['values'],patient=source.patient,clinic=source.clinic,
        times={k:datetime.fromisoformat(v) for k,v in p['values'].items() if k in ('followup_due_at','occurred_at','assessed_at') and v},
        case_no=case.case_no if case else None,clinical=request.workspace.role=='DENTIST',
        evidence=p.get('evidence'),window=(instruction.earliest_on,instruction.latest_on) if instruction else None,
        service=instruction.service.name if instruction else p['step'].service.name if p.get('step') else case.step_version.service.name,
        step_description=p['step'].description if p.get('step') else None)
    form=ConfirmPlanActionForm(initial=dict(proposal_token=p['proposal_token']))
    return clinical_render(request,'clinical/continuity_confirm.html',dict(title=title,preview=safe,form=form,back=back))


@login_required
@never_cache
@require_GET
def recalls(request):
    queue=request.GET.get('queue','active')
    if queue not in ('active','unclaimed','overdue','completed','withdrawn','all'):queue='active'
    page=Paginator(recall_instructions(request.user,queue),20).get_page(request.GET.get('page'))
    return clinical_render(request,'clinical/recall_list.html',dict(page=page,rows=[recall_projection(i) for i in page],queue=queue,pagination_query='queue='+queue))


@login_required
@never_cache
@require_GET
def recall_detail(request,pk):
    row=get_object_or_404(recall.scoped_episodes(request.user),pk=pk)
    return clinical_render(request,'clinical/recall_detail.html',dict(episode=row,instruction=recall_projection(row.instruction),events=list(row.events.select_related('actor').order_by('-pk'))))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def recall_claim(request,pk):return recall_action_page(request,action='OPEN',instruction_id=pk)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def recall_action(request,pk,action):
    action=action.upper()
    if action not in RECALL_TITLES or action=='OPEN':raise Http404('未找到此复诊办理入口。')
    return recall_action_page(request,action=action,episode_id=pk)


def recall_action_page(request,*,action,instruction_id=None,episode_id=None):
    episode=None
    if action=='OPEN':instruction=get_object_or_404(recall.scoped_instructions(request.user),pk=instruction_id)
    else:episode=get_object_or_404(recall.scoped_episodes(request.user),pk=episode_id);instruction=episode.instruction
    projected=recall_projection(instruction);back=reverse('clinical_recall_detail',kwargs=dict(pk=episode.pk)) if episode else reverse('clinical_recalls');title=RECALL_TITLES[action]
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        row,response=confirmation(request,contract=recall.CONTRACT,roles=('FRONT_DESK',),expected=dict(action=action,instruction=instruction.pk,episode=episode.pk if episode else None),
            handler=recall.confirm_recall,title=title,back=back)
        return response or redirect('clinical_recall_detail',pk=row.pk)
    cls={'OPEN':RecallOpenForm,'CONTACT':RecallContactForm,'REASSIGN':RecallResponsibilityForm,'RESUME':RecallResponsibilityForm,'COMPLETE':RecallCompletionForm,'WITHDRAW':RecallWithdrawalForm}[action]
    options=dict(initial=dict(followup_due_at=timezone.now()+timedelta(days=1)))
    if action=='COMPLETE':options['candidates']=projected['evidence']
    form=cls(request.POST or None,**options);status=200
    if request.method=='POST':
        if form.is_valid():
            try:p=recall.prepare_recall(actor=request.user,action=action,instruction_id=instruction.pk,episode_id=episode.pk if episode else None,fields=form.fields_data())
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return work_preview(request,title,p,back,instruction=instruction)
        else:status=400
    return clinical_render(request,'clinical/continuity_action.html',dict(title=title,form=form,back=back,instruction=projected,action=action),status=status)


@login_required
@never_cache
@require_GET
def labs(request):
    queue=request.GET.get('queue','pending');rows=laboratory.front_cases(request.user)
    if queue=='unclaimed':rows=rows.filter(coordinator__isnull=True,state='REQUESTED')
    elif queue=='review':rows=rows.filter(state='RECEIVED')
    elif queue=='overdue':rows=rows.exclude(state__in=['ACCEPTED','WITHDRAWN']).filter(needed_on__lt=timezone.localdate())
    elif queue=='closed':rows=rows.filter(state__in=['ACCEPTED','WITHDRAWN'])
    elif queue!='all':queue='pending';rows=rows.exclude(state__in=['ACCEPTED','WITHDRAWN'])
    page=Paginator(rows.order_by('needed_on','pk'),20).get_page(request.GET.get('page'))
    return clinical_render(request,'clinical/lab_list.html',dict(page=page,rows=[lab_projection(c) for c in page],queue=queue,pagination_query='queue='+queue))


@login_required
@never_cache
@require_GET
def lab_detail(request,pk):
    case=get_object_or_404(laboratory.front_cases(request.user),pk=pk)
    return clinical_render(request,'clinical/lab_detail.html',dict(case=lab_projection(case)))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def lab_action(request,pk,action):
    action=action.upper()
    if action not in ('CLAIM','DISPATCH','RECEIVE','DELAY'):raise Http404('未找到此前台加工件办理入口。')
    case=get_object_or_404(laboratory.front_cases(request.user),pk=pk);back=reverse('clinical_lab_detail',kwargs=dict(pk=pk));title=LAB_TITLES[action]
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        row,response=confirmation(request,contract=laboratory.CONTRACT,roles=('FRONT_DESK',),expected=dict(action=action,case=pk,visit=None),handler=laboratory.confirm_lab,title=title,back=back)
        return response or redirect(back)
    form=LabLogisticsForm(request.POST or None,action=action,initial=dict(followup_due_at=timezone.now()+timedelta(days=1)));status=200
    if request.method=='POST':
        if form.is_valid():
            try:p=laboratory.prepare_lab(actor=request.user,action=action,case_id=case.pk,fields=form.fields_data())
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return work_preview(request,title,p,back,case=case)
        else:status=400
    return clinical_render(request,'clinical/continuity_action.html',dict(title=title,form=form,back=back,case=lab_projection(case),action=action),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def doctor_labs(request,pk):
    d,rows=clinician_cases(request.user,pk);visit=d['visit'];back=reverse('clinical_doctor_labs',kwargs=dict(pk=pk));title=LAB_TITLES['CREATE']
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        row,response=confirmation(request,contract=laboratory.CONTRACT,roles=('DENTIST',),expected=dict(action='CREATE',visit=pk,case=None),handler=laboratory.confirm_lab,title=title,back=back,visit=visit)
        return response or redirect(back)
    form=LabRequestForm(request.POST or None,visit=visit,actor=request.user,initial=dict(patient_binding=patient_form_binding(request.user,visit)));status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:p=laboratory.prepare_lab(actor=request.user,action='CREATE',visit_id=pk,fields=form.fields_data())
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return work_preview(request,title,p,back,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/doctor_labs.html',dict(d,rows=list(rows.prefetch_related('reviews__target_step_version')),form=form),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def doctor_lab_action(request,pk,case_id,action):
    action=action.upper()
    if action not in ('REVIEW','WITHDRAW'):raise Http404('未找到此医师加工件办理入口。')
    d,rows=clinician_cases(request.user,pk);visit=d['visit'];case=get_object_or_404(rows,pk=case_id)
    if not d['can_record']:raise PermissionDenied('当前仅有查阅范围，请由有本次记录权限的医师继续验收。')
    back=reverse('clinical_doctor_labs',kwargs=dict(pk=pk));title=LAB_TITLES[action]
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        saved,response=confirmation(request,contract=laboratory.CONTRACT,roles=('DENTIST',),expected=dict(action=action,case=case_id,visit=pk),handler=laboratory.confirm_lab,title=title,back=back,visit=visit)
        return response or redirect(back)
    initial=dict(patient_binding=patient_form_binding(request.user,visit))
    form=LabReviewForm(request.POST or None,visit=visit,case=case,actor=request.user,initial=initial) if action=='REVIEW' else LabWithdrawalForm(request.POST or None,initial=initial)
    status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:p=laboratory.prepare_lab(actor=request.user,action=action,case_id=case_id,visit_id=pk,fields=form.fields_data())
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return work_preview(request,title,p,back,case=case,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/continuity_action.html',dict(title=title,form=form,back=back,clinical_case=case,visit=visit,action=action),status=status)


@login_required
@never_cache
@require_GET
def summary(request):
    rows=coordination_summary(request.user)
    return clinical_render(request,'clinical/continuity_summary.html',dict(rows=rows))


@login_required
@never_cache
@require_GET
def doctor_queue(request):
    queue=request.GET.get('queue','review');rows=doctor_lab_queue(request.user)
    if queue=='pending':rows=rows.exclude(state__in=['ACCEPTED','WITHDRAWN'])
    elif queue!='all':queue='review';rows=rows.filter(state='RECEIVED')
    page=Paginator(rows,20).get_page(request.GET.get('page'))
    return clinical_render(request,'clinical/doctor_lab_queue.html',dict(page=page,rows=page,queue=queue,pagination_query='queue='+queue))
