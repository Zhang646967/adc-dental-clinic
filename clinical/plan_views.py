import uuid
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import read_proposal
from clinical import plans,executions,next_visits
from clinical.encounter_views import clinical_render
from clinical.encounter_selectors import encounter_details
from clinical.form_binding import patient_form_binding,check_patient_form
from clinical.plan_models import PlanDraft,PlanStepVersion,PerformedProcedure
from clinical.plan_selectors import clinician_plans,clinician_plan_details,patient_plan_rows,self_plan_details,actual_details
from clinical.plan_forms import (PlanStartForm,PlanNotesForm,StepForm,PlanReasonForm,StepRemoveForm,DecisionForm,
    ExecutionForm,InstructionForm,ConfirmPlanActionForm,PlainReasonForm,LinkAppointmentForm,PlanRefreshForm)


def show_preview(request,title,preview,back,*,base_template='base.html',visit=None):
    if preview.get('payload'):
        from registry.models import TreatmentType
        from scheduling.models import BookingService
        types=dict(TreatmentType.objects.filter(pk__in=[r['treatment_type'] for r in preview['payload']['steps']]).values_list('pk','name'))
        services=dict(BookingService.objects.filter(pk__in=[r['service'] for r in preview['payload']['steps']]).values_list('pk','name'))
        preview['display_steps']=[dict(r,catalogue_name=types[r['treatment_type']],service_name=services[r['service']]) for r in preview['payload']['steps']]
    form=ConfirmPlanActionForm(initial={'proposal_token':preview['proposal_token']})
    return clinical_render(request,'clinical/plan_confirm.html',dict(title=title,preview=preview,form=form,back=back,base_template=base_template,visit=visit))


