from uuid import UUID
from django import forms
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, OuterRef, Subquery
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from accounts.models import UserAccount
from adc_core.proposals import workspace_binding
from adc_core.snapshots import reporting_snapshot
from finance.reconciliation_views import mutation
from finance.allocation_models import FundAllocation, FundIssue, FundIssueEvent
from finance.allocation_projection import claim_funds, transfer_funds
from finance.fund_models import FundTransfer
from finance.fund_views import ReviewForm
from finance import allocation_services as services
from finance import fund_issue_services as issues
from insurance.settlement_models import SettlementRequest


def _read(actor):
    workspace_binding(actor, ('FINANCE',))


def _claims():
    return SettlementRequest.objects.select_related('invoice', 'arrangement__clinic', 'review').order_by('-pk')


def _search(qs, value):
    value = value.strip()[:80]
    if value:
        condition = Q(invoice__invoice_no__icontains=value)
        try: condition |= Q(request_id=UUID(value))
        except ValueError: pass
        qs = qs.filter(condition)
    return qs


def _fund_view(claim):
    facts = claim_funds(claim.pk)
    facts['receivable'] = claim.fund_amount if claim.state in ('CONFIRMED', 'CANCEL_PENDING') and hasattr(claim, 'review') and claim.review.decision == 'APPROVE' else 0
    facts['unreceived'] = max(facts['receivable'] - facts['net_received'], 0)
    return facts


class AllocationForm(forms.Form):
    basis = forms.CharField(label='本次逐笔分配依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, candidates, *args, **kw):
        super().__init__(*args, **kw)
        self.candidates = list(candidates)
        for row in self.candidates:
            facts = _fund_view(row)
            self.fields['claim_' + str(row.pk)] = forms.DecimalField(
                label=f'{row.invoice.invoice_no} · 申报 {str(row.request_id)[:8]}',
                max_digits=16, decimal_places=2, min_value=0, required=False,
                help_text=f'基金应收 {facts["receivable"]}；已到账净额 {facts["net_received"]}；待核对入账 {facts["reserved_in"]} / 退回 {facts["reserved_out"]}。不分配时留空。')

    def allocations(self):
        return [dict(claim=row.pk, amount=str(self.cleaned_data['claim_'+str(row.pk)]))
            for row in self.candidates if self.cleaned_data.get('claim_'+str(row.pk))]


class IssueForm(forms.Form):
    kind = forms.ChoiceField(label='事项类型', choices=FundIssue._meta.get_field('kind').choices)
    amount = forms.DecimalField(label='待核对金额', max_digits=16, decimal_places=2, min_value=0, required=False,
        help_text='金额尚不明确时留空；这里不会记账或转为患者欠款。')
    owner_id = forms.TypedChoiceField(label='跟进责任人', coerce=int)
    due_at = forms.DateTimeField(label='下次联系期限', widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        help_text='按门诊业务时间填写。')
    basis = forms.CharField(label='跟进依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.fields['owner_id'].choices = list(UserAccount.objects.filter(is_active=True,
            role_assignments__role='FINANCE', role_assignments__scope_kind='CHAIN', role_assignments__is_active=True
        ).distinct().order_by('username').values_list('pk', 'username'))


class FollowupForm(IssueForm):
    state = forms.ChoiceField(label='本次处理', choices=[('OPEN', '继续跟进／重新分配责任'), ('CLOSED', '记录结论并结束跟进')])

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        del self.fields['kind']; del self.fields['amount']
        self.fields['due_at'].required = False
        self.fields['due_at'].help_text = '继续跟进须填写未来期限；结束跟进保留原期限。'

    def clean(self):
        d = super().clean()
        if d.get('state') == 'OPEN' and not d.get('due_at'):
            self.add_error('due_at', '请填写下次联系期限。')
        return d


@login_required
@never_cache
@require_GET
def claim_list(request):
    _read(request.user)
    with reporting_snapshot():
        q = request.GET.get('q', '')[:80]
        qs = _search(_claims().filter(state__in=['CONFIRMED', 'CANCEL_PENDING', 'CANCELLED', 'REVIEW_REJECTED']), q)
        page = Paginator(qs, 20).get_page(request.GET.get('page', '1'))
        rows = [dict(claim=row, funds=_fund_view(row)) for row in page.object_list]
        return render(request, 'finance/fund_claims.html', dict(rows=rows, page_obj=page, q=q))


@login_required
@never_cache
@require_GET
def claim_detail(request, pk):
    _read(request.user)
    with reporting_snapshot():
        row = get_object_or_404(_claims(), pk=pk)
        page = Paginator(row.fund_allocations.select_related('allocation__transfer__line', 'allocation').order_by('-pk'), 20).get_page(request.GET.get('page', '1'))
        return render(request, 'finance/fund_claim_detail.html', dict(row=row, funds=_fund_view(row),
            page_obj=page, allocations=list(page.object_list), issues=row.fund_issues.order_by('-pk')[:20]))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def create(request, pk):
    _read(request.user)
    transfer = get_object_or_404(FundTransfer.objects.select_related('line__account__clinic'), pk=pk)
    states = ['CONFIRMED'] if transfer.kind == 'RECEIPT' else ['CONFIRMED', 'CANCEL_PENDING']
    candidates = _search(_claims().filter(arrangement__clinic_id=transfer.line.account.clinic_id,
        state__in=states, review__decision='APPROVE'), request.GET.get('q', ''))[:100]
    form = AllocationForm(candidates, request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None)
    return mutation(request, title='逐笔分配基金到账' if transfer.kind=='RECEIPT' else '逐笔核对基金退回', form=form,
        prepare=lambda **v: services.prepare_allocation(actor=request.user, transfer_id=pk,
            allocations=form.allocations(), basis=v['basis']),
        confirm=lambda **v: services.confirm_allocation(actor=request.user, expected_transfer_id=pk, **v),
        summary=lambda p: [('原流水', transfer.line.transaction_id), ('诊所', transfer.line.account.clinic.name),
            ('银行日期', transfer.line.booked_on), ('本次用途', transfer.get_kind_display())] +
            [(line['request_id'], line['amount'] + ' ' + p['source']['currency']) for line in p['source']['lines']] +
            [('分配依据', p['data']['basis']), ('提交后', '预留本次分配金额，待另一财务账号独立复核。')],
        destination=lambda row: redirect('fund_allocation_detail', pk=row.pk), recovery='fund_transfers',
        context=dict(allocation_transfer=transfer, allocation_search=request.GET.get('q', '')[:80]))


