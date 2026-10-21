"""Native views of the existing waitlist. Coordination owns all business effects."""
from datetime import datetime, timedelta
from django.db import transaction
from django.core.paginator import Paginator
from django.utils import timezone
from accounts.policies import require_writable
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from care.models import AuditEvent
from coordination import services
from coordination.models import WaitRequest, WaitOffer
from coordination.reservations import lock_resources
from coordination.windows import validate_wait_window, WindowError
from portal import mini_forms as forms
from portal.mini_api import endpoint, result, validated, visit_data
from portal.policies import patient_access
from registry.models import Clinic, Dentist
from scheduling.models import Visit
from scheduling.resource_models import ResourcePlan
from scheduling.resources import policy, service_for

JOIN = 'adc.mini.wait.join.v1'
ACTION = 'adc.mini.wait.action.v1'


def owned(actor):
    return WaitRequest.objects.filter(patient_id=patient_access(actor).patient_id).select_related('clinic', 'service', 'preferred_dentist')


def offer_data(offer):
    active = offer.state == 'PENDING' and offer.request.state == 'OFFERED' and offer.expires_at > timezone.now()
    plan = ResourcePlan.objects.filter(offer=offer).order_by('-version', '-pk').first()
    label = (plan.snapshot.get('service', {}).get('name') if plan else None) or (offer.request.service.name if offer.request.service_id else '常规预约')
    return dict(id=offer.pk, slot=offer.slot_id, clinic=offer.request.clinic.name, dentist=offer.slot.dentist.name,
        service=label,
        start=offer.starts_at.isoformat(), end=offer.ends_at.isoformat(), expires=offer.expires_at.isoformat(),
        state=offer.state, status_label='已到期，待前台重新安排' if offer.state == 'PENDING' and not active else offer.get_state_display(),
        active=active, visit=visit_data(offer.visit) if offer.visit_id else None)


def wait_data(entry):
    offers = entry.offers.select_related('request__clinic', 'request__service', 'slot__dentist', 'visit__clinic', 'visit__dentist').order_by('-pk')[:5]
    return dict(id=entry.pk, clinic_id=entry.clinic_id, clinic=entry.clinic.name, service=entry.service.name if entry.service_id else '常规预约',
        dentist=entry.preferred_dentist.name if entry.preferred_dentist_id else '不限医师',
        earliest=entry.earliest.isoformat(), latest=entry.latest.isoformat(),
        state=entry.state, status_label=entry.get_state_display(), revision=entry.revision,
        can_withdraw=entry.state in ('WAITING', 'OFFERED'), offers=[offer_data(o) for o in offers])


@endpoint()
def listing(request):
    d = validated(forms.PageForm(request.GET))
    qs = owned(request.user).order_by('-pk')
    page = Paginator(qs, 10).get_page(d['page'] or 1)
    return result(request, dict(rows=[wait_data(e) for e in page], page=page.number, pages=page.paginator.num_pages,
        has_open=qs.filter(state__in=('WAITING', 'OFFERED')).exists()))


def join_values(actor, d):
    Clinic.objects.get(pk=d['clinic'], is_active=True)
    resource_policy = policy(d['clinic'])
    if d['service'] and resource_policy is None:
        raise RuleError('所选服务不属于本店当前服务目录，请重新选择。')
    service = service_for(d['clinic'], d['service']) if resource_policy else None
    if resource_policy and resource_policy.state != 'ENABLED':
        raise RuleError('诊所资源尚在核对，请联系前台协助。')
    if service and (not service.is_active or not service.department.is_active or
            d['dentist'] and not service.dentists.filter(pk=d['dentist'], is_active=True).exists()):
        raise RuleError('服务或医师偏好已变化，请重新选择。')
    if d['dentist']: Dentist.objects.get(pk=d['dentist'], is_active=True)
    try:
        validate_wait_window(d['earliest'], d['latest'], now=timezone.now(),
            minimum=timedelta(minutes=service.duration_minutes if service else 30))
    except WindowError as exc:
        raise RuleError(str(exc)) from exc
    return service


@endpoint(('POST',))
def join_preview(request):
    d = validated(forms.WaitJoinForm(request.POST))
    service = join_values(request.user, d)
    qs = owned(request.user)
    if qs.filter(state__in=('WAITING', 'OFFERED')).exists():
        raise RuleError('你已有有效候补，请先查看或退出原记录。')
    data = dict(clinic=d['clinic'], service=d['service'], dentist=d['dentist'],
        earliest=d['earliest'].isoformat(), latest=d['latest'].isoformat(),
        last_entry=qs.order_by('-pk').values_list('pk', flat=True).first(),
        duration=service.duration_minutes if service else 30)
    return result(request, dict(clinic=Clinic.objects.get(pk=d['clinic']).name,
        service=service.name if service else '常规预约', dentist=Dentist.objects.get(pk=d['dentist']).name if d['dentist'] else '不限医师',
        start=data['earliest'], end=data['latest'], proposal_token=proposal(request.user, JOIN, ('PATIENT',), data)))


