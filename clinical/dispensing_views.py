"""Clinic dispensing worklist and the preview/confirm pages."""
from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, OuterRef, Subquery, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from adc_core.http_support import EXPECTED_ERRORS, add_error
from clinical import dispensing as cmd
from clinical.encounter_views import clinical_render
from clinical.pharmacy_models import DispenseMovement, PharmacyQuote, PharmacyStop
from clinical.prescription_access import active_duties
from clinical.prescription_forms import PrescriptionConfirmForm
from clinical.prescription_models import Prescription, PrescriptionDuty, PrescriptionVersion
from clinical.prescriptions import current_version
from supplies.access import enabled as stock_enabled
from supplies.pharmacy import choices as lot_choices
from supplies.models import NursingExecution
from workspaces.views import select_clinic

ACTIONS = {'QUOTE': '确认本店划价', 'ISSUE': '登记实际发药', 'RETURN': '登记实际退药', 'STOP': '停止剩余调配'}


class ActionForm(forms.Form):
    reason = forms.CharField(label='办理依据', max_length=500, widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, kind, rows=(), issues=(), lots=(), **kwargs):
        super().__init__(*args, **kwargs)
        if kind == 'ISSUE':
            self.fields['line'] = forms.TypedChoiceField(label='药品条目', coerce=int, choices=[
                (row.pk, f'{row.name_snapshot} · 尚可发 {row.ordered_quantity-row.issued} {row.unit_snapshot}')
                for row in rows if row.issued < row.ordered_quantity
            ])
            if stock_enabled():
                self.fields['lot'] = forms.TypedChoiceField(label='实际发药批次', coerce=int, choices=[
                    (lot.pk,f'{lot.item.name} · {lot.code} · 可用 {lot.available} {lot.item.unit}') for lot in lots
                ])
        if kind == 'RETURN':
            self.fields['issue'] = forms.TypedChoiceField(label='原发药记录', coerce=int, choices=[
                (row.pk, f'#{row.pk} · {row.line.name_snapshot} · 可退 {row.quantity-row.returned-row.administered} {row.line.unit_snapshot}')
                for row in issues
            ])
        if kind in ('ISSUE', 'RETURN'):
            self.fields['quantity'] = forms.IntegerField(label='实际数量', min_value=1, max_value=9999)
            self.order_fields(['line', 'lot', 'issue', 'quantity', 'reason'])


def case_history(version):
    if version is None or version.state != 'APPROVED':
        return {}
    quote = PharmacyQuote.objects.filter(approval=version.decision).first()
    stop = PharmacyStop.objects.filter(approval=version.decision).first()
    return dict(quote=quote, stop=stop, quote_lines=list(cmd.quote_rows(quote)) if quote else [])


def _case(request, pk):
    cmd.dispenser(request.user, request.workspace.clinic_id)
    cases = Prescription.objects.select_related('visit__clinic', 'visit__patient', 'prescriber').exclude(prescriber=request.user)
    return get_object_or_404(cases,
                             pk=pk, visit__clinic_id=request.workspace.clinic_id)


