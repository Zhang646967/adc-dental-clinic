"""Native WeChat course channel. Shared business commands own every booking effect.

Standard Django sessions, CSRF and signed workspace contexts are retained. This
is assigned-account login, not WeChat identity verification or phone registration.
"""
from datetime import timedelta
from functools import wraps
from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from accounts.models import UserAccount
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from portal.models import PatientAccess
from portal.policies import patient_access
from portal import mini_forms as forms, services, rescheduling
from registry.models import Clinic
from scheduling.models import AvailabilitySlot, Visit
from scheduling.resource_models import BookingService, ResourcePolicy
from scheduling.resources import current_plan, service_for
from workspaces.activation import begin_login_workspace, apply_role
from workspaces.context import ensure_context, token_for, valid_context, attach

BOOK = 'adc.mini.booking.v1'
CANCEL = 'adc.mini.cancel.v1'


def result(request, data=None, *, status=200, code=None, message=None):
    payload = dict(ok=code is None, request_id=getattr(request, 'adc_request_id', ''))
    if code: payload.update(code=code, message=message)
    else: payload['data'] = data
    response = JsonResponse(payload, status=status)
    response['Cache-Control'] = 'no-store'
    return response


def endpoint(methods=('GET',), *, public=False):
    def decorate(view):
        @wraps(view)
        def handle(request, *args, **kwargs):
            if request.method not in methods:
                response = result(request, status=405, code='METHOD', message='请求方式不正确。')
                response['Allow'] = ', '.join(methods)
                return response
            try:
                if not public:
                    if not request.user.is_authenticated:
                        return result(request, status=401, code='LOGIN_REQUIRED', message='请先登录课程患者账号。')
                    patient_access(request.user)
                return view(request, *args, **kwargs)
            except PermissionDenied:
                return result(request, status=403, code='ACCESS_DENIED', message='当前账号或患者授权已失效，请重新登录或联系前台。')
            except ObjectDoesNotExist:
                return result(request, status=404, code='NOT_FOUND', message='记录不存在或不属于当前患者，请返回清单核对。')
            except RuleError as exc:
                return result(request, status=409, code='BUSINESS_CONFLICT', message=str(exc))
        return handle
    return decorate


def validated(form):
    if not form.is_valid():
        raise RuleError('；'.join(str(e) for errors in form.errors.values() for e in errors))
    return form.cleaned_data


def session_data(request):
    data = dict(authenticated=False, csrf_token=get_token(request), read_only=settings.ADC_READ_ONLY,
        business_timezone='Asia/Shanghai', today=timezone.localdate().isoformat(),
        last_day=(timezone.localdate()+timedelta(days=14)).isoformat())
    if request.user.is_authenticated:
        ctx = ensure_context(request)
        attach(request, ctx)
        if valid_context(request.user, ctx) and ctx.role == 'PATIENT':
            access = patient_access(request.user)
            data.update(authenticated=True, patient_name=access.patient.name, workspace_token=token_for(ctx))
    return data


@endpoint(public=True)
def session(request):
    return result(request, session_data(request))


@sensitive_post_parameters('password')
@endpoint(('POST',), public=True)
def sign_in(request):
    form = AuthenticationForm(request, data=request.POST)
    if not form.is_valid():
        return result(request, status=401, code='LOGIN_FAILED', message='账号或密码不正确，或账号已停用。')
    user = form.get_user()
    with transaction.atomic():
        UserAccount.objects.select_for_update().get(pk=user.pk, is_active=True)
        if not PatientAccess.objects.select_for_update().filter(user=user, is_active=True, patient__is_active=True).exists():
            raise PermissionDenied
        login(request, user)
        request.session.set_expiry(3600)
        begin_login_workspace(request)
        # This endpoint explicitly selects only the authorized patient role,
        # including for a person who also has an employee role.
        if request.workspace.role != 'PATIENT':
            apply_role(request, request.workspace, 'PATIENT')
    return result(request, session_data(request))


@endpoint(('POST',), public=True)
def sign_out(request):
    logout(request)
    return result(request, session_data(request))


def visit_data(visit):
    plan = current_plan(visit)
    successor = Visit.objects.filter(replaces_visit_id=visit.pk, patient_id=visit.patient_id).values_list('pk', flat=True).first()
    return dict(id=visit.pk, clinic_id=visit.clinic_id, clinic=visit.clinic.name,
        dentist=visit.dentist.name, start=visit.scheduled_start.isoformat(), end=visit.scheduled_end.isoformat(),
        status=visit.status, status_label=visit.get_status_display(), version=visit.lock_version,
        service=plan.service.name if plan else '常规预约',
        service_id=plan.service_id if plan else None, predecessor=visit.replaces_visit_id, successor=successor,
        can_change=visit.status == 'SCHEDULED' and visit.scheduled_start > timezone.now(),
        address=visit.clinic.postal_address, phone=visit.clinic.phone)


def option_data(row):
    slot = row['slot']
    return dict(id=f"{slot.pk}:{row['start'].isoformat()}", slot=slot.pk, clinic=slot.clinic.name, dentist=slot.dentist.name,
        start=row['start'].isoformat(), end=row['end'].isoformat(),
        service=row['service'].pk if row.get('service') else None)


