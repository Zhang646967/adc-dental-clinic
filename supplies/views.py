"""Ordinary staff HTML entry points for stock and nursing rehearsal."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_http_methods

from adc_core.http_support import EXPECTED_ERRORS, add_error
from clinical.pharmacy_models import DispenseMovement
from clinical.plan_models import PerformedProcedure
from equipment.forms import ExplicitProposalForm
from scheduling.models import Visit
from supplies import nursing, stock
from supplies.access import duties, nurse, require_enabled, warehouse
from supplies.forms import ExecutionForm, LotActionForm, PackHoldForm, PackReleaseForm, ReceiptForm
from supplies.models import NursingDuty, NursingExecution, SterilePack, StockItem, StockLot, StockMovement
from workspaces.views import select_clinic

STOCK_LABELS={'RECEIPT':'登记到货','RECALL':'登记批次召回','WASTE':'登记批次报损','REVERSE':'冲回原记录'}
PACK_LABELS={'RELEASE':'放行无菌包','HOLD':'停用无菌包'}
EXECUTION_LABELS=dict(NursingExecution.Kind.choices)


def _page(rows,request):
    return Paginator(rows,20).get_page(request.GET.get('page'))


def _preview(request,label,token,summary,recovery_route):
    return render(request,'business/proposal.html',dict(
        title=label,summary=summary,recovery_route=recovery_route,
        form=ExplicitProposalForm(initial={'proposal_token':token}),button='确认保存办理结果',
    ))


def _confirm(request,command,route,*,return_args=None,**kwargs):
    form=ExplicitProposalForm(request.POST)
    if form.is_valid():
        try:
            result,replayed=command(request.user,form.cleaned_data['proposal_token'],True,**kwargs)
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            prefix='原办理已保存' if replayed else '已保存本次办理'
            messages.success(request,f'{prefix}，记录 #{result.pk}。')
            return redirect(route,**(return_args or {}))
    return render(request,'business/proposal.html',dict(
        title='核对本次办理',form=form,recovery_route=route if not return_args else
        ('stock_queue' if route=='stock_detail' else 'nursing_queue'),button='确认保存办理结果',
    ),status=409)


def _items(request):
    clinic=request.workspace.clinic_id
    return StockItem.objects.filter(clinic_id=clinic,kind__in=warehouse(request.user,clinic))


@login_required
@never_cache
@require_GET
def stock_queue(request):
    require_enabled()
    if request.workspace.clinic_id is None:
        return select_clinic(request)
    today=timezone.localdate()
    lots=stock.lot_choices(_items(request)).annotate(
        quarantined=Sum('movements__quantity',filter=Q(movements__kind='QUARANTINE'),default=0),
    )
    return render(request,'supplies/stock_queue.html',dict(page=_page(lots,request),today=today))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def stock_receive(request):
    items=_items(request)
    if request.POST.get('action')=='confirm':
        return _confirm(request,stock.confirm,'stock_queue',expected_action='RECEIPT')
    form=ReceiptForm(request.POST or None,items=items)
    if request.method=='POST' and form.is_valid():
        values=form.cleaned_data
        try:
            data,token=stock.prepare(request.user,'RECEIPT',dict(values,item=values['item'].pk,expires_on=values['expires_on'].isoformat()))
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            return _preview(request,STOCK_LABELS['RECEIPT'],token,[
                ('库存条目',values['item']),('批号',data['code']),('有效期至',data['expires_on']),
                ('数量',data['quantity']),('到货凭据',data['reference']),('办理依据',data['reason']),
            ],'stock_queue')
    return render(request,'supplies/stock_receive.html',dict(form=form,has_items=items.exists()))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def stock_detail(request,pk):
    lot=get_object_or_404(stock.lot_choices(_items(request)),pk=pk)
    if request.POST.get('action')=='confirm':
        return _confirm(request,stock.confirm,'stock_detail',return_args={'pk':pk},expected_lot=pk)
    moves=lot.movements.select_related('actor','reverses').order_by('-pk')
    traces=moves.filter(kind__in=['ISSUE','USE']).select_related(
        'dispense__line__quote__approval__version__prescription__visit__patient','execution__visit__patient',
    )
    page=_page(moves,request)
    trace_page=Paginator(traces,20).get_page(request.GET.get('trace_page'))
    affected=[]
    for row in trace_page:
        visit=row.dispense.line.quote.approval.version.prescription.visit if row.dispense_id else row.execution.visit
        affected.append(dict(visit=visit.visit_no,patient=visit.patient.patient_no,quantity=row.quantity,
                             kind=row.get_kind_display(),recorded_at=row.recorded_at))
    reversible=moves.filter(kind__in=stock.REVERSALS,reversal__isnull=True)
    posted=request.POST.get('action')
    actions=[kind for kind in ('WASTE','RECALL','REVERSE') if
        (kind!='RECALL' or not hasattr(lot,'recall')) and (kind!='REVERSE' or reversible.exists())]
    action_forms={kind:LotActionForm(request.POST if kind==posted else None,kind=kind,prefix=kind.lower(),
                                   movements=reversible if kind=='REVERSE' else ()) for kind in actions}
    form=action_forms.get(posted)
    if request.method=='POST' and form and form.is_valid():
        try:
            data,token=stock.prepare(request.user,posted,dict(form.cleaned_data,lot=lot.pk))
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            labels={'quantity':'数量','reference':'召回依据','movement':'原记录编号','reason':'办理依据'}
            return _preview(request,STOCK_LABELS[posted],token,[('批号',lot.code),('库存条目',lot.item)]+[
                (label,data[key]) for key,label in labels.items() if key in data
            ],'stock_queue')
    return render(request,'supplies/stock_detail.html',dict(
        lot=lot,page=page,affected=affected,trace_page=trace_page,today=timezone.localdate(),
        actions=[(kind,STOCK_LABELS[kind],form) for kind,form in action_forms.items()],
    ))


@login_required
@never_cache
@require_GET
def nursing_queue(request):
    require_enabled()
    clinic=request.workspace.clinic_id
    if clinic is None:
        return select_clinic(request)
    kinds=set(duties(request.user.pk).filter(clinic_id=clinic).values_list('kind',flat=True))
    if NursingDuty.Kind.STERILITY in kinds and NursingDuty.Kind.EXECUTE not in kinds:
        return redirect('sterile_packs')
    nurse(request.user,clinic,NursingDuty.Kind.EXECUTE)
    past=request.GET.get('queue')=='past'
    visits=Visit.objects.filter(clinic_id=clinic).select_related('patient')
    if past:
        visits=visits.filter(nursing_executions__isnull=False).exclude(status='CHECKED_IN').distinct()
    else:
        visits=visits.filter(status='CHECKED_IN',patient__is_active=True)
    return render(request,'supplies/nursing_queue.html',dict(
        page=_page(visits.order_by('-attended_at','-pk'),request),past=past,
        can_release=NursingDuty.Kind.STERILITY in kinds,
    ))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def nursing_detail(request,pk):
    clinic=request.workspace.clinic_id
    nurse(request.user,clinic,NursingDuty.Kind.EXECUTE)
    visit=get_object_or_404(Visit.objects.select_related('patient'),pk=pk,clinic_id=clinic)
    if request.POST.get('action')=='confirm':
        return _confirm(request,nursing.confirm,'nursing_detail',return_args={'pk':pk},visit_id=pk)
    actual=list(PerformedProcedure.objects.filter(encounter__visit=visit,state='ACTIVE').order_by('pk'))
    medicine=list(DispenseMovement.objects.filter(line__quote__approval__version__prescription__visit=visit,
                                                 requires_batch=True,kind='ISSUE').select_related('line'))
    items=StockItem.objects.filter(clinic_id=clinic,kind__in=['MATERIAL','IMPLANT'])
    lots=stock.lot_choices(items).filter(expires_on__gte=timezone.localdate(),available__gt=0,recall__isnull=True)
    packs=SterilePack.objects.filter(clinic_id=clinic,valid_until__gt=timezone.now(),hold__isnull=True,execution__isnull=True).order_by('pk')
    kinds=[]
    if visit.status=='CHECKED_IN' and visit.patient.is_active and not settings.ADC_READ_ONLY:
        kinds=['ESCALATE']
        if actual and lots.exists():
            kinds.insert(0,'MATERIAL')
        if actual and packs.exists():
            kinds.insert(0,'STERILE')
        if medicine:
            kinds.insert(0,'ADMINISTER')
    posted=request.POST.get('action')
    action_forms={kind:ExecutionForm(request.POST if kind==posted else None,kind=kind,prefix=kind.lower(),
                                    actuals=actual,lots=lots,packs=packs,issues=medicine) for kind in kinds}
    form=action_forms.get(posted)
    if request.method=='POST' and form and form.is_valid():
        values=form.cleaned_data
        try:
            data,token=nursing.prepare(request.user,visit,posted,dict(values,observed_at=values['observed_at'].isoformat()))
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            summary=[('患者编号',visit.patient.patient_no),('就诊',visit.visit_no),('实际发生',timezone.localtime(values['observed_at'])),
                     ('数量',data['quantity']),('实际执行依据',data['reason'])]
            for key in ('performed','issue','lot','pack'):
                if key in data:
                    field=form.fields[key]
                    summary.append((field.label,dict(field.choices)[data[key]]))
            return _preview(request,EXECUTION_LABELS[posted],token,summary,'nursing_queue')
    return render(request,'supplies/nursing_detail.html',dict(
        visit=visit,actions=[(kind,EXECUTION_LABELS[kind],form) for kind,form in action_forms.items()],
        page=_page(visit.nursing_executions.select_related('actor','sterile_pack','stock_movement__lot','issue__line','performed').order_by('-pk'),request),
    ))


@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def sterile_packs(request):
    clinic=request.workspace.clinic_id
    nurse(request.user,clinic,NursingDuty.Kind.STERILITY)
    if request.POST.get('action')=='confirm':
        return _confirm(request,nursing.confirm_pack,'sterile_packs')
    packs=SterilePack.objects.filter(clinic_id=clinic).select_related('hold','execution','released_by').order_by('-pk')
    posted=request.POST.get('action')
    release=PackReleaseForm(request.POST if posted=='RELEASE' else None,prefix='release')
    hold=PackHoldForm(request.POST if posted=='HOLD' else None,prefix='hold',packs=packs.filter(hold__isnull=True))
    form={'RELEASE':release,'HOLD':hold}.get(posted)
    if request.method=='POST' and form and form.is_valid():
        values=dict(form.cleaned_data)
        if posted=='RELEASE':
            fields=dict(values,processed_at=values['processed_at'].isoformat(),valid_until=values['valid_until'].isoformat())
            labels=[('无菌包',values['code']),('灭菌依据',values['reference']),('实际灭菌时间',values['processed_at']),
                    ('有效截止',values['valid_until'])]
        else:
            fields=dict(values,pack=values['pack'].pk)
            labels=[('无菌包',values['pack'].code),('停用依据',values['reason'])]
        try:
            _,token=nursing.prepare_pack(request.user,clinic,posted,fields)
        except EXPECTED_ERRORS as exc:
            add_error(form,exc)
        else:
            return _preview(request,PACK_LABELS[posted],token,labels,'sterile_packs')
    return render(request,'supplies/sterile_packs.html',dict(
        page=_page(packs,request),now=timezone.now(),actions=[('RELEASE',PACK_LABELS['RELEASE'],release),
                                                           ('HOLD',PACK_LABELS['HOLD'],hold)],
    ))
