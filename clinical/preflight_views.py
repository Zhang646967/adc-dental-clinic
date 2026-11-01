from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect,get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import read_proposal
from clinical import preflight,executions
from clinical.authority import require_reviewer,professional_scope,visit_service_id
from clinical.encounter_views import clinical_render
from clinical.encounter_selectors import encounter_details
from clinical.form_binding import patient_form_binding,check_patient_form
from clinical.preflight_forms import PreflightForm,RetrospectiveForm,ClinicalRuleForm,GapReviewForm
from clinical.plan_forms import ConfirmPlanActionForm,current_steps
from clinical.preflight_models import ClinicalConsentRule,TreatmentPreflight,ProcedureGap
from clinical.models import ClinicalReviewerAppointment
from workspaces.context import require_active


def preview(request,prepared,back,title,description):
    return clinical_render(request,'clinical/preflight_confirm.html',dict(form=ConfirmPlanActionForm(initial={'proposal_token':prepared['proposal_token']}),
        back=back,title=title,description=description,preview=prepared.get('data',{})))


def confirm(request,contract,expected,handler,back,title):
    form=ConfirmPlanActionForm(request.POST)
    if form.is_valid():
        try:
            d=read_proposal(request.user,contract,('DENTIST',),form.cleaned_data['proposal_token'])['data']
            if any(d.get(k)!=v for k,v in expected.items()):raise PermissionDenied('请在原就诊或原事项页确认。')
            row,replay=handler(actor=request.user,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:messages.success(request,title+'已保留。');return redirect(back)
    return clinical_render(request,'clinical/preflight_confirm.html',dict(form=form,back=back,title=title),status=409)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def workspace(request,pk,retrospective=False):
    d=encounter_details(request.user,pk);visit=d['visit'];kind='clinical_retrospective' if retrospective else 'clinical_preflight'
    back=reverse(kind,kwargs={'pk':pk});title='已发生治疗的真实补记' if retrospective else '治疗前核对'
    if request.method=='POST' and request.POST.get('phase')=='confirm':
        return confirm(request,executions.RETRO_CONTRACT if retrospective else preflight.CONTRACT,{'visit':pk},
            executions.confirm_retrospective if retrospective else preflight.confirm,back,title)
    initial=dict(patient_binding=patient_form_binding(request.user,visit),quantity='1',progress='COMPLETE',charge_mode='CHARGE')
    if request.GET.get('step'):
        step=get_object_or_404(current_steps(visit,request.user),pk=request.GET['step'])
        initial.update(step_version=step.pk,treatment_type=step.treatment_type_id,tooth=step.tooth,surfaces=list(step.surface),quantity=str(step.estimated_quantity))
    form=(RetrospectiveForm if retrospective else PreflightForm)(request.POST or None,visit=visit,actor=request.user,initial=initial)
    status=200
    if request.method=='POST':
        check_patient_form(request.user,visit,request.POST.get('patient_binding',''))
        if form.is_valid():
            try:
                p=executions.prepare_retrospective(actor=request.user,visit_id=pk,fields=form.fields_data(),gap_reason=form.cleaned_data['gap_reason']) if retrospective else preflight.prepare(
                    actor=request.user,visit_id=pk,fields=form.fields_data(),communication=form.cleaned_data['communication'])
            except EXPECTED_ERRORS as exc:add_error(form,exc);status=409
            else:return preview(request,p,back,title,'保留真实治疗及资料缺口，交另一名审核医师复核；不补造事前核对。' if retrospective else '核对不会生成治疗或费用；实际完成后仍需单独登记。')
        else:status=400
    return clinical_render(request,'clinical/preflight.html',dict(d,form=form,title=title,retrospective=retrospective,
        checks=TreatmentPreflight.objects.filter(visit=visit).order_by('-pk'),back=back,controls_enabled=preflight.enabled(visit.clinic_id)),status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def rules(request):
    require_active(request.user,('DENTIST',));now=timezone.now()
    clinics=ClinicalReviewerAppointment.objects.filter(user=request.user,is_active=True,valid_from__lte=now,valid_until__gt=now).values('clinic_id')
    if not clinics.exists():raise PermissionDenied('需要当前有效的本店专业审核职责。')
    back=reverse('clinical_control_rules')
    if request.method=='POST' and request.POST.get('phase')=='confirm':return confirm(request,preflight.RULE_CONTRACT,{},preflight.confirm_rule,back,'规则／启用办理')
    form=ClinicalRuleForm(request.POST or None,actor=request.user)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:p=preflight.prepare_rule(actor=request.user,clinic_id=d['clinic'].pk,treatment_id=d['treatment_type'].pk if d['treatment_type'] else None,
            mode=d['mode'],reference=d['reference'],explanation=d['explanation'],activate=d['activate'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,p,back,'核对临床规则或启用','新版本保留旧规则；未知要求不能自动当作无需同意。')
    return clinical_render(request,'clinical/control_rules.html',dict(form=form,rows=ClinicalConsentRule.objects.filter(clinic_id__in=clinics).select_related('clinic','treatment_type').order_by('clinic_id','treatment_type_id','-number'),back=back))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def gaps(request,pk=None):
    require_active(request.user,('DENTIST',));now=timezone.now()
    clinics=ClinicalReviewerAppointment.objects.filter(user=request.user,is_active=True,valid_from__lte=now,valid_until__gt=now).values('clinic_id')
    if not clinics.exists():raise PermissionDenied('需要当前有效的本店独立专业复核职责。')
    from clinical.plan_locks import readable_services
    rows=ProcedureGap.objects.filter(performed__encounter__visit__clinic_id__in=clinics).select_related('performed__encounter__visit','performed__step_version')
    # Review appointment does not replace professional sensitive-read scope.
    rows=[r for r in rows.order_by('state','pk') if (r.performed.step_version.service_id if r.performed.step_version_id else visit_service_id(r.performed.encounter.visit)) in readable_services(request.user,r.performed.encounter.visit.clinic_id)]
    selected=next((r for r in rows if r.pk==pk),None) if pk else None
    if pk and selected is None:raise PermissionDenied('当前没有本项缺口的复核与查阅范围。')
    back=reverse('clinical_gap_detail',kwargs={'pk':pk}) if pk else reverse('clinical_gaps')
    if request.method=='POST' and request.POST.get('phase')=='confirm':return confirm(request,preflight.REVIEW_CONTRACT,{'gap':pk},preflight.confirm_review,back,'历史缺口复核')
    form=GapReviewForm(request.POST or None)
    if request.method=='POST' and selected and form.is_valid():
        try:p=preflight.prepare_review(actor=request.user,gap_id=pk,note_text=form.cleaned_data['note_text'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return preview(request,p,back,'复核历史缺口','核对真实事实与后续安排；复核不把历史缺口改成事前已通过。')
    return clinical_render(request,'clinical/gaps.html',dict(rows=rows,selected=selected,form=form,back=back))
