from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from adc_core.http_support import EXPECTED_ERRORS, add_error
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from finance import advance_services as services
from finance import advance_reversal_services as reversals
from finance.advance_forms import AllocationBasisForm, AllocationLines, AllocationReviewForm, ReversalBasisForm, ReversalReviewForm
from finance.advance_models import AdvanceAllocationReversal
from finance.cash_selectors import with_invoice_balances


@login_required
@require_GET
def listing(request):
    state = request.GET.get('state', '')
    receipt_id = request.GET.get('receipt', '')
    if state not in ('', 'PENDING', 'POSTED', 'REJECTED') or (receipt_id and (
            len(receipt_id) > 19 or not receipt_id.isascii() or not receipt_id.isdecimal() or
            not 0 < int(receipt_id) < 2**63)):
        return render(request, 'business/problem.html', {'problem': '分配筛选无效，请重新选择。'}, status=400)
    with reporting_snapshot():
        rows = services.allocations(request.user).select_related('receipt__clinic', 'receipt__advance_patient').order_by('-pk')
        if state:
            rows = rows.filter(state=state)
        if receipt_id:
            rows = rows.filter(receipt_id=receipt_id)
        page = Paginator(rows, 20).get_page(request.GET.get('page', '1'))
        return render(request, 'finance/advance_allocation_list.html',
                      {'rows': list(page.object_list), 'page_obj': page, 'state_filter': state,
                       'receipt_filter': receipt_id, 'page_query': urlencode(dict(state=state, receipt=receipt_id))})


def _render_detail(request, pk, form=None):
    with reporting_snapshot():
        row = get_object_or_404(services.allocations(request.user).select_related(
            'receipt__clinic', 'receipt__advance_patient', 'prepared_by', 'reviewed_by'), pk=pk)
        live = AdvanceAllocationReversal.objects.filter(state__in=['PENDING', 'POSTED'])
        lines = list(row.lines.select_related('invoice', 'record_version').prefetch_related(
            Prefetch('reversals', queryset=live, to_attr='live_reversals')).order_by('invoice_id'))
        return render(request, 'finance/advance_allocation_detail.html', {
            'row': row, 'lines': lines, 'review_form': form or AllocationReviewForm(),
            'available': services.available_amount(row.receipt),
        })


@login_required
@require_GET
def detail(request, pk):
    return _render_detail(request, pk)


def _confirmation(request, form, title, button, *, summary=None, status=200, recovery_route='advance_allocation_list'):
    return render(request, 'business/proposal.html', dict(form=form, title=title, button=button,
        summary=summary, recovery_route=recovery_route), status=status)


def _facts_summary(facts):
    summary = [('原预收可用（CNY）', facts['available']), ('本次抵扣合计（CNY）', facts['total']),
               ('通过后原预收可用（CNY）', facts['after'])]
    for item in facts['lines']:
        summary.append((f"{item['number']} · 第 {item['revision']} 版",
            f"患者责任 ¥{item['responsibility']} · 当前待付 ¥{item['due']} · 抵扣 ¥{item['amount']} · 通过后待付 ¥{item['after']}"))
    return summary


