from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Exists, OuterRef
from django.http import Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from finance.cash_selectors import cash_scope
from finance.reconciliation_models import PaymentAccount, CashEvidenceVersion, StatementBatch, ReconciliationMatch, METHODS
from registry.models import Clinic
from finance.evidence_policies import reconciliation_scope
from finance.reconciliation_forms import AccountForm,AccountStateForm,EvidenceForm,ImportForm,MatchForm,EvidenceReviewForm,MatchReviewForm
from finance.payment_account_services import prepare_account,confirm_account
from finance.cash_evidence_services import prepare_evidence,confirm_evidence,prepare_evidence_review,confirm_evidence_review
from finance.statement_services import prepare_import,confirm_import
from finance.reconciliation_services import prepare_match,confirm_match,prepare_match_review,confirm_match_review,ACTIVE
from finance.reconciliation_selectors import dashboard,line_scope,match_scope,candidates
from finance.fund_models import StatementUse

def proposal_page(request,title,summary,token,recovery,*,status=200,form=None):
    return render(request,'business/proposal.html',dict(title=title,summary=summary,
        form=form or ExplicitProposalForm(initial={'proposal_token':token}),button='明确确认并保存',recovery_route=recovery),status=status)

def mutation(request,*,title,form,prepare,confirm,summary,destination,recovery,context=None):
    """Common HTTP form flow; each command still owns its authorization and locks."""
    context=context or {};action=request.POST.get('action','preview')
    if request.method=='POST' and action=='confirm':
        bound=ExplicitProposalForm(request.POST)
        if bound.is_valid():
            try:row,repeated=confirm(**bound.cleaned_data)
            except EXPECTED_ERRORS as exc:add_error(bound,exc)
            except DatabaseError:return render(request,'business/problem.html',{'problem':'暂不能确认保存结果，请先查阅当前记录，不要推断已记账或重复提交。'},status=503)
            else:
                messages.success(request,'此前已保存，显示当前结果。' if repeated else '已保存，原有账单与现金金额保持。')
                return destination(row)
        return proposal_page(request,title,[],None,recovery,status=409,form=bound)
    if request.method=='POST' and action!='preview':raise PermissionDenied
    if request.method=='POST' and form.is_valid():
        try:p=prepare(**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return proposal_page(request,title,summary(p),p['proposal_token'],recovery)
    return render(request,'finance/reconciliation_edit.html',dict(context,title=title,form=form,recovery=recovery))

@login_required
@never_cache
@require_GET
def accounts(request):
    rows=PaymentAccount.objects.select_related('clinic').order_by('clinic__clinic_code','code')
    clinic=reconciliation_scope(request.user)
    if clinic is not None:rows=rows.filter(clinic_id=clinic)
    return render(request,'finance/payment_accounts.html',{'page':Paginator(rows,20).get_page(request.GET.get('page','1'))})

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def account_edit(request,pk=None):
    reconciliation_scope(request.user)
    if request.workspace.role!='FINANCE':raise PermissionDenied
    row=get_object_or_404(PaymentAccount,pk=pk) if pk else None
    form=(AccountStateForm if row else AccountForm)(request.POST if request.method=='POST' and request.POST.get('action','preview')=='preview' else None)
    return mutation(request,title='启用／停用渠道账户' if row else '建立合成渠道账户',form=form,
        prepare=lambda **v:prepare_account(actor=request.user,account_id=pk,**v),
        confirm=lambda **v:confirm_account(actor=request.user,expected_account_id=pk,**v),
        summary=lambda p:([('渠道账户',row.code),('新状态','启用' if p['data']['active'] else '停用')] if row else
            [('诊所',Clinic.objects.get(pk=p['data']['clinic']).name),('渠道账户代码',p['data']['code']),('收付款方式',dict(METHODS)[p['data']['method']])])+
            [('影响','账户身份与历史保留；停用阻止新的渠道使用')],
        destination=lambda r:redirect('payment_accounts'),recovery='payment_accounts')

@login_required
@never_cache
@require_GET
def home(request):
    return render(request,'finance/reconciliation_home.html',dashboard(request.user,request.GET.get('page','1')))

@login_required
@require_GET
def template(request):
    from equipment.policies import manager_clinic
    manager_clinic(request.user)
    response=HttpResponse('transaction_id,booked_on,direction,amount,currency,reference\nSYNTH-001,2026-10-15,IN,100.00,CNY,SYNTH-RECEIPT-001\n',content_type='text/csv; charset=utf-8')
    response['Content-Disposition']='attachment; filename="adc-synthetic-statement-v1.csv"'
    return response

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def import_statement(request):
    from equipment.policies import manager_clinic
    manager_clinic(request.user)
    if request.method=='POST' and request.POST.get('action')=='confirm':
        return mutation(request,title='确认接受合成流水',form=ExplicitProposalForm(),prepare=None,summary=None,
            confirm=lambda **v:confirm_import(actor=request.user,**v),destination=lambda r:redirect('statement_batch',pk=r.pk),recovery='reconciliation_home')
    if request.method=='POST' and request.POST.get('action','preview')!='preview':raise PermissionDenied
    form=ImportForm(request.POST if request.method=='POST' else None,request.FILES if request.method=='POST' else None,actor=request.user)
    if request.method=='POST' and form.is_valid():
        from finance.statement_csv import MAX_BYTES
        try:p=prepare_import(actor=request.user,payment_account_id=form.cleaned_data['payment_account_id'],source_bytes=form.cleaned_data['source'].read(MAX_BYTES+1))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        except DatabaseError:return render(request,'business/problem.html',{'problem':'无法保存导入草稿，请核对批次记录。'},status=503)
        else:return render(request,'finance/statement_preview.html',dict(p,form=ExplicitProposalForm(initial={'proposal_token':p['proposal_token']})))
    return render(request,'finance/reconciliation_edit.html',dict(title='上传并预览合成流水',form=form,upload=True,recovery='reconciliation_home'))

@login_required
@never_cache
@require_GET
def batch_detail(request,pk):
    clinic=reconciliation_scope(request.user)
    qs=StatementBatch.objects.select_related('account__clinic','created_by')
    if clinic is not None:qs=qs.filter(account__clinic_id=clinic)
    batch=get_object_or_404(qs,pk=pk)
    uses=StatementUse.objects.filter(line_id=OuterRef('pk'),state='ACTIVE')
    rows=batch.lines.annotate(active=Exists(uses),fund_used=Exists(uses.filter(fund_transfer__isnull=False))).order_by('pk')
    if request.GET.get('unmatched')=='1':rows=rows.filter(active=False)
    return render(request,'finance/statement_batch.html',dict(batch=batch,page=Paginator(rows,20).get_page(request.GET.get('page','1')),unmatched=request.GET.get('unmatched')=='1'))

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def match_line(request,pk):
    with reporting_snapshot():
        line=get_object_or_404(line_scope(request.user),pk=pk)
        choices=candidates(request.user,line)
        history=list(match_scope(request.user).filter(line=line).order_by('-pk'))
    if request.method=='GET' and request.workspace.role=='FINANCE':
        return render(request,'finance/reconciliation_edit.html',dict(title='查阅流水与候选凭据',line=line,candidates=choices,history=history,recovery='reconciliation_home'))
    if request.workspace.role!='MANAGER':raise PermissionDenied
    form=MatchForm(request.POST if request.method=='POST' and request.POST.get('action','preview')=='preview' else None)
    return mutation(request,title='提出逐笔匹配',form=form,
        prepare=lambda **v:prepare_match(actor=request.user,line_id=pk,**v),
        confirm=lambda **v:confirm_match(actor=request.user,expected_line_id=pk,**v),
        summary=lambda p:[('流水编号',p['line'].transaction_id),('款项编号',p['entry'].pk),('凭据版本',p['evidence'].version),('金额',p['entry'].amount),('提交后','等待不同财务账号复核；不改变资金余额')],
        destination=lambda r:redirect('reconciliation_match',pk=r.pk),recovery='reconciliation_home',context=dict(line=line,candidates=choices,history=history))

@login_required
@never_cache
@require_GET
def match_detail(request,pk):
    row=get_object_or_404(match_scope(request.user),pk=pk)
    return render(request,'finance/reconciliation_match.html',{'row':row})

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def match_review(request,pk):
    row=get_object_or_404(match_scope(request.user),pk=pk)
    if request.workspace.role!='FINANCE':raise PermissionDenied
    form=MatchReviewForm(request.POST if request.method=='POST' and request.POST.get('action','preview')=='preview' else None)
    return mutation(request,title='独立复核逐笔匹配',form=form,
        prepare=lambda **v:prepare_match_review(actor=request.user,match_id=pk,**v),
        confirm=lambda **v:confirm_match_review(actor=request.user,expected_match_id=pk,**v),
        summary=lambda p:[('匹配编号',p['row'].pk),('流水编号',p['row'].line.transaction_id),('款项编号',p['row'].cash_entry_id),('金额',p['row'].line.amount),('决定','确认匹配' if p['data']['decision']=='approve' else '拒绝匹配'),('复核依据',p['data']['reason']),('影响','仅保存匹配决定，不产生收退款')],
        destination=lambda r:redirect('reconciliation_match',pk=r.pk),recovery='reconciliation_home')

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def evidence_edit(request,pk):
    row=get_object_or_404(cash_scope(request.user,detail=True),pk=pk)
    if request.workspace.role not in ('FRONT_DESK','MANAGER'):raise PermissionDenied
    form=EvidenceForm(request.POST if request.method=='POST' and request.POST.get('action','preview')=='preview' else None,actor=request.user)
    return mutation(request,title='补充／更正已记账款项凭据',form=form,
        prepare=lambda **v:prepare_evidence(actor=request.user,entry_id=pk,**v),
        confirm=lambda **v:confirm_evidence(actor=request.user,expected_entry_id=pk,**v),
        summary=lambda p:[('款项编号',p['entry'].pk),('渠道账户',p['account']),('新凭据编号',p['data']['reference']),('补证依据',p['data']['reason']),('影响','不同财务账号核实后旧匹配失效；原款项金额保持')],
        destination=lambda r:redirect('cash_detail',pk=r.cash_entry_id),recovery='cash_list')

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def evidence_review(request,pk):
    reconciliation_scope(request.user)
    if request.workspace.role!='FINANCE':raise PermissionDenied
    row=get_object_or_404(CashEvidenceVersion,pk=pk)
    form=EvidenceReviewForm(request.POST if request.method=='POST' and request.POST.get('action','preview')=='preview' else None)
    return mutation(request,title='独立复核补证／凭据更正',form=form,
        prepare=lambda **v:prepare_evidence_review(actor=request.user,evidence_id=pk,**v),
        confirm=lambda **v:confirm_evidence_review(actor=request.user,expected_evidence_id=pk,**v),
        summary=lambda p:[('款项编号',p['row'].cash_entry_id),('凭据版本',p['row'].version),('渠道账户',p['row'].account),('凭据编号',p['row'].reference),('补证依据',p['row'].reason),('决定','核实凭据' if p['data']['decision']=='approve' else '拒绝凭据'),('复核依据',p['data']['reason']),('影响','通过后原有匹配转为需重核；原现金金额保持')],
        destination=lambda r:redirect('cash_detail',pk=r.cash_entry_id),recovery='reconciliation_home')
