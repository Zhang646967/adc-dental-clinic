from datetime import timedelta
from urllib.parse import urlencode
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Q, Count
from django.http import Http404
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from operations.selectors import allowed_clinics
from operations.cancellation_policy import BANDS, WEEKDAYS, REASONS, FOLLOW_STATES, ACTION_NAMES, ACTION_STATES, ASSESSMENTS
from operations.cancellation_selectors import (local_clinic, cancellation_report, followup_visits,
    improvement_scope, owners)
from operations.cancellation_services import (prepare_followup, confirm_followup, prepare_improvement,
    confirm_improvement, available_actions)
from operations.forms import CancellationFilterForm, FollowUpForm, ImprovementForm, ImprovementStepForm
from operations.models import CancellationFollowUp
from accounts.models import UserAccount
from django.utils.dateparse import parse_datetime

@login_required
@never_cache
@require_GET
def analysis(request):
    today = timezone.localdate()
    form = CancellationFilterForm(request.GET or {'start':today-timedelta(days=28), 'end':today-timedelta(days=1)},
        clinics=allowed_clinics(request.user))
    report = None
    if form.is_valid():
        d = form.cleaned_data
        report = cancellation_report(request.user, d['start'], d['end'], d['clinic_id'], d['weekday'], d['band'])
        if report['clinic_id']:
            common = dict(start=d['start'].isoformat(), end=d['end'].isoformat(), clinic_id=report['clinic_id'])
            for row in report['grid']:
                for c in row['cells']:
                    c['url'] = reverse('cancellation_analysis')+'?'+urlencode(dict(common, weekday=c['weekday'], band=c['band']))
            for c in report['ranking']:
                c['url'] = reverse('cancellation_analysis')+'?'+urlencode(dict(common, weekday=c['weekday'], band=c['band']))
            if request.workspace.role == 'MANAGER':
                report['new_action_url'] = reverse('appointment_improvement_new')+'?'+urlencode(
                    dict(start=d['start'].isoformat(), end=d['end'].isoformat(), weekday=d['weekday'] or today.isoweekday(), band=d['band'] or '08_10'))
    return render(request, 'operations/cancellations.html', dict(form=form, report=report, bands=BANDS),
        status=200 if report is not None else 400)

class WorkFilter(forms.Form):
    state = forms.ChoiceField(label='跟进范围', choices=[('pending','待办理（含未登记）'),('missing','未登记跟进'),('all','全部')], required=False)
    overdue = forms.BooleanField(label='仅看联系逾期', required=False)
    reason = forms.ChoiceField(label='原因分类', choices=[('','全部原因')]+REASONS, required=False)

@login_required
@never_cache
@require_GET
def followups(request):
    form = WorkFilter(request.GET or {'state':'pending'})
    rows = []; page = None; totals = {}
    if form.is_valid():
        with reporting_snapshot():
            qs = followup_visits(request.user); today = timezone.localdate(); d=form.cleaned_data
            totals = qs.aggregate(missing=Count('pk',filter=Q(cancellation_followup__isnull=True)),
                pending=Count('pk',filter=Q(cancellation_followup__state__in=['OPEN','WAITING'])),
                overdue=Count('pk',filter=Q(cancellation_followup__state__in=['OPEN','WAITING'],cancellation_followup__due_on__lt=today)))
            if d['state'] == 'pending': qs=qs.filter(Q(cancellation_followup__isnull=True)|Q(cancellation_followup__state__in=['OPEN','WAITING']))
            if d['state'] == 'missing': qs=qs.filter(cancellation_followup__isnull=True)
            if d['overdue']: qs=qs.filter(cancellation_followup__state__in=['OPEN','WAITING'],cancellation_followup__due_on__lt=today)
            if d['reason'] == 'UNSUPPLIED': qs=qs.filter(Q(cancellation_followup__isnull=True)|Q(cancellation_followup__reason_code='UNSUPPLIED'))
            elif d['reason']: qs=qs.filter(cancellation_followup__reason_code=d['reason'])
            page=Paginator(qs.order_by('cancellation_followup__due_on','scheduled_start','pk'),20).get_page(request.GET.get('page'))
            rows=list(page.object_list)
            active_owners=set(owners(local_clinic(request.user),('FRONT_DESK',)).values_list('pk',flat=True))
            for v in rows:
                f=getattr(v,'cancellation_followup',None)
                v.followup=f;v.owner_available=not f or f.assigned_to_id in active_owners
    return render(request,'operations/followups.html',dict(form=form,rows=rows,page_obj=page,totals=totals,
        page_query=urlencode({k:v for k,v in request.GET.items() if k!='page'})),status=200 if form.is_valid() else 400)