@transaction.atomic
def register(actor, token):
    require_writable(actor)
    access = patient_access(actor, lock=True)
    p = read_proposal(actor, JOIN, ('PATIENT',), token)
    lock_resources(patients=[access.patient_id])
    # The existing immutable audit row is also the exact native request receipt.
    # The patient lock serializes confirmations; a replay returns current history,
    # including a later withdrawal, rather than re-registering the old preference.
    prior = AuditEvent.objects.filter(actor=actor, event_type='MINI_WAIT_REGISTERED',
        subject_type='waitrequest', change_summary__operation=p['operation']).first()
    if prior:
        return owned(actor).get(pk=prior.subject_key)
    d = p['data']
    if owned(actor).order_by('-pk').values_list('pk', flat=True).first() != d['last_entry']:
        raise RuleError('候补记录已经变化，请先查看办理结果，再重新登记。')
    values = dict(d, earliest=datetime.fromisoformat(d['earliest']), latest=datetime.fromisoformat(d['latest']))
    service = join_values(actor, values)
    if (service.duration_minutes if service else 30) != d['duration']:
        raise RuleError('服务时长已变化，请重新核对候补范围。')
    entry = services.join_waitlist(actor=actor, clinic_id=d['clinic'], service_id=d['service'], dentist_id=d['dentist'],
        earliest=values['earliest'], latest=values['latest'])
    emit(actor, 'MINI_WAIT_REGISTERED', entry, summary={'operation': p['operation']})
    return entry


@endpoint(('POST',))
def join_confirm(request):
    d = validated(forms.ConfirmationForm(request.POST))
    return result(request, dict(kind='waitlist', wait=wait_data(register(request.user, d['proposal_token']))))


@endpoint(('POST',))
def withdraw_preview(request, pk):
    entry = owned(request.user).get(pk=pk)
    if entry.state not in ('WAITING', 'OFFERED'): raise RuleError('这条候补已结束，请核对当前结果。')
    token = proposal(request.user, ACTION, ('PATIENT',), dict(entry=pk, revision=entry.revision, action='withdraw'))
    return result(request, dict(wait=wait_data(entry), proposal_token=token))


@endpoint(('POST',))
def withdraw_confirm(request, pk):
    d = validated(forms.ConfirmationForm(request.POST))
    p = read_proposal(request.user, ACTION, ('PATIENT',), d['proposal_token'])['data']
    if p.get('entry') != pk or p['action'] != 'withdraw': raise RuleError('确认内容不属于本次操作。')
    owned(request.user).get(pk=pk)
    entry = services.withdraw(actor=request.user, entry_id=pk, expected_revision=p['revision'])
    return result(request, dict(kind='waitlist', wait=wait_data(entry)))


def own_offer(actor, pk):
    return WaitOffer.objects.select_related('request__clinic', 'request__service', 'slot__dentist',
        'visit__clinic', 'visit__dentist').get(pk=pk, request__in=owned(actor))


@endpoint()
def detail(request, pk):
    offer = own_offer(request.user, pk)
    sources = Visit.objects.filter(patient_id=offer.request.patient_id, clinic_id=offer.request.clinic_id,
        status='SCHEDULED', scheduled_start__gt=timezone.now()).select_related('clinic', 'dentist')
    if offer.request.service_id:
        sources = sources.filter(resource_plans__is_current=True, resource_plans__service_id=offer.request.service_id)
    return result(request, dict(offer=offer_data(offer), sources=[visit_data(v) for v in sources.distinct().order_by('scheduled_start', 'pk')[:10]]))


@endpoint(('POST',))
def answer_preview(request, pk):
    d = validated(forms.OfferAnswerForm(request.POST))
    offer = own_offer(request.user, pk)
    if not offer_data(offer)['active']: raise RuleError('邀约已处理或到期，请先查看当前结果。')
    token = proposal(request.user, ACTION, ('PATIENT',), dict(offer=pk, action=d['action'], revision=offer.request.revision))
    return result(request, dict(**offer_data(offer), action=d['action'], proposal_token=token))


@endpoint(('POST',))
def answer_confirm(request, pk):
    d = validated(forms.ConfirmationForm(request.POST))
    p = read_proposal(request.user, ACTION, ('PATIENT',), d['proposal_token'])['data']
    if p.get('offer') != pk or p['action'] not in ('accept', 'decline'): raise RuleError('确认内容不属于本次邀约。')
    own_offer(request.user, pk)
    offer = services.answer_offer(actor=request.user, offer_id=pk, accept=p['action'] == 'accept', expected_revision=p['revision'])
    return result(request, dict(kind='visit' if offer.visit_id else 'waitlist', visit=visit_data(offer.visit) if offer.visit_id else None,
        wait=wait_data(owned(request.user).get(pk=offer.request_id))))
