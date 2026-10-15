from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import get_object_or_404,render,redirect
from django.utils import timezone
from django.views.decorators.http import require_GET,require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from accounts.policies import clinic_ids
from adc_core.http_support import EXPECTED_ERRORS,add_error
from care.models import Invoice
from equipment.models import EquipmentEvent
from equipment.policies import manager_clinic
from equipment.costs import effective_cost
from equipment.forms import ExplicitProposalForm
from finance.cash_forms import CashRequestForm,ExpenseRequestForm,CashReviewForm
from finance.cash_selectors import cash_listing,cash_detail
from finance.cash_selectors import invoice_balance,event_net
from adc_core.snapshots import reporting_snapshot
from finance.cash_selectors import receivables as receivables_read
from finance.cash_services import prepare_cash,confirm_cash_request,prepare_review,confirm_cash_review

@login_required
@require_GET
def receivables(request):
    try:data=receivables_read(request.user,request.GET.get('state',''),request.GET.get('page','1'))
    except EXPECTED_ERRORS:
        return render(request,'business/problem.html',{'problem':'应收筛选无效，请重新查询。'},status=400)
    return render(request,'finance/receivables.html',data)

@login_required
@require_GET
def listing(request):
    try:data=cash_listing(request.user,request.GET.get('state',''),request.GET.get('page','1'),
        kind=request.GET.get('kind',''),invoice=request.GET.get('invoice',''),event=request.GET.get('event',''))
    except EXPECTED_ERRORS:
        return render(request,'business/problem.html',{'problem':'记账筛选无效，请重新查询。'},status=400)
    return render(request,'finance/cash_list.html',data)

@login_required
@require_GET
def detail(request,pk):
    try:data=cash_detail(request.user,pk)
    except EXPECTED_ERRORS:raise Http404
    return render(request,'finance/cash_detail.html',data)

def _request(request,source_type,pk,reversal_id=None):
    with reporting_snapshot():
        if source_type=='invoice':
            source=get_object_or_404(Invoice.objects.select_related('visit__clinic','current_record_version'),pk=pk,visit__clinic_id__in=clinic_ids(request.user))
            balance=invoice_balance(source)
        else:
            clinic=manager_clinic(request.user)
            source=get_object_or_404(EquipmentEvent.objects.select_related('asset__clinic'),pk=pk,asset__clinic_id=clinic)
            balance=dict(known_cost=effective_cost(source)[0],net_equipment_expense=event_net(source.pk),pending=source.cash_entries.filter(state='PENDING').count())
    action=request.POST.get('action','preview')
    title='申请冲回误记条目' if reversal_id else '申请模拟收款／退款' if source_type=='invoice' else '申请设备费用记账'
    if request.method=='POST' and action=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                entry,repeated=confirm_cash_request(actor=request.user,**form.cleaned_data,
                    expected_source_type=source_type,expected_source_id=pk,expected_reversal_id=reversal_id)
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            except DatabaseError:
                return render(request,'business/problem.html',{'problem':'暂不能核实申请结果，请先查阅记账申请清单；不要推断已付款或反复创建。'},status=503)
            else:
                messages.success(request,'此前已提交，返回当前审核状态。' if repeated else '申请已提交；待独立财务审核，不计入实收或已付。')
                return redirect('cash_detail',pk=entry.pk)
        return render(request,'business/proposal.html',{'title':title,'form':form,'button':'确认提交待审核申请','recovery_route':'cash_list'},status=409)
    if request.method=='POST' and action!='preview':raise PermissionDenied
    klass=ExpenseRequestForm if source_type=='equipment' or reversal_id else CashRequestForm
    initial={'occurred_on':timezone.localdate()}
    if source_type=='invoice' and reversal_id is None:
        initial.update(kind='REFUND' if balance['refund_due'] else 'RECEIPT',
            amount=balance['refund_due'] or balance['remaining'] or None)
    form=klass(request.POST if request.method=='POST' else None,initial=initial)
    if request.method=='POST' and form.is_valid():
        values=dict(form.cleaned_data)
        values.setdefault('kind','EQUIPMENT_EXPENSE' if source_type=='equipment' else 'REFUND')
        try:preview=prepare_cash(actor=request.user,source_type=source_type,source_id=pk,reversal_id=reversal_id,**values)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            summary=[('类型',{'RECEIPT':'模拟收款','REFUND':'模拟退款','EQUIPMENT_EXPENSE':'设备费用','EXPENSE_REVERSAL':'设备费用冲回'}[preview['kind']]),
                ('来源',preview['source'].invoice_no if source_type=='invoice' else preview['source'].asset.asset_code),
                ('金额（CNY）',preview['amount']),('事实日期',preview['occurred_on']),('核对依据',preview['reason']),
                ('提交后状态','待财务审核；尚未记账')]
            summary.extend(_balance_summary(preview['balance'],preview['projected'],source_type))
            return render(request,'business/proposal.html',{'title':title,'summary':summary,'form':ExplicitProposalForm(initial={'proposal_token':preview['proposal_token']}),'button':'确认提交待审核申请','recovery_route':'cash_list'})
    return render(request,'finance/cash_request.html',dict(source=source,source_type=source_type,title=title,form=form,balance=balance))

