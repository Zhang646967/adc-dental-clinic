from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from finance.reconciliation_views import mutation
from insurance.policies import scope
from insurance.settlement_services import settlements
from insurance.settlement_views import _confirm
from insurance.cancellation_models import CANCEL_MODES
from insurance import cancellation_services as services


class CancellationForm(forms.Form):
    simulation_mode = forms.ChoiceField(label='本地模拟方式', choices=CANCEL_MODES)
    reason = forms.CharField(label='撤销原结算依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class ReviewForm(forms.Form):
    decision = forms.ChoiceField(label='独立核对决定', choices=[('APPROVE', '原撤销与基金退回核对通过'), ('REJECT', '未通过，保留原分担并继续处置')])
    reason = forms.CharField(label='原撤销结果与资金退回核对依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def create(request, pk):
    row = get_object_or_404(settlements(request.user), pk=pk)
    form = CancellationForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None)
    return mutation(request, title='撤销原医保模拟结算', form=form,
        prepare=lambda **v: services.prepare_cancellation(actor=request.user, request_id=pk, **v),
        confirm=lambda **v: services.confirm_cancellation(actor=request.user, expected_request_id=pk, **v),
        summary=lambda p: [('原请求', row.request_id), ('原模拟受理编号', p['source']['original_reference']),
            ('原个人账户承担', row.personal_account), ('原基金承担', row.fund_amount),
            ('办理依据', p['data']['reason']), ('提交后', '继续核对原撤销结果、基金退回和独立复核；患者现金不自动退款。')],
        destination=lambda result: redirect('insurance_settlement_detail', pk=result.pk), recovery='insurance_settlements')


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def query(request, pk):
    row = get_object_or_404(settlements(request.user), pk=pk)
    if request.method == 'POST':
        if request.POST.get('action') != 'confirm':
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied('请明确确认查询原撤销编号。')
        return _confirm(request, services.confirm_cancellation_query, expected_request_id=pk)
    from finance.reconciliation_views import proposal_page
    from adc_core.http_support import EXPECTED_ERRORS
    from django.shortcuts import render
    try: p = services.prepare_cancellation_query(actor=request.user, request_id=pk)
    except EXPECTED_ERRORS as exc:
        return render(request, 'business/problem.html', dict(problem=str(exc)), status=409)
    return proposal_page(request, '查询原撤销结果', [('原结算请求', row.request_id),
        ('原撤销编号', row.cancellation.cancellation_id), ('查询后', '取得保留的原撤销结果，继续核对基金退回和独立复核。')],
        p['proposal_token'], 'insurance_settlements')


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def review(request, pk):
    scope(request.user, ('FINANCE',))
    row = get_object_or_404(settlements(request.user), pk=pk)
    form = ReviewForm(request.POST if request.method=='POST' and request.POST.get('action')=='preview' else None)
    return mutation(request, title='独立核对结算撤销', form=form,
        prepare=lambda **v: services.prepare_cancellation_review(actor=request.user, request_id=pk, **v),
        confirm=lambda **v: services.confirm_cancellation_review(actor=request.user, expected_request_id=pk, **v),
        summary=lambda p: [('原请求', row.request_id), ('原个人账户承担', row.personal_account), ('原基金承担', row.fund_amount),
            ('决定', '撤销核对通过，恢复患者现金责任' if p['data']['decision']=='APPROVE' else '未通过，保留原分担并继续处置'),
            ('依据', p['data']['reason']), ('账款衔接', '只撤回原非现金分担；不撤销实际费用，不自动产生患者收款或退款。')],
        destination=lambda result: redirect('insurance_settlement_detail', pk=result.pk), recovery='insurance_settlements')
