from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from finance.cash_selectors import invoice_balance
from insurance import settlement_services as services
from insurance.policies import scope
from insurance.settlement_forms import SettlementForm, SettlementReviewForm
from insurance.settlement_source import quote_source, authorized_invoice
from insurance.settlement_models import SETTLEMENT_STATES, ACTIVE_SETTLEMENT_STATES, SIMULATION_MODES


def _invoice(actor, pk):
    from django.core.exceptions import ObjectDoesNotExist
    try: return authorized_invoice(actor, pk)
    except ObjectDoesNotExist: raise Http404 from None


def _confirm(request, command, **expected):
    form = ExplicitProposalForm(request.POST)
    if form.is_valid():
        try:
            row, repeated = command(actor=request.user, **form.cleaned_data, **expected)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        except DatabaseError:
            return render(request, 'business/problem.html', {'problem': '暂不能确认办理结果，请返回结算进度查询原请求；不要直接重复申报或收退款。'}, status=503)
        else:
            messages.success(request, '显示原请求当前进度。' if repeated else '医保结算办理进度已保存；患者现金仍按独立收退款流程核对。')
            return redirect('insurance_settlement_detail', pk=row.pk)
    return render(request, 'business/proposal.html', dict(title='重新核对结算进度', form=form,
        button='明确确认', recovery_route='insurance_settlements'), status=409)


