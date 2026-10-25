from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_http_methods
from adc_core.proposals import workspace_binding
from finance.fund_models import FundTransfer
from finance.reconciliation_models import StatementLine
from finance.reconciliation_views import mutation
from finance import fund_services as services


class BasisForm(forms.Form):
    basis=forms.CharField(label='基金用途与银行证据核对依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}),
        help_text='仅使用合成流水；请核对基金到账或退回用途，不能把患者现金流水重复作为基金凭据。')


class ReviewForm(forms.Form):
    decision=forms.ChoiceField(label='独立复核决定',choices=[('approve','银行证据核对通过'),('reject','未通过，释放本次用途')])
    reason=forms.CharField(label='独立核对依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))


def _read(actor):
    workspace_binding(actor,('FINANCE',))


def _rows():
    return FundTransfer.objects.select_related('line__account__clinic','prepared_by','reviewed_by')


@login_required
@never_cache
@require_GET
def listing(request):
    _read(request.user)
    page=Paginator(_rows().order_by('-pk'),20).get_page(request.GET.get('page','1'))
    return render(request,'finance/fund_list.html',dict(page_obj=page,rows=list(page.object_list)))


@login_required
@never_cache
@require_GET
def detail(request,pk):
    _read(request.user)
    row=get_object_or_404(_rows(),pk=pk)
    from finance.allocation_projection import transfer_funds
    return render(request,'finance/fund_detail.html',dict(row=row, funds=transfer_funds(row),
        allocations=row.allocations.select_related('prepared_by').order_by('-pk'),
        can_review=row.state=='PENDING' and row.prepared_by_id!=request.user.pk))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def create(request,pk):
    _read(request.user)
    line=get_object_or_404(StatementLine.objects.select_related('account__clinic','batch'),pk=pk)
    kind='RECEIPT' if line.direction=='IN' else 'RETURN'
    form=BasisForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None)
    return mutation(request,title='核对基金银行到账' if kind=='RECEIPT' else '核对基金银行退回',form=form,
        prepare=lambda **v:services.prepare_transfer(actor=request.user,line_id=pk,kind=kind,**v),
        confirm=lambda **v:services.confirm_transfer(actor=request.user,expected_line_id=pk,**v),
        summary=lambda p:[('诊所',line.account.clinic.name),('账户',line.account.code),('流水编号',line.transaction_id),
            ('方向',line.get_direction_display()),('到账／退回日期',line.booked_on),('金额',line.amount),('币种',line.currency),
            ('用途依据',p['data']['basis']),('提交后','保留流水用途，待另一财务账号核对；申报分配另行办理，不生成患者现金或新增收入')],
        destination=lambda row:redirect('fund_transfer_detail',pk=row.pk),recovery='fund_transfers',context=dict(fund_line=line))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def review(request,pk):
    _read(request.user)
    row=get_object_or_404(_rows(),pk=pk)
    form=ReviewForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None)
    return mutation(request,title='独立复核基金银行证据',form=form,
        prepare=lambda **v:services.prepare_transfer_review(actor=request.user,transfer_id=pk,**v),
        confirm=lambda **v:services.confirm_transfer_review(actor=request.user,expected_transfer_id=pk,**v),
        summary=lambda p:[('用途',row.get_kind_display()),('原流水',row.line.transaction_id),('原金额',row.line.amount),
            ('提交依据',row.basis),('决定','银行证据核对通过' if p['data']['decision']=='approve' else '未通过，释放本次用途'),
            ('复核依据',p['data']['reason']),('资金边界','保留银行事实；不自动核销申报、不生成患者收退款')],
        destination=lambda result:redirect('fund_transfer_detail',pk=result.pk),recovery='fund_transfers',context=dict(fund_line=row.line))
