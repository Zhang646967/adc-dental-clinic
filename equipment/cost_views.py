from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import render,redirect
from django.views.decorators.http import require_GET,require_http_methods
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from equipment.models import EquipmentCostAmendment
from equipment.costs import (cost_history,scoped_events,prepare_cost,confirm_cost,
    prepare_cost_review,confirm_cost_review,cost_blocker,cost_id)
from equipment.policies import manager_clinic
from finance.cash_forms import CashReviewForm

class CostForm(forms.Form):
    proposed_cost=forms.DecimalField(label='核实后的整笔事件费用（CNY）',min_value=0,max_digits=16,decimal_places=2,
        help_text='填写总额，不是差额。0表示明确零费用；不填未知费用。')
    reason=forms.CharField(label='原始凭据与更正依据（合成案例，不含患者资料）',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

@login_required
@never_cache
@require_GET
def history(request,pk):
    try:data=cost_history(request.user,pk,request.GET.get('page','1'))
    except EXPECTED_ERRORS:raise Http404
    return render(request,'equipment/cost_history.html',data)

@login_required
@never_cache
@require_GET
def queue(request):
    with reporting_snapshot():
        events=scoped_events(request.user)
        rows=EquipmentCostAmendment.objects.filter(event__in=events,state='PENDING').select_related('event__asset__clinic','prepared_by').order_by('prepared_at','pk')
        page=Paginator(rows,20).get_page(request.GET.get('page','1'))
        data=dict(amendments=list(page.object_list),page_obj=page)
    return render(request,'equipment/cost_queue.html',data)

def _summary(event,old,new):
    return [('来源诊所',event.asset.clinic.name),('设备',event.asset.asset_code),('来源事件',f'#{event.pk} · {event.get_kind_display()}'),
        ('原始登记费用','未登记' if event.cost is None else event.cost),('申请所依据费用','未登记' if old is None else old),
        ('拟核实整笔费用（CNY）',new),('操作影响','只更新费用核对依据；保留原始记录；不会自动记账或改变设备、预约、排班')]

def _edit(request,pk,review=False):
    if review:
        row=EquipmentCostAmendment.objects.select_related('event__asset__clinic','prepared_by').get(pk=cost_id(pk))
        event=row.event;title='独立审核设备费用补正'
    else:
        manager_clinic(request.user)
        data=cost_history(request.user,pk);event=data['event'];title='申请设备费用补录／更正'
    action=request.POST.get('action','preview')
    if request.method=='POST' and action=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                result,repeated=(confirm_cost_review(actor=request.user,expected_amendment_id=pk,**form.cleaned_data) if review else
                    confirm_cost(actor=request.user,expected_event_id=pk,**form.cleaned_data))
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            except DatabaseError:
                return render(request,'business/problem.html',{'problem':'暂不能核实结果，请先查看来源费用历史；不要重复申请或推断已经记账。'},status=503)
            else:
                messages.success(request,'此前已保存，显示当前历史。' if repeated else '费用补正记录已保存；现金与设备状态未自动变动。')
                return redirect('equipment_cost_history',pk=result.event_id)
        return render(request,'business/proposal.html',dict(title=title,form=form,button='确认保存费用补正',recovery_route='equipment_cost_queue'),status=409)
    if request.method=='POST' and action!='preview':raise PermissionDenied('未知费用操作。')
    blocker=cost_blocker(row) if review else ''
    form=(CashReviewForm if review else CostForm)(request.POST if request.method=='POST' else None)
    if review:
        form.fields['decision'].choices=[('approve','核实费用依据（不会记账）'),('reject','拒绝并保留原申请')]
        if blocker:form.fields['decision'].choices=[('reject','拒绝失效申请并保留历史')]
    if request.method=='POST' and form.is_valid():
        try:
            preview=(prepare_cost_review(actor=request.user,amendment_id=pk,**form.cleaned_data) if review else
                prepare_cost(actor=request.user,event_id=pk,**form.cleaned_data))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            old=row.previous_cost if review else preview['previous_cost'];new=row.proposed_cost if review else preview['proposed_cost']
            summary=_summary(event,old,new)+[('申请人',row.prepared_by.username if review else request.user.username),
                ('原始凭据与更正依据',row.reason if review else preview['reason'])]
            if review:summary.extend([('审核决定','核实费用依据' if preview['decision']=='approve' else '拒绝；当前费用依据保持'),('独立审核说明',preview['reason'])])
            return render(request,'business/proposal.html',dict(title=title,summary=summary,
                form=ExplicitProposalForm(initial={'proposal_token':preview['proposal_token']}),button='确认保存费用补正',recovery_route='equipment_cost_queue'))
    return render(request,'equipment/cost_edit.html',dict(title=title,event=event,amendment=row if review else None,form=form,blocker=blocker))

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def request_cost(request,pk):
    try:return _edit(request,pk)
    except EXPECTED_ERRORS:raise Http404

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def review_cost(request,pk):
    try:return _edit(request,pk,review=True)
    except EXPECTED_ERRORS:raise Http404