@endpoint()
def catalogue(request):
    clinics = list(Clinic.objects.filter(is_active=True).values('id', 'name', 'postal_address', 'phone'))
    enabled = ResourcePolicy.objects.filter(state='ENABLED').values('clinic_id')
    services_qs = BookingService.objects.filter(is_active=True, department__is_active=True,
        department__clinic_id__in=enabled, department__clinic__is_active=True).prefetch_related('dentists')
    data = []
    for service in services_qs.order_by('department__clinic_id', 'pk'):
        data.append(dict(id=service.pk, name=service.name, clinic=service.department.clinic_id,
            department=service.department.name, duration=service.duration_minutes,
            dentists=list(service.dentists.filter(is_active=True).values('id', 'name'))))
    return result(request, dict(clinics=clinics, services=data, resource_clinics=list(enabled)))


@endpoint()
def candidates(request):
    d = validated(forms.CandidateForm(request.GET))
    rows = services.public_options(request.user, d['clinic'], d['day'], d['service'], d['dentist'])
    return result(request, dict(rows=[option_data(r) for r in rows], observed_at=timezone.now().isoformat(),
        note='候选不占位；确认时重新核对。时间均为北京时间。'))


@endpoint()
def visits(request):
    access = patient_access(request.user)
    d = validated(forms.PageForm(request.GET))
    qs = Visit.objects.filter(patient_id=access.patient_id).select_related('clinic', 'dentist')
    queue = d['queue'] or 'active'
    if queue == 'active': qs = qs.filter(status__in=('SCHEDULED', 'CHECKED_IN')).order_by('scheduled_start', 'pk')
    elif queue == 'history': qs = qs.exclude(status__in=('SCHEDULED', 'CHECKED_IN')).order_by('-scheduled_start', '-pk')
    else: qs = qs.order_by('-scheduled_start', '-pk')
    page = Paginator(qs, 10).get_page(d['page'] or 1)
    return result(request, dict(rows=[visit_data(v) for v in page], page=page.number, pages=page.paginator.num_pages))


@endpoint()
def detail(request, pk):
    return result(request, visit_data(rescheduling.owned_visit(request.user, pk)))


@endpoint(('POST',))
def book_preview(request):
    d = validated(forms.BookingPreviewForm(request.POST))
    slot, end, token = services.preview_booking(user=request.user, slot_id=d['slot'], start=d['start'], service_id=d['service'])
    wrapped = proposal(request.user, BOOK, ('PATIENT',), dict(token=token))
    label = service_for(slot.clinic_id, d['service']).name if d['service'] else '常规预约'
    return result(request, dict(proposal_token=wrapped, clinic=slot.clinic.name, dentist=slot.dentist.name,
        start=d['start'].isoformat(), end=end.isoformat(), service=label))


@endpoint(('POST',))
def book_confirm(request):
    d = validated(forms.ConfirmationForm(request.POST))
    p = read_proposal(request.user, BOOK, ('PATIENT',), d['proposal_token'])
    visit = services.confirm_booking(actor=request.user, token=p['data']['token'])
    return result(request, visit_data(visit))


@endpoint(('POST',))
def cancel_preview(request, pk):
    d = validated(forms.CancellationPreviewForm(request.POST))
    visit = rescheduling.owned_visit(request.user, pk)
    rescheduling.check_source(visit)
    from adc_core.commands import assert_revision
    assert_revision(visit, d['expected_version'])
    token = proposal(request.user, CANCEL, ('PATIENT',), dict(visit=pk, **d))
    return result(request, dict(original=visit_data(visit), reason=d['reason'], proposal_token=token))


@endpoint(('POST',))
def cancel_confirm(request, pk):
    d = validated(forms.ConfirmationForm(request.POST))
    p = read_proposal(request.user, CANCEL, ('PATIENT',), d['proposal_token'])['data']
    if p['visit'] != pk: raise RuleError('确认内容不属于这条预约，请重新核对。')
    visit = services.cancel_booking(actor=request.user, visit_id=pk, expected_version=p['expected_version'], reason=p['reason'])
    return result(request, visit_data(visit))


@endpoint()
def reschedule_candidates(request, pk):
    visit = rescheduling.owned_visit(request.user, pk)
    from portal.reschedule_forms import SearchForm
    d = validated(SearchForm(request.GET, visit=visit))
    observation = rescheduling.options(actor=request.user, visit_id=pk, day=d['day'],
        dentist_id=d['dentist'].pk if d['dentist'] else None)
    return result(request, dict(rows=[option_data(r) for r in observation['rows']], limited=observation['limited'],
        note=observation['limit_reason'], original=visit_data(visit)))


@endpoint(('POST',))
def reschedule_preview(request, pk):
    d = validated(forms.PreviewForm(request.POST))
    prepared = rescheduling.prepare(actor=request.user, visit_id=pk, expected_version=d['expected_version'],
        slot_id=d['slot_id'], start=d['start'], reason=d['reason'], offer_id=d['offer_id'])
    return result(request, dict(original=visit_data(prepared['original']), proposal_token=prepared['proposal_token'],
        clinic=prepared['destination'].clinic.name, dentist=prepared['destination'].dentist.name,
        start=prepared['start'].isoformat(), end=prepared['end'].isoformat(), reason=prepared['reason'],
        duration_changed=prepared['duration_changed']))


@endpoint(('POST',))
def reschedule_confirm(request, pk):
    d = validated(forms.ConfirmationForm(request.POST))
    visit, replayed = rescheduling.confirm(actor=request.user, visit_id=pk, proposal_token=d['proposal_token'], confirmed=True)
    return result(request, dict(visit=visit_data(visit), replayed=replayed))