def _unknown_result(request, *, recovery_route='advance_allocation_list'):
    return render(request, 'business/problem.html',
                  {'problem': '暂不能确认结果，请先查看申请记录和当前状态，再决定是否重试。',
                   'recovery_route': recovery_route}, status=503)


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def new(request, pk):
    title = '申请预收款抵扣'
    button = '确认提交待复核'
    action = request.POST.get('action', 'preview')
    if request.method == 'POST' and action == 'confirm':
        form = ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                row, repeated = services.confirm_allocation(actor=request.user, receipt_id=pk, **form.cleaned_data)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
            except DatabaseError:
                return _unknown_result(request)
            else:
                messages.success(request, '此前已提交，以下为当前结果。' if repeated else '申请已提交，等待财务复核。')
                return redirect('advance_allocation_detail', pk=row.pk)
        return _confirmation(request, form, title, button, status=409)
    if request.method == 'POST' and action != 'preview':
        raise PermissionDenied

    with reporting_snapshot():
        receipt = get_object_or_404(services.advance_receipts(request.user).select_related('clinic', 'advance_patient'), pk=pk)
        available = services.available_amount(receipt)
        bills = with_invoice_balances(services.receipt_invoices(receipt).filter(
            current_record_version__state='PUBLISHED')).filter(remaining__gt=0).order_by('-first_issued_at', '-pk')
        choices = [(pk, f'{number} · 第 {revision} 版 · 待付 ¥{due:.2f}') for pk, number, revision, due in
                   bills.values_list('pk', 'invoice_no', 'current_record_version__revision_no', 'remaining')]
    form = AllocationBasisForm(request.POST or None)
    lines = AllocationLines(request.POST or None, form_kwargs={'invoices': choices})
    if request.method == 'POST' and form.is_valid() and lines.is_valid():
        items = [(line['invoice'], line['amount']) for line in lines.cleaned_data if line]
        try:
            preview = services.prepare_allocation(actor=request.user, receipt_id=pk, items=items, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            summary = [('原预收编号', pk), ('门店与患者', f'{receipt.clinic.name} · {receipt.advance_patient.name}'),
                       ('分配依据', preview['basis'])] + _facts_summary(preview['facts'])
            return _confirmation(request, ExplicitProposalForm(initial={'proposal_token': preview['proposal_token']}),
                                 title, button, summary=summary)
    return render(request, 'finance/advance_allocation_request.html', {
        'receipt': receipt, 'available': available, 'form': form, 'lines': lines, 'can_apply': bool(available and choices),
    })


@login_required
@sensitive_post_parameters()
@require_POST
def review(request, pk):
    title = '独立复核预收抵扣'
    button = '确认独立复核决定'
    action = request.POST.get('action', 'preview')
    if action == 'confirm':
        form = ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                row, repeated = services.confirm_allocation_review(actor=request.user, allocation_id=pk, **form.cleaned_data)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
            except DatabaseError:
                return _unknown_result(request)
            else:
                messages.success(request, '以下为本次分配的保留结果。' if repeated else '独立复核决定已保存。')
                return redirect('advance_allocation_detail', pk=row.pk)
        return _confirmation(request, form, title, button, status=409)
    if action != 'preview':
        raise PermissionDenied
    form = AllocationReviewForm(request.POST)
    if form.is_valid():
        try:
            preview = services.prepare_allocation_review(actor=request.user, allocation_id=pk, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            row = preview['row']
            summary = [('分配编号', pk), ('原预收编号', row.receipt_id),
                       ('门店与患者', f'{row.receipt.clinic.name} · {row.receipt.advance_patient.name}'),
                       ('决定', '批准抵扣' if preview['facts'] else '拒绝分配'), ('依据', preview['reason'])]
            if preview['facts']:
                summary += _facts_summary(preview['facts'])
            return _confirmation(request, ExplicitProposalForm(initial={'proposal_token': preview['proposal_token']}),
                                 title, button, summary=summary)
    return _render_detail(request, pk, form)


def _reverse_summary(facts):
    return [('账单', facts['invoice']), ('原抵扣时的账单版本', facts['original_revision']),
            ('当前账单版本', facts['current_revision']), ('撤销金额（CNY）', facts['amount']),
            ('当前账单待付（CNY）', facts['current_due']), ('通过后账单待付（CNY）', facts['resulting_due']),
            ('通过后预收可用（CNY）', facts['after']), ('通过后待核对预收超额（CNY）', facts['resulting_excess'])]


@login_required
@require_GET
def reversal_list(request):
    allocation_id = request.GET.get('allocation', '')
    state = request.GET.get('state', '')
    if state not in ('', 'PENDING', 'POSTED', 'REJECTED') or (allocation_id and (
            len(allocation_id) > 19 or not allocation_id.isascii() or not allocation_id.isdecimal() or
            not 0 < int(allocation_id) < 2**63)):
        return render(request, 'business/problem.html', {'problem': '请重新选择撤销查询范围。'}, status=400)
    with reporting_snapshot():
        rows = reversals.reversals(request.user).order_by('-pk')
        if allocation_id:
            get_object_or_404(services.allocations(request.user), pk=allocation_id)
            rows = rows.filter(line__allocation_id=allocation_id)
        if state:
            rows = rows.filter(state=state)
        page = Paginator(rows, 20).get_page(request.GET.get('page', '1'))
        return render(request, 'finance/advance_reversal_list.html',
                      dict(rows=list(page.object_list), page_obj=page,
                           page_query=urlencode(dict(state=state, allocation=allocation_id))))


def _reversal_detail(request, pk, form=None):
    row = get_object_or_404(reversals.reversals(request.user).select_related(
        'prepared_by', 'reviewed_by', 'line__record_version'), pk=pk)
    return render(request, 'finance/advance_reversal_detail.html',
                  dict(row=row, review_form=form or ReversalReviewForm()))


@login_required
@require_GET
def reversal_detail(request, pk):
    return _reversal_detail(request, pk)


@login_required
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def reverse_line(request, pk):
    title = '申请撤销抵扣明细'
    button = '确认提交撤销申请'
    action = request.POST.get('action', 'preview')
    if request.method == 'POST' and action == 'confirm':
        form = ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                row, repeated = reversals.confirm_reversal(actor=request.user, line_id=pk, **form.cleaned_data)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
            except DatabaseError:
                return _unknown_result(request, recovery_route='advance_reversal_list')
            else:
                messages.success(request, '此前已提交，以下为当前结果。' if repeated else '撤销申请已提交，等待财务复核。')
                return redirect('advance_reversal_detail', pk=row.pk)
        return _confirmation(request, form, title, button, status=409, recovery_route='advance_reversal_list')
    if action != 'preview':
        raise PermissionDenied
    line = get_object_or_404(reversals.lines(request.user), pk=pk, allocation__state='POSTED')
    form = ReversalBasisForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            p = reversals.prepare_reversal(actor=request.user, line_id=pk, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            summary = [('原分配编号', line.allocation_id), ('撤销依据', p['basis'])] + _reverse_summary(p['facts'])
            return _confirmation(request, ExplicitProposalForm(initial={'proposal_token': p['proposal_token']}),
                                 title, button, summary=summary, recovery_route='advance_reversal_list')
    return render(request, 'finance/advance_reversal_request.html', dict(line=line, form=form))


@login_required
@sensitive_post_parameters()
@require_POST
def reversal_review(request, pk):
    title = '独立复核抵扣撤销'
    button = '确认独立复核决定'
    action = request.POST.get('action', 'preview')
    if action == 'confirm':
        form = ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                row, repeated = reversals.confirm_review(actor=request.user, reversal_id=pk, **form.cleaned_data)
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
            except DatabaseError:
                return _unknown_result(request, recovery_route='advance_reversal_list')
            else:
                messages.success(request, '此前已复核，以下为保留结果。' if repeated else '撤销复核结果已保存。')
                return redirect('advance_reversal_detail', pk=row.pk)
        return _confirmation(request, form, title, button, status=409, recovery_route='advance_reversal_list')
    if action != 'preview':
        raise PermissionDenied
    form = ReversalReviewForm(request.POST)
    if form.is_valid():
        try:
            p = reversals.prepare_review(actor=request.user, reversal_id=pk, **form.cleaned_data)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            summary = [('撤销申请编号', pk), ('决定', '批准撤销' if p['facts'] else '拒绝撤销'), ('依据', p['reason'])]
            if p['facts']:
                summary += _reverse_summary(p['facts'])
            return _confirmation(request, ExplicitProposalForm(initial={'proposal_token': p['proposal_token']}),
                                 title, button, summary=summary, recovery_route='advance_reversal_list')
    return _reversal_detail(request, pk, form)
