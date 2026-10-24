import uuid
from datetime import datetime
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_POST,require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import read_proposal
from clinical import encounters as cmd
from clinical.authority import require_visit_authority
from clinical.encounter_selectors import encounter_details,clinical_worklist
from clinical.encounter_forms import HistoryForm,StartEncounterForm,ClinicalNotesForm,FindingForm,RemoveFindingForm,ClinicalReasonForm,ClinicalConfirmForm
from clinical.models import ClinicalHistoryVersion
from clinical.form_binding import patient_form_binding,check_patient_form
from clinical.tooth_rules import PERMANENT,PRIMARY,KINDS
from portal.policies import patient_access
from scheduling.models import Visit


def clinical_render(request,template,context,**kwargs):
    response=render(request,template,context,**kwargs)
    response.adc_sensitive_read_authorized=True
    return response


@login_required
@never_cache
@require_GET
def worklist(request):
    rows=clinical_worklist(request.user);queue=request.GET.get('queue','active')
    if queue=='draft':rows=rows.filter(clinical_draft=True)
    elif queue=='confirmed':rows=rows.filter(clinical_revision__isnull=False)
    elif queue!='all':queue='active';rows=rows.filter(status__in=['SCHEDULED','CHECKED_IN'])
    page=Paginator(rows,25).get_page(request.GET.get('page'))
    return clinical_render(request,'clinical/encounter_worklist.html',dict(page=page,queue=queue))