def _balance_summary(balance,projected,source_type):
    if source_type=='invoice':
        return [('当前账单版本',balance['current_revision']),('当前开单金额（CNY）',balance['billed']),
            ('当前已审核净收款（CNY）',balance['net_received']),('待审核收款金额（未计入现金）',balance['pending_receipts']),
            ('待审核退款金额（未计入现金）',balance['pending_refunds']),
            ('本条单独获批后净收款（CNY）',projected['net_received']),('本条单独获批后待收（CNY）',projected['remaining']),
            ('本条单独获批后待退（CNY）',projected['refund_due'])]
    return [('当前核对费用（CNY）',balance['known_cost']),('当前已审核净费用（CNY）',balance['net_equipment_expense']),
            ('本条单独获批后净费用（CNY）',projected['net_equipment_expense'])]

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def invoice_request(request,pk):return _request(request,'invoice',pk)

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def expense_request(request,pk):return _request(request,'equipment',pk)

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def reversal(request,pk):
    try:entry=cash_detail(request.user,pk)['entry']
    except EXPECTED_ERRORS:raise Http404
    if request.workspace.role not in ('FRONT_DESK','MANAGER'):raise PermissionDenied
    return _request(request,'invoice' if entry.invoice_id else 'equipment',entry.invoice_id or entry.equipment_event_id,pk)

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def review(request,pk):
    try:data=cash_detail(request.user,pk)
    except EXPECTED_ERRORS:raise Http404
    action=request.POST.get('action','preview')
    title='独立财务审核'
    if request.method=='POST' and action=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:entry,repeated=confirm_cash_review(actor=request.user,**form.cleaned_data,expected_entry_id=pk)
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            except DatabaseError:
                return render(request,'business/problem.html',{'problem':'审核结果暂时不能核实，请先打开条目查看当前状态；不要重复记账。'},status=503)
            else:
                messages.success(request,'此前已审核，返回当前状态。' if repeated else '独立财务审核已保存。')
                return redirect('cash_detail',pk=entry.pk)
        return render(request,'business/proposal.html',{'title':title,'form':form,'button':'确认独立审核决定','recovery_route':'cash_list'},status=409)
    if request.method=='POST' and action!='preview':raise PermissionDenied
    form=CashReviewForm(request.POST if request.method=='POST' else None)
    if data['approval_blocker']:form.fields['decision'].choices=[('reject','拒绝失效申请并保留历史')]
    if request.method=='POST' and form.is_valid():
        try:p=prepare_review(actor=request.user,entry_id=pk,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            summary=[('申请编号',pk),('类型',p['entry'].get_kind_display()),('金额（CNY）',p['entry'].amount),
                ('诊所',p['entry'].clinic.name),('事实日期',p['entry'].occurred_on),
                ('来源',p['source'].invoice_no if p['source_type']=='invoice' else p['source'].asset.asset_code),
                ('申请人',p['entry'].prepared_by.username),('决定','核实并记账' if p['decision']=='approve' else '拒绝'),
                ('独立审核说明',p['reason'])]
            if p['decision']=='approve':
                summary.extend(_balance_summary(p['balance'],p['projected'],p['source_type']))
            elif p['source_type']=='invoice':
                summary.extend([('当前账单版本',p['balance']['current_revision']),('当前开单金额（CNY）',p['balance']['billed']),
                    ('已审核净收款（CNY）',p['balance']['net_received'])])
            else:
                summary.extend([('当前核对费用（CNY）',p['balance']['known_cost']),
                                ('该事件已审核净费用（CNY）',p['balance']['net_equipment_expense'])])
            if p['decision']=='reject':summary.append(('余额影响','拒绝保留原申请；当前现金与余额保持'))
            return render(request,'business/proposal.html',{'title':title,'summary':summary,'form':ExplicitProposalForm(initial={'proposal_token':p['proposal_token']}),'button':'确认独立审核决定','recovery_route':'cash_list'})
    return render(request,'finance/cash_review.html',dict(data,form=form))