@login_required
@never_cache
@require_GET
def queue(request):
    clinic = request.workspace.clinic_id
    if clinic is None and cmd.enabled():
        return select_clinic(request)
    cmd.dispenser(request.user, clinic)
    latest = PrescriptionVersion.objects.filter(prescription=OuterRef('prescription')).order_by('-number')
    rows = PrescriptionVersion.objects.filter(
        pk=Subquery(latest.values('pk')[:1]), prescription__visit__clinic_id=clinic,
        decision__action='APPROVED',
    ).exclude(prescription__prescriber=request.user).select_related(
        'prescription__visit__patient', 'decision__pharmacy_quote', 'decision__pharmacy_stop',
    ).order_by('-submitted_at', '-pk')
    can_review = active_duties(request.user.pk, PrescriptionDuty.Kind.REVIEW).filter(clinic_id=clinic).exists()
    return clinical_render(request, 'clinical/dispensing_queue.html', dict(
        page=Paginator(rows, 20).get_page(request.GET.get('page')), can_review=can_review,
    ))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    case = _case(request, pk)
    version = current_version(case)
    history = case_history(version)
    quote = history.get('quote')
    rows = history.get('quote_lines', [])
    moves = DispenseMovement.objects.filter(line__quote=quote).select_related('line', 'actor', 'stock_movement__lot').order_by('-pk') if quote else DispenseMovement.objects.none()
    administered=NursingExecution.objects.filter(issue_id=OuterRef('pk')).order_by().values('issue_id').annotate(
        total=Sum('quantity'),
    ).values('total')
    issues = moves.filter(kind='ISSUE').annotate(
        returned=Sum('returns__quantity', default=0),
        administered=Coalesce(Subquery(administered),0),
    ).filter(quantity__gt=F('returned')+F('administered')) if quote else moves
    kinds = []
    if not settings.ADC_READ_ONLY and request.user.pk != case.prescriber_id and version and version.state == 'APPROVED':
        if case.visit.status == 'CHECKED_IN' and not history['stop']:
            if not quote:
                kinds.extend(['QUOTE', 'STOP'])
            elif any(row.issued < row.ordered_quantity for row in rows):
                kinds.extend(['ISSUE', 'STOP'])
        if case.visit.status in ('CHECKED_IN', 'COMPLETED') and issues.exists():
            kinds.append('RETURN')
    lots=list(lot_choices(rows)) if 'ISSUE' in kinds else []
    stock_missing='ISSUE' in kinds and stock_enabled() and not lots
    if stock_missing:
        kinds.remove('ISSUE')
    posted = request.POST.get('action') if request.method == 'POST' else None
    action_forms = {kind: ActionForm(request.POST if kind == posted else None, prefix=kind.lower(),
                                    kind=kind, rows=rows, issues=issues if kind == 'RETURN' else (), lots=lots)
                    for kind in kinds}
    error, status = '', 200
    if request.method == 'POST':
        form = action_forms.get(posted)
        if form is None:
            error, status = '本次办理条件已变化，请核对当前处方与记录。', 409
        elif not form.is_valid():
            status = 400
        else:
            data = form.cleaned_data
            line = next((row for row in rows if row.pk == data.get('line')), None)
            issue = next((row for row in issues if row.pk == data.get('issue')), None) if posted == 'RETURN' else None
            try:
                info, token = cmd.prepare(request.user, case, posted, data['reason'],
                    line_id=issue.line_id if issue else data.get('line'), issue_id=data.get('issue'),
                    quantity=data.get('quantity'),lot_id=data.get('lot'))
            except EXPECTED_ERRORS as exc:
                add_error(form, exc)
                status = 409
            else:
                return clinical_render(request, 'clinical/dispensing_confirm.html', dict(
                    case=case, visit=case.visit, version=version, data=info, label=ACTIONS[posted],
                    item=issue.line if issue else line, lot=next((row for row in lots if row.pk==info.get('lot')),None),
                    form=PrescriptionConfirmForm(initial={'proposal_token': token}),
                ))
    return clinical_render(request, 'clinical/dispensing_detail.html', dict(
        case=case, version=version, visit=case.visit, history=history,
        movements=Paginator(moves, 25).get_page(request.GET.get('page')), error=error, stock_missing=stock_missing,
        actions=[(kind, ACTIONS[kind], form) for kind, form in action_forms.items()],
    ), status=status)


@login_required
@never_cache
@sensitive_post_parameters()
@require_POST
def confirm(request, pk):
    case = _case(request, pk)
    form = PrescriptionConfirmForm(request.POST)
    if form.is_valid():
        try:
            obj, replayed = cmd.confirm(request.user, form.cleaned_data['proposal_token'], True, case_id=case.pk)
        except EXPECTED_ERRORS as exc:
            add_error(form, exc)
        else:
            prefix = '原办理已保存' if replayed else '已保存本次办理'
            messages.success(request, f'{prefix}，记录 #{obj.pk}。')
            return redirect('dispensing_detail', pk=case.pk)
    return clinical_render(request, 'clinical/dispensing_confirm.html', dict(
        case=case, visit=case.visit, form=form, label='核对发药办理结果',
    ), status=409)