def entry_forms(request,details,action,post_data=None):
    head=details['encounter'];revision=head.revision if head else 0
    binding=patient_form_binding(request.user,details['visit'])
    def initial():return dict(expected_revision=revision,operation_id=uuid.uuid4(),patient_binding=binding)
    bound=lambda name:(post_data if post_data is not None else request.POST) if request.method=='POST' and action==name else None
    notes=dict(details['payload'],history=details['payload'].get('history_id'),observed_at=None,**initial())
    return dict(
        start_form=StartEncounterForm(bound('START'),initial=dict(expected_visit_version=details['visit'].lock_version,operation_id=uuid.uuid4(),patient_binding=binding),auto_id='start_%s'),
        notes_form=ClinicalNotesForm(bound('NOTES'),visit=details['visit'],is_amendment=bool(details['draft'] and details['draft'].base_record_id),initial=notes,auto_id='clinical_note_%s'),
        finding_form=FindingForm(bound('ADD_FINDING'),initial=initial(),auto_id='finding_%s'),
        remove_form=RemoveFindingForm(bound('REMOVE_FINDING'),initial=initial(),auto_id='finding_remove_%s'),
        amend_form=ClinicalReasonForm(bound('BEGIN_AMEND'),initial=initial(),auto_id='clinical_amend_%s'),
        discard_form=ClinicalReasonForm(bound('DISCARD'),initial=initial(),auto_id='clinical_discard_%s'))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def workspace(request,pk):
    get_object_or_404(Visit,pk=pk)
    details=encounter_details(request.user,pk,revision=request.GET.get('revision'))
    if request.method=='POST':
        if request.GET.get('revision') is not None:raise PermissionDenied('历史版本仅供查阅，请返回当前检查草稿办理。')
        check_patient_form(request.user,details['visit'],request.POST.get('patient_binding',''))
    action=request.POST.get('action') if request.method=='POST' else None
    resumed=request.method=='POST' and request.POST.get('review_current')=='yes'
    post_data=None
    if resumed:
        if action not in ('NOTES','ADD_FINDING') or not details['can_edit']:
            raise PermissionDenied('请从当前可编辑的检查草稿核对已保存内容。')
        post_data=request.POST.copy();post_data.update(expected_revision=details['encounter'].revision,operation_id=str(uuid.uuid4()))
        messages.info(request,'已载入当前草稿版本号，本页填写仍未提交。请比较已保存内容后再明确保存。')
    forms=entry_forms(request,details,action,post_data);status=200;rebase_available=False
    by_action={'START':'start_form','NOTES':'notes_form','ADD_FINDING':'finding_form','REMOVE_FINDING':'remove_form','BEGIN_AMEND':'amend_form','DISCARD':'discard_form'}
    if request.method=='POST' and not resumed:
        if action not in by_action:raise PermissionDenied('未知检查记录操作。')
        form=forms[by_action[action]]
        if form.is_valid():
            data=form.fields_data() if action in ('NOTES','ADD_FINDING') else dict(form.cleaned_data)
            data.pop('confirmed',None)
            data.pop('patient_binding',None)
            try:
                if action=='START':head,replay=cmd.start_encounter(actor=request.user,visit_id=pk,**data)
                else:
                    expected=data.pop('expected_revision');op=data.pop('operation_id')
                    head,replay=cmd.change_draft(actor=request.user,visit_id=pk,expected_revision=expected,operation_id=op,action=action,fields=data)
            except EXPECTED_ERRORS as exc:
                add_error(form,exc);status=409
                details=encounter_details(request.user,pk)
                rebase_available=action in ('NOTES','ADD_FINDING') and details['can_edit'] and expected!=details['encounter'].revision
            else:
                messages.success(request,'该次操作已经保存，已显示当前检查进度。' if replay else {'START':'已开始本次实际检查记录。','BEGIN_AMEND':'更正草稿已建立，原确认版本继续保留。','DISCARD':'草稿已放弃，已确认版本继续保留。'}.get(action,'检查草稿已保存，请完成核对后确认版本。'))
                return redirect('clinical_encounter',pk=pk)
        else:status=400
    quadrants=[{'label':('恒牙' if q<5 else '乳牙')+'第'+str(q if q<5 else q-4)+'象限',
        'kind':'PERMANENT' if q<5 else 'PRIMARY','teeth':[n for n in PERMANENT+PRIMARY if n//10==q]} for q in range(1,9)]
    remove_rows=[]
    for i,row in enumerate(details['findings'],1):
        row=dict(row);row['line_no']=i;row['kind_label']=KINDS.get(row['kind'],row['kind']);row['operation_id']=str(uuid.uuid4());remove_rows.append(row)
    return clinical_render(request,'clinical/encounter_workspace.html',dict(details,**forms,quadrants=quadrants,finding_rows=remove_rows,rebase_available=rebase_available,rebase_action=action,show_saved_comparison=rebase_available or resumed,observed_at_display=datetime.fromisoformat(details['payload']['observed_at']) if details['payload'].get('observed_at') else None),status=status)


@login_required
@never_cache
@require_GET
def record_preview(request,pk):
    details=encounter_details(request.user,pk)
    try:prepared=cmd.prepare_record(actor=request.user,visit_id=pk)
    except EXPECTED_ERRORS as exc:
        form=ClinicalConfirmForm();add_error(form,exc)
        return clinical_render(request,'clinical/record_confirm.html',dict(details,form=form,blocked=True),status=409)
    form=ClinicalConfirmForm(initial={'proposal_token':prepared['proposal_token']})
    return clinical_render(request,'clinical/record_confirm.html',dict(details,form=form,preview_payload=prepared['payload'],preview_history=cmd.visible_history(details['visit'].patient_id,details['visit'].clinic_id).filter(pk=prepared['payload']['history_id']).first() if prepared['payload']['history_id'] else None,preview_observed_at=datetime.fromisoformat(prepared['payload']['observed_at']),blocked=False))


@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def record_confirm(request):
    form=ClinicalConfirmForm(request.POST);details={}
    if form.is_valid():
        try:
            p=read_proposal(request.user,cmd.CONTRACT,('DENTIST',),form.cleaned_data['proposal_token'])
            details=encounter_details(request.user,p['data']['visit'])
            head,replay=cmd.confirm_record(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            messages.success(request,'该次确认已完成，已显示当前检查进度。' if replay else '已确认检查版本；实际治疗、结算与收退款继续按各自流程办理。')
            return redirect('clinical_encounter',pk=head.visit_id)
    render_response=clinical_render if details else render
    return render_response(request,'clinical/record_confirm.html',dict(details,form=form,blocked=True),status=409)


def history_page(request,*,visit=None):
    if visit is None:
        authority=patient_access(request.user,self_only=True);patient=authority.patient;clinic=None
        rows=ClinicalHistoryVersion.objects.filter(patient=patient,source='SELF');base='portal/base.html'
    else:
        require_visit_authority(request.user,visit,'RECORD',always=True)
        patient=visit.patient;clinic=visit.clinic_id
        rows=ClinicalHistoryVersion.objects.filter(patient=patient,scope_clinic_id=clinic);base='base.html'
    latest=rows.order_by('-revision').first();initial=dict(expected_revision=latest.revision if latest else 0,operation_id=uuid.uuid4())
    if visit is not None:
        initial['patient_binding']=patient_form_binding(request.user,visit)
        if request.method=='POST':check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
    if visit is None and latest:
        for name in ('medical_status','medical_history','medication_status','medications','allergy_status','reported_allergies'):initial[name]=getattr(latest,name)
    resumed=request.method=='POST' and request.POST.get('review_current')=='yes'
    data=request.POST.copy() if request.method=='POST' else None
    if resumed:
        data.update(expected_revision=initial['expected_revision'],operation_id=str(uuid.uuid4()),confirmed='')
        messages.info(request,'已载入当前自述版本号，本页填写仍未提交。请核对最新版本并重新确认。')
    form=HistoryForm(data,initial=initial);status=200;rebase_available=False
    if request.method=='POST' and not resumed:
        if form.is_valid():
            data=dict(form.cleaned_data);expected=data.pop('expected_revision');op=data.pop('operation_id');confirmed=data.pop('confirmed');data.pop('patient_binding',None)
            try:row,replay=cmd.submit_history(actor=request.user,fields=data,expected_revision=expected,operation_id=op,confirmed=confirmed,visit_id=visit.pk if visit else None)
            except EXPECTED_ERRORS as exc:
                add_error(form,exc);status=409
                latest=rows.order_by('-revision').first()
                rebase_available=expected!=(latest.revision if latest else 0)
            else:
                messages.success(request,'已核对本次保存结果，未重复新增自述版本。' if replay else '新自述版本已保留，接诊时仍由医师另行核对。')
                return redirect('clinical_encounter' if visit else 'portal_history',**({'pk':visit.pk} if visit else {}))
        else:status=400
    page=Paginator(rows.order_by('-revision'),10).get_page(request.GET.get('page'))
    return clinical_render(request,'clinical/history.html',dict(form=form,patient=patient,visit=visit,page=page,base_template=base,rebase_available=rebase_available,reviewed_current=resumed),status=status)


@login_required(login_url='portal_login')
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def patient_history(request):return history_page(request)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def interview_history(request,pk):
    return history_page(request,visit=get_object_or_404(Visit.objects.select_related('patient'),pk=pk))