def _summary(clean):
    labels={'reason_code':'核实原因','state':'联系结果','assigned_to':'责任人','due_on':'执行／联系期限',
        'replacement_no':'另约编号','note':'本次办理依据','weekday':'星期','band':'开始时段','baseline_start':'原窗口起日',
        'baseline_end':'原窗口止日','kind':'措施类别','plan':'具体措施及完成标准','review_start':'后续观察起日',
        'review_end':'后续观察止日','assessment':'复核结论'}
    from operations.cancellation_policy import KINDS
    choices={'reason_code':dict(REASONS),'state':dict(FOLLOW_STATES),'weekday':dict(WEEKDAYS),'band':dict(BANDS),
        'kind':dict(KINDS),'assessment':dict(ASSESSMENTS)}
    return [(labels[k],choices.get(k,{}).get(v,v) if v is not None else '不适用') for k,v in clean.items()]

def _metrics_summary(label, snapshot):
    m=snapshot['metrics']
    rate = str(m['cancel_rate'])+'%' if m['cancel_rate'] is not None else '无法计算'
    complete = str(m['completeness'])+'%' if m['completeness'] is not None else '无法计算'
    return [(label+'患者取消',str(m['patient_cancel'])+' / '+str(m['denominator'])+' = '+rate),
        (label+'诊所取消',m['clinic_cancel']),(label+'状态完整率',complete),
        (label+'样本提示',m['sample_note'])]

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def followup(request,pk):
    try: visit=followup_visits(request.user).get(pk=pk)
    except EXPECTED_ERRORS: raise Http404
    row=getattr(visit,'cancellation_followup',None)
    phase=request.POST.get('action','preview')
    if request.method=='POST' and phase=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try: saved,repeated=confirm_followup(actor=request.user,visit_id=pk,**form.cleaned_data)
            except EXPECTED_ERRORS as exc: add_error(form,exc)
            except DatabaseError: return render(request,'business/problem.html',{'problem':'暂不能核实保存结果，请先查看跟进历史，再决定是否重试。'},status=503)
            else:
                messages.success(request,'显示此前已保存的跟进结果。' if repeated else '联系结果已保存，原取消记录保持原样。')
                return redirect('cancellation_followup',pk=pk)
        return render(request,'business/proposal.html',dict(title='核对取消跟进',form=form,recovery_route='cancellation_followups'),status=409)
    if request.method=='POST' and phase!='preview': raise PermissionDenied
    initial=dict(reason_code=row.reason_code if row else 'UNSUPPLIED',state=row.state if row else 'OPEN',
        assigned_to=row.assigned_to_id if row else request.user.pk,due_on=row.due_on if row else timezone.localdate(),
        replacement_no=row.replacement_visit.visit_no if row and row.replacement_visit_id else '',note='')
    form=FollowUpForm(request.POST if request.method=='POST' else None,clinic=visit.clinic_id,initial=initial)
    if request.method=='POST' and form.is_valid():
        try: clean,token=prepare_followup(actor=request.user,visit_id=pk,data=serialize_form(form.cleaned_data))
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        else:
            return render(request,'business/proposal.html',dict(title='核对取消跟进',
                summary=[('预约',visit.visit_no),('原取消原因',visit.cancellation_reason)]+_summary(clean),
                form=ExplicitProposalForm(initial={'proposal_token':token}),button='确认保存联系结果',recovery_route='cancellation_followups'))
    history=list(row.history.select_related('actor').order_by('-pk')[:20]) if row else []
    names=dict(UserAccount.objects.filter(pk__in=[h.snapshot['owner'] for h in history]).values_list('pk','username'))
    for h in history:
        h.reason_label=dict(REASONS).get(h.snapshot['reason_code']);h.state_label=dict(FOLLOW_STATES).get(h.snapshot['state']);h.owner_label=names.get(h.snapshot['owner'],'历史经办账号')
    return render(request,'operations/followup.html',dict(visit=visit,row=row,form=form,history=history))

def serialize_form(data):
    from operations.cancellation_services import serialize
    return serialize(data)

