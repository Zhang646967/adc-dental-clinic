from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from equipment.policies import manager_clinic
from finance.cash_services import _date
from finance.daily_facts import day_facts, page_day_facts, comparison, KINDS, LABELS
from finance.daily_services import (close_scope,latest,blocker,prepare_close,confirm_close,
    prepare_close_review,confirm_close_review)

class DailyForm(forms.Form):
    business_date=forms.DateField(label='事实日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    evidence=forms.CharField(label='凭据编号与核对范围（仅合成案例）',max_length=500,widget=forms.Textarea(attrs={'rows':2}),help_text='四类凭据须分别核实；不要填写患者、银行卡、账号或交易秘密。')
    reason=forms.CharField(label='交接说明／差异原因／重开依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}),help_text='有差异时，经办人负责回查原始业务；只说明原因不能使差异通过复核。')
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for k,label in zip(KINDS,LABELS):
            self.fields[k]=forms.DecimalField(label=f'凭据核实的{label}总额（CNY）',min_value=0,max_digits=28,decimal_places=2,help_text='按总额填写，不能填净额；明确没有时填 0。')
        self.order_fields(['business_date',*KINDS,'evidence','reason'])

class ReviewForm(forms.Form):
    decision=forms.ChoiceField(label='独立复核决定',choices=[('approve','四类金额一致，完成交接复核'),('reject','退回经办人重新核对')])
    reason=forms.CharField(label='复核依据／需解决的问题',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

def _data(actor,pk):
    with reporting_snapshot():
        row=close_scope(actor).select_related('clinic','prepared_by','reviewed_by').get(pk=pk)
        current=day_facts(row.clinic_id,row.business_date)
        from finance.reconciliation_selectors import evidence_summary
        from finance.allocation_projection import daily_fund_summary
        return dict(row=row,current=current,channel_summary=evidence_summary(row.clinic_id,row.business_date),comparison=comparison(row.snapshot,row.declared),
            fund_summary=daily_fund_summary(row.clinic_id,row.business_date),
            changed=row.snapshot!=current,blocker=blocker(row,current) if row.state=='PENDING' else '',
            latest=latest(row.clinic_id,row.business_date))

@login_required
@never_cache
@require_GET
def listing(request):
    state=request.GET.get('state','');day=request.GET.get('day','')
    if state not in ('','PENDING','APPROVED','REJECTED'):return render(request,'business/problem.html',{'problem':'日结状态筛选无效。'},status=400)
    try:
        if day:day=_date(day)
    except EXPECTED_ERRORS:return render(request,'business/problem.html',{'problem':'日结日期筛选无效。'},status=400)
    with reporting_snapshot():
        qs=close_scope(request.user).filter(next_version__isnull=True)
        if state:qs=qs.filter(state=state)
        if day:qs=qs.filter(business_date=day)
        page=Paginator(qs.select_related('clinic','prepared_by','reviewed_by').order_by('-business_date','clinic_id'),20).get_page(request.GET.get('page','1'))
        rows=list(page.object_list)
        facts=page_day_facts((row.clinic_id,row.business_date) for row in rows)
        for row in rows:row.changed=row.snapshot!=facts[(row.clinic_id,row.business_date)]
    return render(request,'finance/daily_list.html',dict(rows=rows,page_obj=page,state=state,day=day))

@login_required
@never_cache
@require_GET
def detail(request,pk):
    try:data=_data(request.user,pk)
    except EXPECTED_ERRORS:raise Http404
    return render(request,'finance/daily_detail.html',data)

def _edit(request,pk=None):
    review=pk is not None
    if review:data=_data(request.user,pk)
    else:
        manager_clinic(request.user);data={}
    title='独立复核日结交接' if review else '编制／重开日结核对'
    action=request.POST.get('action','preview')
    if request.method=='POST' and action=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                row,repeated=(confirm_close_review(actor=request.user,expected_close_id=pk,**form.cleaned_data) if review else confirm_close(actor=request.user,**form.cleaned_data))
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            except DatabaseError:return render(request,'business/problem.html',{'problem':'暂不能核实保存结果，请查阅日结清单确认当前版本。'},status=503)
            else:
                messages.success(request,'此前已保存，显示当前版本。' if repeated else '日结交接已保存，原始现金账保持。')
                return redirect('daily_close_detail',pk=row.pk)
        return render(request,'business/proposal.html',dict(title=title,form=form,button='确认保存日结交接',recovery_route='daily_close_list'),status=409)
    if request.method=='POST' and action!='preview':raise PermissionDenied
    form=(ReviewForm if review else DailyForm)(request.POST if request.method=='POST' else None,initial={} if review else {'business_date':request.GET.get('day') or timezone.localdate()})
    if review and (data['blocker'] or data['row'].prepared_by_id==request.user.pk or data['row'].state!='PENDING'):
        form.fields['decision'].choices=[('reject','退回经办人重新核对')]
    if request.method=='POST' and form.is_valid():
        values=dict(form.cleaned_data)
        if not review:values['declared']={k:values.pop(k) for k in KINDS}
        try:p=prepare_close_review(actor=request.user,close_id=pk,**values) if review else prepare_close(actor=request.user,**values)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            if review:
                summary=[('日结日期',p['row'].business_date),('版本',p['row'].version),('决定','通过交接复核' if p['decision']=='approve' else '退回重核'),('复核说明',p['reason'])]
            else:
                summary=[('事实日期（北京时间）',p['day']),('新版本',p['version']),('待审核款项数',p['snapshot']['pending'])]
                for item in p['comparison']:
                    summary.append((item['label'],f"账内 {item['ledger']} / 凭据 {item['declared']} / 差异 {item['difference']:.2f} CNY"))
                summary.extend([('凭据核对范围',p['evidence']),('交接／重开依据',p['reason']),('差异责任人',request.user.username),('保存后','待独立复核；差异或未审款项阻止通过；不自动调账')])
            return render(request,'business/proposal.html',dict(title=title,summary=summary,form=ExplicitProposalForm(initial={'proposal_token':p['proposal_token']}),button='确认保存日结交接',recovery_route='daily_close_list'))
    return render(request,'finance/daily_edit.html',dict(data,title=title,form=form))

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def request_close(request):return _edit(request)

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def review_close(request,pk):
    try:return _edit(request,pk)
    except EXPECTED_ERRORS:raise Http404