@login_required
@never_cache
@require_GET
def listing(request):
    with reporting_snapshot():
        rows = services.settlements(request.user).select_related('invoice').order_by('-pk')
        state = request.GET.get('state', '')
        if state and state not in dict(SETTLEMENT_STATES):
            return render(request, 'business/problem.html', {'problem': '请选择有效的结算进度。'}, status=400)
        invoice_id = request.GET.get('invoice', '')
        if invoice_id:
            if not invoice_id.isascii() or not invoice_id.isdecimal() or not 0 < int(invoice_id) < 2**63:
                raise Http404
            _invoice(request.user, int(invoice_id))
            rows = rows.filter(invoice_id=int(invoice_id))
        if state:
            rows = rows.filter(state=state)
        page = Paginator(rows, 20).get_page(request.GET.get('page', '1'))
        from urllib.parse import urlencode
        return render(request, 'insurance/settlement_list.html', dict(rows=list(page.object_list), page_obj=page,
            states=SETTLEMENT_STATES, state_filter=state, invoice_filter=invoice_id,
            page_query=urlencode(dict(state=state, invoice=invoice_id))))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def create(request, pk):
    scope(request.user, ('FRONT_DESK',))
    invoice = _invoice(request.user, pk)
    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        return _confirm(request, services.confirm_settlement, expected_invoice_id=pk)
    if request.method == 'POST' and request.POST.get('action') != 'preview':
        raise PermissionDenied('请先预览原账单的逐行模拟分担。')
    active = services.settlements(request.user).filter(invoice=invoice, state__in=ACTIVE_SETTLEMENT_STATES).first()
    if active:
        return redirect('insurance_settlement_detail', pk=active.pk)
    try:
        with reporting_snapshot(): source = quote_source(request.user, pk)['snapshot']
    except RuleError as exc:
        return render(request, 'insurance/settlement_form.html', dict(invoice=invoice, blocker=str(exc)))
    form = SettlementForm(source, request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            p = services.prepare_settlement(actor=request.user, invoice_id=pk, allocations=form.allocations(),
                simulation_mode=form.cleaned_data['simulation_mode'], reason=form.cleaned_data['reason'])
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            rows = [dict(source=s, result=a) for s, a in zip(p['source']['lines'], p['data']['allocations'])]
            return render(request, 'insurance/settlement_preview.html', dict(invoice=invoice, source=p['source'],
                rows=rows, data=p['data'], simulation_label=dict(SIMULATION_MODES)[p['data']['simulation_mode']],
                form=ExplicitProposalForm(initial={'proposal_token': p['proposal_token']})))
    return render(request, 'insurance/settlement_form.html', dict(invoice=invoice, source=source, form=form))


@login_required
@never_cache
@require_GET
def detail(request, pk):
    with reporting_snapshot():
        row = get_object_or_404(services.settlements(request.user).select_related('invoice'), pk=pk)
        balance = invoice_balance(_invoice(request.user, row.invoice_id))
        events = list(row.events.select_related('actor').order_by('-sequence'))
        for event in events:
            event.action_label = {'SUBMIT':'提交模拟请求','QUERY':'查询原编号','REVIEW':'独立复核',
                'CANCEL_START':'发起原结算撤销','CANCEL_QUERY':'查询原撤销结果','CANCEL_REVIEW':'独立核对撤销'}.get(event.action, event.action)
            event.state_label = dict(SETTLEMENT_STATES).get(event.snapshot['state'], event.snapshot['state'])
            if 'cancellation_state' in event.snapshot:
                from insurance.cancellation_models import CANCEL_STATES
                event.cancellation_label = dict(CANCEL_STATES)[event.snapshot['cancellation_state']]
        from finance.allocation_projection import claim_funds
        cancellation = row.cancellation if hasattr(row, 'cancellation') else None
        return render(request, 'insurance/settlement_detail.html', dict(row=row, balance=balance,
            funds=claim_funds(row.pk), cancellation=cancellation,
            cancellation_reviews=cancellation.reviews.select_related('reviewed_by').order_by('-sequence') if cancellation else [],
            can_cancel=row.state in ('CONFIRMED','AWAITING_REVIEW','REVIEW_REJECTED'),
            can_query_cancel=cancellation and cancellation.state in ('PROCESSING','UNKNOWN'),
            can_review_cancel=cancellation and cancellation.state in ('AWAITING_REVIEW','REVIEW_REJECTED')
                and request.user._adc_workspace.role=='FINANCE' and cancellation.prepared_by_id!=request.user.pk,
            lines=list(row.lines.order_by('line_no')), events=events,
            can_query=row.state in ('PROCESSING', 'UNKNOWN'), can_review=row.state == 'AWAITING_REVIEW'
            and request.user._adc_workspace.role == 'FINANCE' and row.created_by_id != request.user.pk))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def query(request, pk):
    row = get_object_or_404(services.settlements(request.user), pk=pk)
    if request.method == 'POST':
        if request.POST.get('action') != 'confirm': raise PermissionDenied('请明确确认查询原编号。')
        return _confirm(request, services.confirm_query, expected_request_id=pk)
    try: p = services.prepare_query(actor=request.user, request_id=pk)
    except EXPECTED_ERRORS as exc:
        return render(request, 'business/problem.html', {'problem': str(exc)}, status=409)
    return render(request, 'business/proposal.html', dict(title='查询原医保模拟请求',
        summary=[('原请求编号', row.request_id), ('当前进度', row.get_state_display()),
                 ('查询后', '取得同一请求的原模拟结果，待独立复核；不会重新申报或记入现金')],
        form=ExplicitProposalForm(initial={'proposal_token': p['proposal_token']}), button='查询原编号', recovery_route='insurance_settlements'))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def review(request, pk):
    scope(request.user, ('FINANCE',))
    row = get_object_or_404(services.settlements(request.user), pk=pk)
    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        return _confirm(request, services.confirm_settlement_review, expected_request_id=pk)
    if request.method == 'POST' and request.POST.get('action') != 'preview': raise PermissionDenied('请先预览独立核对决定。')
    form = SettlementReviewForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try: p = services.prepare_settlement_review(actor=request.user, request_id=pk, **form.cleaned_data)
        except EXPECTED_ERRORS as exc: add_error(form, exc)
        else:
            return render(request, 'business/proposal.html', dict(title='独立核对医保模拟分担',
                summary=[('原请求', row.request_id), ('原账单金额', row.gross_amount), ('现金责任', row.patient_cash),
                    ('个人账户承担', row.personal_account), ('基金承担（应收）', row.fund_amount),
                    ('决定', '核对通过' if p['data']['decision'] == 'APPROVE' else '未通过，原请求仍待处置'), ('依据', p['data']['reason'])],
                form=ExplicitProposalForm(initial={'proposal_token': p['proposal_token']}), button='明确确认复核决定', recovery_route='insurance_settlements'))
    return render(request, 'insurance/settlement_review.html', dict(row=row, form=form))