def confirmation(request,*,contract,roles,expected,handler,title,back,base_template='base.html',visit=None):
    form=ConfirmPlanActionForm(request.POST)
    if form.is_valid():
        try:
            data=read_proposal(request.user,contract,roles,form.cleaned_data['proposal_token'])['data']
            if any(data.get(k)!=v for k,v in expected.items()):raise PermissionDenied('确认内容属于其他就诊人或事项，请返回原记录核对。')
            result,replay=handler(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'已核对原办理结果，未重复创建。' if replay else '本次办理已保存，已显示当前业务结果。')
            return result,None
    response=clinical_render(request,'clinical/plan_confirm.html',dict(title=title,form=form,back=back,base_template=base_template,visit=visit),status=409)
    return None,response


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def plan_list(request,pk):
    details,rows=clinician_plans(request.user,pk);visit=details['visit']
    form=PlanStartForm(request.POST or None,initial=dict(patient_binding=patient_form_binding(request.user,visit),operation_id=uuid.uuid4()))
    status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:plan,replay=plans.start_plan(actor=request.user,visit_id=pk,operation_id=form.cleaned_data['operation_id'])
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return redirect('clinical_plan_detail',pk=pk,plan_id=plan.pk)
        else:status=400
    plan_rows=[dict(plan=p,version=plans.current_version(p),has_draft=PlanDraft.objects.filter(plan=p).exists()) for p in rows]
    return clinical_render(request,'clinical/plan_list.html',dict(details,form=form,plan_rows=plan_rows),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def plan_detail(request,pk,plan_id):
    d=clinician_plan_details(request.user,pk,plan_id,revision=request.GET.get('revision'));visit=d['visit'];plan=d['plan']
    if request.method=='POST':
        if request.GET.get('revision') is not None:raise PermissionDenied('历史方案只供查阅，请返回当前版本办理。')
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
    action=request.POST.get('action') if request.method=='POST' else None
    resumed=request.method=='POST' and request.POST.get('review_current')=='yes'
    post=request.POST
    if resumed:
        if action not in ('NOTES','ADD_STEP','UPDATE_STEP') or d['draft'] is None or not d['can_record']:raise PermissionDenied('请从可编辑方案核对当前草稿。')
        post=request.POST.copy();post.update(expected_revision=plan.revision,operation_id=str(uuid.uuid4()))
        messages.info(request,'已载入当前方案版本号，本页填写仍未保存。请比较已保存内容，再明确提交。')
    common=dict(patient_binding=patient_form_binding(request.user,visit),expected_revision=plan.revision)
    initial=lambda **values:dict(common,operation_id=uuid.uuid4(),**values)
    bound=lambda *names:post if request.method=='POST' and action in names else None
    payload=d['plan_payload'] or dict(summary='',discussion_note='',amendment_reason='',steps=[])
    edit=request.GET.get('edit');edit_row=None
    if edit is not None:
        try:
            number=int(edit)
            if d['draft'] is None or not 1<=number<=len(payload['steps']):raise ValueError
            edit_row=dict(payload['steps'][number-1],sequence=number,surfaces=list(payload['steps'][number-1]['surface']))
        except (TypeError,ValueError):raise Http404('草稿步骤已变化，请返回当前计划。')
    forms=dict(notes_form=PlanNotesForm(bound('NOTES'),initial=initial(**{k:payload[k] for k in ('summary','discussion_note','amendment_reason')}),auto_id='plan_note_%s'),
        step_form=StepForm(bound('ADD_STEP','UPDATE_STEP'),actor=request.user,visit=visit,initial=initial(**(edit_row or dict(estimated_quantity='1',charge_basis='PER_EXECUTION'))),auto_id='plan_step_%s'),
        amend_form=PlanReasonForm(bound('BEGIN_AMEND'),initial=initial(),auto_id='plan_amend_%s'),
        discard_form=PlanReasonForm(bound('DISCARD'),initial=initial(),auto_id='plan_discard_%s'),
        refresh_form=PlanRefreshForm(bound('REFRESH_SOURCE'),initial=initial(),auto_id='plan_refresh_%s'))
    remove=StepRemoveForm(bound('REMOVE_STEP'),initial=initial(),auto_id='plan_remove_%s')
    by_action=dict(NOTES=forms['notes_form'],ADD_STEP=forms['step_form'],UPDATE_STEP=forms['step_form'],BEGIN_AMEND=forms['amend_form'],DISCARD=forms['discard_form'],REMOVE_STEP=remove,REFRESH_SOURCE=forms['refresh_form'])
    status=200;rebase=False
    if request.method=='POST' and not resumed:
        if action not in by_action:raise PermissionDenied('未知治疗计划操作。')
        form=by_action[action]
        if form.is_valid():
            data=form.fields_data() if action in ('ADD_STEP','UPDATE_STEP') else dict(form.cleaned_data)
            expected=data.pop('expected_revision')
            op=data.pop('operation_id');data.pop('patient_binding',None);data.pop('confirmed',None)
            try:plans.change_plan(actor=request.user,visit_id=pk,plan_id=plan_id,expected_revision=expected,operation_id=op,action=action,fields=data)
            except EXPECTED_ERRORS as exc:
                add_error(form,exc);status=409;d=clinician_plan_details(request.user,pk,plan_id)
                rebase=action in ('NOTES','ADD_STEP','UPDATE_STEP') and d['draft'] is not None and expected!=d['plan'].revision
            else:
                messages.success(request,'方案草稿已保存；已确认的旧方案与患者决定继续保留。')
                return redirect('clinical_plan_detail',pk=pk,plan_id=plan_id)
        else:status=400
    draft_rows=[]
    for number,row in enumerate((d['draft'].payload['steps'] if d['draft'] else []),1):
        rf=remove if request.method=='POST' and action=='REMOVE_STEP' and str(number)==request.POST.get('sequence') else StepRemoveForm(initial=initial(sequence=number),auto_id='remove_'+str(number)+'_%s')
        draft_rows.append(dict(row,sequence=number,remove_form=rf))
    return clinical_render(request,'clinical/plan_detail.html',dict(d,**forms,draft_rows=draft_rows,action=action,rebase_available=rebase,editing=bool(edit_row) or action=='UPDATE_STEP'),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def plan_preview(request,pk,plan_id):
    d=clinician_plan_details(request.user,pk,plan_id);back=reverse('clinical_plan_detail',kwargs=dict(pk=pk,plan_id=plan_id));title='确认治疗计划版本'
    if request.method=='POST':
        row,response=confirmation(request,contract=plans.PLAN_CONTRACT,roles=('DENTIST',),expected=dict(visit=pk,plan=plan_id),handler=plans.confirm_plan,title=title,back=back,visit=d['visit'])
        return response or redirect(back)
    try:p=plans.prepare_plan(actor=request.user,visit_id=pk,plan_id=plan_id)
    except EXPECTED_ERRORS as exc:messages.error(request,str(exc));return redirect(back)
    return show_preview(request,title,p,back,visit=d['visit'])


def decision_page(request,*,step_id,visit_id=None,plan_id=None):
    manual=visit_id is not None;base='base.html' if manual else 'portal/base.html'
    if manual:
        d=encounter_details(request.user,visit_id);visit=d['visit']
        step=get_object_or_404(PlanStepVersion.objects.select_related('version__plan'),pk=step_id,version__plan__origin_encounter__visit__patient_id=visit.patient_id,version__plan__origin_encounter__visit__clinic_id=visit.clinic_id)
        back=reverse('clinical_plan_detail',kwargs=dict(pk=visit_id,plan_id=step.version.plan_id));binding=patient_form_binding(request.user,visit)
    else:
        d=self_plan_details(request.user,plan_id);visit=None
        step=get_object_or_404(PlanStepVersion.objects.select_related('version__plan'),pk=step_id,version__plan=d['plan']);back=reverse('portal_plan',kwargs=dict(pk=plan_id));binding=''
    title='记录患者本人对步骤的决定' if manual else '核对我的方案步骤'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        expected=dict(plan=step.version.plan_id,step=step.pk,visit=visit_id)
        row,response=confirmation(request,contract=plans.DECISION_CONTRACT,roles=('DENTIST','PATIENT'),expected=expected,handler=plans.confirm_decision,title=title,back=back,base_template=base,visit=visit)
        return response or redirect(back)
    form=DecisionForm(request.POST or None,manual=manual,initial=dict(patient_binding=binding));status=200
    if request.method=='POST':
        if manual:check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            values=dict(form.cleaned_data);values.pop('patient_binding',None)
            try:p=plans.prepare_decision(actor=request.user,step_id=step.pk,fields=values,visit_id=visit_id)
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return show_preview(request,title,p,back,base_template=base,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/plan_action.html',dict(title=title,form=form,step=step,visit=visit,back=back,base_template=base),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def manual_decision(request,pk,step_id):return decision_page(request,step_id=step_id,visit_id=pk)


@login_required(login_url='portal_login')
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def self_decision(request,pk,step_id):return decision_page(request,step_id=step_id,plan_id=pk)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def actual(request,pk):
    d=actual_details(request.user,pk);visit=d['visit'];back=reverse('clinical_actual',kwargs=dict(pk=pk));title='确认本次实际执行与计费'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        row,response=confirmation(request,contract=executions.ACTUAL_CONTRACT,roles=('DENTIST',),expected=dict(visit=pk),handler=executions.confirm_execution,title=title,back=back,visit=visit)
        return response or redirect(back)
    initial=dict(patient_binding=patient_form_binding(request.user,visit),quantity='1',progress='COMPLETE',charge_mode='CHARGE')
    if request.GET.get('step'):
        from clinical.plan_forms import current_steps
        step=get_object_or_404(current_steps(visit),pk=request.GET['step'])
        initial.update(step_version=step.pk,treatment_type=step.treatment_type_id,tooth=step.tooth,surfaces=list(step.surface),quantity=str(step.estimated_quantity))
    form=ExecutionForm(request.POST or None,visit=visit,initial=initial);status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:p=executions.prepare_execution(actor=request.user,visit_id=pk,fields=form.fields_data())
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return show_preview(request,title,p,back,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/actual.html',dict(d,form=form,back=back),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def void_actual(request,pk,performed_id):
    d=encounter_details(request.user,pk);visit=d['visit'];row=get_object_or_404(PerformedProcedure,pk=performed_id,encounter__visit=visit)
    back=reverse('clinical_actual',kwargs=dict(pk=pk));title='撤回尚未发布的误录执行'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        saved,response=confirmation(request,contract=executions.VOID_CONTRACT,roles=('DENTIST',),expected=dict(visit=pk,performed=performed_id),handler=executions.confirm_void,title=title,back=back,visit=visit)
        return response or redirect(back)
    form=PlainReasonForm(request.POST or None,initial=dict(patient_binding=patient_form_binding(request.user,visit)));status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:p=executions.prepare_void(actor=request.user,visit_id=pk,performed_id=performed_id,reason=form.cleaned_data['reason'])
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return show_preview(request,title,p,back,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/plan_action.html',dict(title=title,form=form,performed=row,visit=visit,back=back,base_template='base.html'),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def instruction(request,pk):
    d=actual_details(request.user,pk);visit=d['visit'];back=reverse('clinical_next_visit',kwargs=dict(pk=pk));title='确认后续就诊指示'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        row,response=confirmation(request,contract=next_visits.CONTRACT,roles=('DENTIST',),expected=dict(visit=pk,action='CREATE'),handler=next_visits.confirm_instruction,title=title,back=back,visit=visit)
        return response or redirect(back)
    form=InstructionForm(request.POST or None,actor=request.user,visit=visit,initial=dict(patient_binding=patient_form_binding(request.user,visit),earliest_on=timezone.localdate()));status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:p=next_visits.prepare_instruction(actor=request.user,visit_id=pk,fields=form.fields_data())
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return show_preview(request,title,p,back,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/next_instruction.html',dict(d,form=form,back=back),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def withdraw_instruction(request,pk,instruction_id):
    d=actual_details(request.user,pk);visit=d['visit'];row=next((i for i in d['instruction_rows'] if i.pk==instruction_id),None)
    if row is None:raise Http404('未找到本次患者的后续指示。')
    back=reverse('clinical_next_visit',kwargs=dict(pk=pk));title='明确撤回后续指示'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        saved,response=confirmation(request,contract=next_visits.CONTRACT,roles=('DENTIST',),expected=dict(visit=pk,instruction=instruction_id,action='WITHDRAW'),handler=next_visits.confirm_instruction,title=title,back=back,visit=visit)
        return response or redirect(back)
    form=PlainReasonForm(request.POST or None,initial=dict(patient_binding=patient_form_binding(request.user,visit)));status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:p=next_visits.prepare_withdrawal(actor=request.user,visit_id=pk,instruction_id=instruction_id,reason=form.cleaned_data['reason'])
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return show_preview(request,title,p,back,visit=visit)
        else:status=400
    return clinical_render(request,'clinical/plan_action.html',dict(title=title,form=form,instruction=row,visit=visit,back=back,base_template='base.html'),status=status)


@login_required
@never_cache
@require_GET
def next_list(request):
    rows=next_visits.front_instructions(request.user);state=request.GET.get('state','OPEN')
    if state in ('OPEN','WITHDRAWN'):rows=rows.filter(state=state)
    page=Paginator(rows,20).get_page(request.GET.get('page'))
    projected=[next_visits.instruction_booking_projection(r) for r in page]
    return clinical_render(request,'clinical/next_list.html',dict(page=page,rows=projected,state=state,pagination_query='state='+state if state in ('OPEN','WITHDRAWN') else 'state=all'))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def link_appointment(request,pk):
    row=get_object_or_404(next_visits.front_instructions(request.user),pk=pk);projected=next_visits.instruction_booking_projection(row)
    back=reverse('clinical_next_list');title='关联已确认的后续预约'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        saved,response=confirmation(request,contract=next_visits.CONTRACT,roles=('FRONT_DESK',),expected=dict(instruction=pk,action='LINK'),handler=next_visits.confirm_link,title=title,back=back)
        return response or redirect(back)
    form=LinkAppointmentForm(request.POST or None,instruction=row);status=200
    if request.method=='POST':
        if form.is_valid():
            try:p=next_visits.prepare_link(actor=request.user,instruction_id=pk,visit_id=form.cleaned_data['visit'].pk)
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return show_preview(request,title,p,back)
        else:status=400
    return clinical_render(request,'clinical/plan_action.html',dict(title=title,form=form,booking_instruction=projected,back=back,base_template='base.html'),status=status)


@login_required(login_url='portal_login')
@never_cache
@require_GET
def self_list(request):
    rows=patient_plan_rows(request.user);page=Paginator(rows,20).get_page(request.GET.get('page'))
    return clinical_render(request,'portal/plans.html',dict(page=page,rows=[dict(plan=p,version=plans.current_version(p)) for p in page]))


@login_required(login_url='portal_login')
@never_cache
@require_GET
def self_detail(request,pk):
    d=self_plan_details(request.user,pk,revision=request.GET.get('revision'))
    return clinical_render(request,'portal/plan.html',d)