@login_required
@never_cache
@require_GET
def detail(request, pk):
    _read(request.user)
    row = get_object_or_404(FundAllocation.objects.select_related('transfer__line__account__clinic', 'prepared_by', 'reviewed_by'), pk=pk)
    return render(request, 'finance/fund_allocation_detail.html', dict(row=row,
        lines=row.lines.select_related('claim__invoice'), can_review=row.state=='PENDING' and row.prepared_by_id!=request.user.pk))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def review(request, pk):
    _read(request.user)
    row = get_object_or_404(FundAllocation.objects.select_related('transfer__line'), pk=pk)
    form = ReviewForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None)
    form.fields['decision'].choices = [('approve', '逐笔分配核对通过'), ('reject', '未通过，释放本次预留金额')]
    return mutation(request, title='独立核对基金分配', form=form,
        prepare=lambda **v: services.prepare_allocation_review(actor=request.user, allocation_id=pk, **v),
        confirm=lambda **v: services.confirm_allocation_review(actor=request.user, expected_allocation_id=pk, **v),
        summary=lambda p: [('原银行流水', row.transfer.line.transaction_id), ('本批金额', row.total),
            ('用途', row.transfer.get_kind_display())] +
            [(str(line.claim.request_id), line.amount) for line in row.lines.select_related('claim')] +
            [('决定', '核对通过' if p['data']['decision']=='approve' else '未通过，释放预留'), ('依据', p['data']['reason'])],
        destination=lambda result: redirect('fund_allocation_detail', pk=result.pk), recovery='fund_transfers')


def _issue_summary(p):
    d = p['data']
    return [('责任人', UserAccount.objects.get(pk=d['owner']).username), ('联系期限', d['due_at']),
        ('依据', d['basis']), ('资金边界', '跟进记录不会修改分担、现金或基金核销金额。')]


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def issue_new(request, pk):
    _read(request.user)
    row = get_object_or_404(_claims(), pk=pk)
    form = IssueForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None,
        initial=dict(owner_id=request.user.pk))
    return mutation(request, title='登记基金差额与待核对事项', form=form,
        prepare=lambda **v: issues.prepare_issue(actor=request.user, claim_id=pk, **v),
        confirm=lambda **v: issues.confirm_issue(actor=request.user, expected_claim_id=pk, **v),
        summary=lambda p: [('原申报', row.request_id), ('事项类型', dict(FundIssue._meta.get_field('kind').choices)[p['data']['kind']]),
            ('金额', p['data']['amount'] if p['data']['amount'] is not None else '尚未明确')] + _issue_summary(p),
        destination=lambda result: redirect('fund_issue_detail', pk=result.pk), recovery='fund_claims')


@login_required
@never_cache
@require_GET
def issue_list(request):
    _read(request.user)
    last = FundIssueEvent.objects.filter(issue_id=OuterRef('pk')).order_by('-sequence')
    qs = FundIssue.objects.select_related('claim__invoice').annotate(current_state=Subquery(last.values('state')[:1]),
        owner_name=Subquery(last.values('owner__username')[:1]), due=Subquery(last.values('due_at')[:1]))
    closed = request.GET.get('closed') == '1'
    page = Paginator(qs.filter(current_state='CLOSED' if closed else 'OPEN').order_by('due', 'pk'), 20).get_page(request.GET.get('page', '1'))
    return render(request, 'finance/fund_issues.html', dict(page_obj=page, now=timezone.now(), closed=closed))


@login_required
@never_cache
@require_GET
def issue_detail(request, pk):
    _read(request.user)
    row = get_object_or_404(FundIssue.objects.select_related('claim__invoice'), pk=pk)
    events = list(row.events.select_related('owner', 'actor').order_by('-sequence'))
    return render(request, 'finance/fund_issue_detail.html', dict(row=row, events=events,
        can_follow=events[0].state=='OPEN', now=timezone.now()))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def followup(request, pk):
    _read(request.user)
    row = get_object_or_404(FundIssue, pk=pk); last = row.events.latest('sequence')
    form = FollowupForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None,
        initial=dict(owner_id=last.owner_id, due_at=last.due_at, state='OPEN'))
    return mutation(request, title='记录跟进与责任调整', form=form,
        prepare=lambda **v: issues.prepare_followup(actor=request.user, issue_id=pk, **v),
        confirm=lambda **v: issues.confirm_followup(actor=request.user, expected_issue_id=pk, **v),
        summary=lambda p: [('结果', '继续跟进' if p['data']['state']=='OPEN' else '记录结论并结束跟进')] + _issue_summary(p),
        destination=lambda result: redirect('fund_issue_detail', pk=result.pk), recovery='fund_issues')