@login_required
@never_cache
@require_GET
def improvements(request):
    state=request.GET.get('state','active')
    if state not in ('active','all',*[k for k,_ in ACTION_STATES]):
        return render(request,'business/problem.html',{'problem':'措施状态筛选无效。'},status=400)
    with reporting_snapshot():
        qs=improvement_scope(request.user)
        if state=='active':qs=qs.exclude(state__in=['CLOSED','CANCELLED'])
        elif state!='all':qs=qs.filter(state=state)
        page=Paginator(qs.order_by('state','due_on','pk'),20).get_page(request.GET.get('page'))
        rows=list(page.object_list)
        active_owners=set(owners(local_clinic(request.user)).values_list('pk',flat=True))
        for row in rows:
            row.day_label=dict(WEEKDAYS)[row.weekday]
            row.owner_available=row.assigned_to_id in active_owners
    return render(request,'operations/improvements.html',dict(rows=rows,page_obj=page,today=timezone.localdate(),
        state=state,states=ACTION_STATES,page_query=urlencode({'state':state})))

@login_required
@never_cache
@require_GET
def improvement_detail(request,pk):
    try: row=improvement_scope(request.user).get(pk=pk)
    except EXPECTED_ERRORS: raise Http404
    history=list(row.history.select_related('actor').order_by('-pk')[:30])
    names=dict(UserAccount.objects.filter(pk__in=[h.snapshot['owner'] for h in history]).values_list('pk','username'))
    for h in history:
        h.label=dict(ACTION_NAMES).get(h.action,h.action);h.owner_label=names.get(h.snapshot['owner'],'历史经办账号')
    return render(request,'operations/improvement_detail.html',dict(row=row,history=history,actions=available_actions(request.user,row),
        day_label=dict(WEEKDAYS)[row.weekday],baseline=row.baseline['metrics'],
        comparison=row.comparison.get('metrics'),assessment=dict(ASSESSMENTS).get(row.assessment,'尚未复核'),
        baseline_asof=parse_datetime(row.baseline['as_of']),comparison_asof=parse_datetime(row.comparison['as_of']) if row.comparison else None))

def _improvement_edit(request,pk=None,action='CREATE'):
    clinic=local_clinic(request.user)
    row=improvement_scope(request.user).get(pk=pk) if pk else None
    if action not in dict(ACTION_NAMES) or (pk is not None and action=='CREATE'): raise Http404
    title=dict(ACTION_NAMES)[action];phase=request.POST.get('action','preview')
    if request.method=='POST' and phase=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try: result,repeated=confirm_improvement(actor=request.user,pk=pk,action=action,**form.cleaned_data)
            except EXPECTED_ERRORS as exc: add_error(form,exc)
            except DatabaseError: return render(request,'business/problem.html',{'problem':'暂不能核实措施保存结果，请先查看办理历史。'},status=503)
            else:
                messages.success(request,'显示此前保存的措施结果。' if repeated else '措施办理已保存。')
                return redirect('appointment_improvement_detail',pk=result.pk)
        return render(request,'business/proposal.html',dict(title=title,form=form,recovery_route='appointment_improvements'),status=409)
    if request.method=='POST' and phase!='preview': raise PermissionDenied
    today=timezone.localdate()
    initial=dict(weekday=request.GET.get('weekday',today.isoweekday()),band=request.GET.get('band','08_10'),
        baseline_start=request.GET.get('start',today-timedelta(days=28)),baseline_end=request.GET.get('end',today-timedelta(days=1)),
        assigned_to=row.assigned_to_id if row else request.user.pk,due_on=row.due_on if row else today+timedelta(days=28))
    form=ImprovementForm(request.POST if request.method=='POST' else None,clinic=clinic,initial=initial) if action=='CREATE' else ImprovementStepForm(
        request.POST if request.method=='POST' else None,clinic=clinic,action=action,baseline_end=row.baseline_end,initial=initial)
    if request.method=='POST' and form.is_valid():
        try: clean,token,payload=prepare_improvement(actor=request.user,action=action,pk=pk,fields=serialize_form(form.cleaned_data))
        except EXPECTED_ERRORS as exc: add_error(form,exc)
        else:
            summary=_summary(clean)
            if row: summary=[('当前状态',row.get_state_display()),('当前责任人',row.assigned_to.username)]+summary
            if 'baseline' in payload: summary+=_metrics_summary('原窗口',payload['baseline'])
            if 'comparison' in payload: summary+=_metrics_summary('原窗口',row.baseline)+_metrics_summary('后续窗口',payload['comparison'])
            return render(request,'business/proposal.html',dict(title=title,summary=summary,form=ExplicitProposalForm(initial={'proposal_token':token}),
                button='确认措施办理',recovery_route='appointment_improvements'))
    return render(request,'operations/improvement_edit.html',dict(row=row,title=title,form=form))

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def improvement_new(request): return _improvement_edit(request)

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def improvement_step(request,pk,action):
    try: return _improvement_edit(request,pk,action.upper())
    except EXPECTED_ERRORS: raise Http404
