from datetime import timedelta
from urllib.parse import urlencode
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import render, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods
from adc_core.http_support import EXPECTED_ERRORS, add_error
from portal import rescheduling as services
from portal.reschedule_forms import SearchForm, PreviewForm, ConfirmForm
from coordination.models import WaitOffer
from scheduling.models import Visit


def _context(actor, visit):
    d = services.related_context(actor, visit)
    offers = WaitOffer.objects.filter(request__patient_id=visit.patient_id,
        request__clinic_id=visit.clinic_id, state='PENDING', request__state='OFFERED',
        expires_at__gt=timezone.now()).select_related('slot__dentist').order_by('expires_at')
    if d['source_plan']:
        offers = offers.filter(request__service_id=d['source_plan'].service_id)
    d['offers'] = list(offers[:5])
    return dict(visit=visit, **d)


@login_required(login_url='portal_login')
@never_cache
@sensitive_post_parameters('proposal_token', 'reason')
@require_http_methods(['GET', 'POST'])
def reschedule(request, pk):
    try: visit = services.owned_visit(request.user, pk)
    except Visit.DoesNotExist: raise Http404
    context = _context(request.user, visit)
    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        form = ConfirmForm(request.POST)
        if form.is_valid():
            try:
                new, repeated = services.confirm(actor=request.user, visit_id=visit.pk,
                    proposal_token=form.cleaned_data['proposal_token'], confirmed=form.cleaned_data['confirmed'])
            except EXPECTED_ERRORS as exc: add_error(form, exc)
            else:
                messages.success(request, '这次确认已经办妥，以下是已保存结果。' if repeated else '改期成功，原预约和资源历史已保留，请按新安排就诊。')
                return redirect('portal_visit', pk=new.pk)
        context['visit'].refresh_from_db()
        context.update(services.related_context(request.user, context['visit']), form=form)
        return render(request, 'portal/reschedule_recovery.html', context, status=409)
    try: services.check_source(visit)
    except EXPECTED_ERRORS as exc:
        return render(request, 'portal/reschedule_recovery.html', dict(context, problem=str(exc)), status=409)
    if request.method == 'POST':
        form = PreviewForm(request.POST)
        if form.is_valid():
            try:
                d = form.cleaned_data
                preview = services.prepare(actor=request.user, visit_id=visit.pk,
                    expected_version=d['expected_version'], slot_id=d['slot_id'], start=d['start'],
                    reason=d['reason'], offer_id=d['offer_id'])
            except EXPECTED_ERRORS as exc: add_error(form, exc)
            else:
                return render(request, 'portal/reschedule_confirm.html', dict(context, preview=preview,
                    form=ConfirmForm(initial={'proposal_token': preview['proposal_token']})))
        return render(request, 'portal/reschedule_recovery.html', dict(context, form=form), status=409)

    today = timezone.localdate()
    day = max(today, min(timezone.localtime(visit.scheduled_start).date(), today+timedelta(days=14)))
    search = SearchForm({'day': day.isoformat()} | request.GET.dict(), visit=visit)
    result = None; selection = None; form = None
    if search.is_valid():
        try:
            if not request.GET.get('offer'):
                result = services.options(actor=request.user, visit_id=visit.pk,
                    day=search.cleaned_data['day'], dentist_id=search.cleaned_data['dentist'].pk if search.cleaned_data['dentist'] else None)
                for row in result['rows']:
                    row['choose_url'] = reverse('portal_reschedule', args=[pk])+'?'+urlencode(dict(
                        day=search.cleaned_data['day'].isoformat(), dentist=request.GET.get('dentist', ''),
                        slot=row['slot_id'], start=row['start_iso']))
            if request.GET.get('offer'):
                offer, plan = services._offer(visit, int(request.GET['offer']))
                selection = dict(slot_id=offer.slot_id, start=offer.starts_at, end=offer.ends_at,
                    dentist=offer.slot.dentist.name, offer_id=offer.pk, offer=offer)
            elif request.GET.get('slot'):
                selection = next((r for r in result['rows'] if str(r['slot_id']) == request.GET['slot'] and r['start_iso'] == request.GET.get('start')), None)
                if selection is None:
                    search.add_error(None, '刚才选择的时段已不可用，请重新查询；原预约保留。')
            if selection:
                form = PreviewForm(initial=dict(expected_version=visit.lock_version, slot_id=selection['slot_id'],
                    start=selection['start'], offer_id=selection.get('offer_id')))
        except (ValueError, *EXPECTED_ERRORS) as exc:
            if isinstance(exc, ValueError): search.add_error(None, '请选择当前本人有效邀约。')
            else: add_error(search, exc)
    return render(request, 'portal/reschedule.html', dict(context, search=search, result=result,
        selection=selection, form=form), status=200 if not search.errors else 400)
