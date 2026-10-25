"""Native WeChat patient channel. Shared commands own every booking effect.

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
from django.http import JsonResponse,Http404
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.debug import sensitive_post_parameters
from accounts.models import UserAccount
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from portal.models import PatientAccess
from portal.policies import patient_access, has_patient_access, subject_choices, SubjectRequired
from portal import mini_forms as forms, services, rescheduling
from portal.service_catalogue import public_profiles, public_profile, require_self_service
from portal.service_projection import service_data
from registry.models import Clinic
from scheduling.models import AvailabilitySlot, Visit
from scheduling.resource_models import ResourcePolicy
from scheduling.resources import current_plan
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


def endpoint(methods=('GET',), *, public=False, subject_optional=False):
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
                        return result(request, status=401, code='LOGIN_REQUIRED', message='请先登录患者账号。')
                    if not subject_optional:patient_access(request.user)
                return view(request, *args, **kwargs)
            except SubjectRequired as exc:
                return result(request,status=409,code='SUBJECT_REQUIRED',message=str(exc))
            except PermissionDenied:
                return result(request, status=403, code='ACCESS_DENIED', message='当前账号或患者授权已失效，请重新登录或联系前台。')
            except (ObjectDoesNotExist,Http404):
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
    from accounts.auth_providers import capabilities
    data = dict(authenticated=False, csrf_token=get_token(request), read_only=settings.ADC_READ_ONLY,
        auth_capabilities=capabilities(),
        account_authenticated=False,identity_provider='local' if settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_PATIENT_IDENTITY_PROVIDER=='local' else 'disabled',
        environment_label=settings.ADC_PUBLIC_ENVIRONMENT_LABEL,
        business_timezone='Asia/Shanghai', today=timezone.localdate().isoformat(),
        last_day=(timezone.localdate()+timedelta(days=14)).isoformat())
    if request.user.is_authenticated:
        ctx = ensure_context(request)
        attach(request, ctx)
        if ctx.login_channel=='PATIENT':
            from portal.account_access import account_data
            try:data.update(account_data(request))
            except PermissionDenied:pass
        if valid_context(request.user, ctx) and ctx.role == 'PATIENT':
            data.update(authenticated=True,workspace_token=token_for(ctx),workspace_id=str(ctx.pk),subject_revision=ctx.revision,
                subject_required=False,patient_name='',subject_key=None,acting_capacity='',delegated=False)
            try:
                access = patient_access(request.user)
                data.update(patient_name=access.patient.name,subject_key=access.pk if access.delegated else 'self',
                    delegated=access.delegated,acting_capacity=(access.source.relationship.get_kind_display()+' · '+access.source.relationship.clinic.public_contact['name']) if access.delegated else '本人')
            except SubjectRequired:data['subject_required']=True
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
        from portal.account_access import can_account_login
        if not can_account_login(user):
            raise PermissionDenied
        login(request, user)
        request.session.set_expiry(3600)
        begin_login_workspace(request,channel='PATIENT')
        # This endpoint explicitly selects only the authorized patient role,
        # including for a person who also has an employee role.
        if has_patient_access(user) and request.workspace.role != 'PATIENT':
            apply_role(request, request.workspace, 'PATIENT')
    return result(request, session_data(request))


@endpoint(('POST',), public=True)
def sign_out(request):
    logout(request)
    return result(request, session_data(request))


def visit_data(visit, *, actor=None):
    plan = current_plan(visit)
    contact=(plan.snapshot.get('public_clinic') if plan else None) or dict(name=visit.clinic.name,address=visit.clinic.postal_address,phone=visit.clinic.phone)
    successor = Visit.objects.filter(replaces_visit_id=visit.pk, patient_id=visit.patient_id).values_list('pk', flat=True).first()
    return dict(id=visit.pk, clinic_id=visit.clinic_id, clinic=contact['name'],
        dentist=visit.dentist.name, start=visit.scheduled_start.isoformat(), end=visit.scheduled_end.isoformat(),
        status=visit.status, status_label=visit.get_status_display(), version=visit.lock_version,
        service=(plan.snapshot.get('service', {}).get('name') or plan.service.name) if plan else '常规预约',
        service_id=plan.service_id if plan else None, predecessor=visit.replaces_visit_id, successor=successor,
        can_change=visit.status == 'SCHEDULED' and visit.scheduled_start > timezone.now(),
        address=contact['address'], phone=contact['phone'],
        patient_request=visit.chief_complaint if actor and not patient_access(actor).delegated else '')


def option_data(row):
    slot = row['slot']
    return dict(id=f"{slot.pk}:{row['start'].isoformat()}", slot=slot.pk, clinic=slot.clinic.public_contact['name'], dentist=slot.dentist.name,
        start=row['start'].isoformat(), end=row['end'].isoformat(),
        service=row['service'].pk if row.get('service') else None)


@endpoint()
def catalogue(request):
    access=patient_access(request.user)
    clinics_qs=Clinic.objects.filter(is_active=True)
    if access.delegated:clinics_qs=clinics_qs.filter(pk=access.clinic_id)
    from registry.branch_projection import public_contact
    clinics = [dict(id=c.pk,name=public_contact(c)['name'],postal_address=public_contact(c)['address'],phone=public_contact(c)['phone'])
        for c in clinics_qs.select_related('public_directory')]
    offerings = [service_data(p,actor=request.user) for p in public_profiles(clinic_id=access.clinic_id)]
    return result(request, dict(clinics=clinics, offerings=offerings,
        services=[s for s in offerings if s['self_booking']],
        resource_clinics=list(ResourcePolicy.objects.filter(state='ENABLED').values_list('clinic_id', flat=True))))


@endpoint()
def service_detail(request, pk):
    profile=public_profile(pk)
    patient_access(request.user).require_clinic(profile.service.department.clinic_id)
    return result(request, service_data(profile,actor=request.user))


@endpoint()
def overview(request):
    from portal.patient_dashboard import dashboard
    d = dashboard(request.user)
    return result(request, dict(next_visit=visit_data(d['next_visit'],actor=request.user) if d['next_visit'] else None,
        active_count=d['active_count'], history_count=d['history_count'],
        waiting_count=d['waiting_count'], offer_count=d['offer_count']))


@endpoint()
def candidates(request):
    d = validated(forms.CandidateForm(request.GET))
    require_self_service(d['service'], clinic_id=d['clinic'], actor=request.user)
    rows = services.public_options(request.user, d['clinic'], d['day'], d['service'], d['dentist'])
    return result(request, dict(rows=[option_data(r) for r in rows], observed_at=timezone.now().isoformat(),
        note='候选不占位；确认时重新核对。时间均为北京时间。'))


@endpoint()
def visits(request):
    access = patient_access(request.user)
    d = validated(forms.PageForm(request.GET))
    qs = access.scope(Visit.objects.all()).select_related('clinic', 'dentist')
    queue = d['queue'] or 'active'
    if queue == 'active': qs = qs.filter(status__in=('SCHEDULED', 'CHECKED_IN')).order_by('scheduled_start', 'pk')
    elif queue == 'history': qs = qs.exclude(status__in=('SCHEDULED', 'CHECKED_IN')).order_by('-scheduled_start', '-pk')
    else: qs = qs.order_by('-scheduled_start', '-pk')
    page = Paginator(qs, 10).get_page(d['page'] or 1)
    return result(request, dict(rows=[visit_data(v,actor=request.user) for v in page], page=page.number, pages=page.paginator.num_pages))


@endpoint()
def detail(request, pk):
    visit = rescheduling.owned_visit(request.user, pk)
    data = visit_data(visit,actor=request.user)
    plan = current_plan(visit)
    # Own historical service, deliberately absent from the general catalogue.
    if plan:
        dentists = plan.service.dentists.filter(is_active=True)
    else:
        from registry.models import Dentist
        dentists = Dentist.objects.filter(is_active=True, pk__in=AvailabilitySlot.objects.filter(
            clinic_id=visit.clinic_id, is_active=True, ends_at__gt=timezone.now()).values('dentist_id'))
    data['reschedule_service'] = dict(id=data['service_id'], name=data['service'], clinic=visit.clinic_id,
        duration=plan.service.duration_minutes if plan else int((visit.scheduled_end-visit.scheduled_start).total_seconds()/60),
        dentists=list(dentists.values('id', 'name')))
    return result(request, data)


@sensitive_post_parameters('patient_request')
@endpoint(('POST',))
def book_preview(request):
    d = validated(forms.BookingPreviewForm(request.POST))
    with reporting_snapshot():
        profile = require_self_service(d['service'],actor=request.user)
        slot, end, token = services.preview_booking(user=request.user, slot_id=d['slot'], start=d['start'], service_id=d['service'])
        if profile.service.department.clinic_id != slot.clinic_id:
            raise RuleError('服务与所选诊所不一致，请重新选择。')
        offering = service_data(profile,actor=request.user)
        wrapped = proposal(request.user, BOOK, ('PATIENT',), dict(token=token, patient_request=d['patient_request']))
        return result(request, dict(proposal_token=wrapped, clinic=slot.clinic.public_contact['name'], dentist=slot.dentist.name,
            start=d['start'].isoformat(), end=end.isoformat(), service=offering['name'],
            fee_label=offering['fee_label'], fee_note=offering['fee_note'],
            preparation=offering['preparation'], patient_request=d['patient_request']))


@endpoint(('POST',))
def book_confirm(request):
    d = validated(forms.ConfirmationForm(request.POST))
    p = read_proposal(request.user, BOOK, ('PATIENT',), d['proposal_token'])
    visit = services.confirm_booking(actor=request.user, token=p['data']['token'],
        patient_request=p['data'].get('patient_request', ''), require_published_service=True)
    return result(request, visit_data(visit,actor=request.user))


@endpoint(('POST',))
def cancel_preview(request, pk):
    d = validated(forms.CancellationPreviewForm(request.POST))
    visit = rescheduling.owned_visit(request.user, pk)
    rescheduling.check_source(visit)
    from adc_core.commands import assert_revision
    assert_revision(visit, d['expected_version'])
    token = proposal(request.user, CANCEL, ('PATIENT',), dict(visit=pk, **d))
    return result(request, dict(original=visit_data(visit,actor=request.user), reason=d['reason'], proposal_token=token))


@endpoint(('POST',))
def cancel_confirm(request, pk):
    d = validated(forms.ConfirmationForm(request.POST))
    prepared = read_proposal(request.user, CANCEL, ('PATIENT',), d['proposal_token'])
    p=prepared['data']
    if p['visit'] != pk: raise RuleError('确认内容不属于这条预约，请重新核对。')
    visit = services.cancel_booking(actor=request.user, visit_id=pk, expected_version=p['expected_version'], reason=p['reason'],authority=prepared['binding']['patient_authority'])
    return result(request, visit_data(visit,actor=request.user))


@endpoint()
def reschedule_candidates(request, pk):
    visit = rescheduling.owned_visit(request.user, pk)
    from portal.reschedule_forms import SearchForm
    d = validated(SearchForm(request.GET, visit=visit))
    observation = rescheduling.options(actor=request.user, visit_id=pk, day=d['day'],
        dentist_id=d['dentist'].pk if d['dentist'] else None)
    return result(request, dict(rows=[option_data(r) for r in observation['rows']], limited=observation['limited'],
        note=observation['limit_reason'], original=visit_data(visit,actor=request.user)))


@endpoint(('POST',))
def reschedule_preview(request, pk):
    d = validated(forms.PreviewForm(request.POST))
    prepared = rescheduling.prepare(actor=request.user, visit_id=pk, expected_version=d['expected_version'],
        slot_id=d['slot_id'], start=d['start'], reason=d['reason'], offer_id=d['offer_id'])
    return result(request, dict(original=visit_data(prepared['original'],actor=request.user), proposal_token=prepared['proposal_token'],
        clinic=(prepared.get('resources') or {}).get('public_clinic',prepared['destination'].clinic.public_contact)['name'], dentist=prepared['destination'].dentist.name,
        start=prepared['start'].isoformat(), end=prepared['end'].isoformat(), reason=prepared['reason'],
        duration_changed=prepared['duration_changed']))


@endpoint(('POST',))
def reschedule_confirm(request, pk):
    d = validated(forms.ConfirmationForm(request.POST))
    visit, replayed = rescheduling.confirm(actor=request.user, visit_id=pk, proposal_token=d['proposal_token'], confirmed=True)
    return result(request, dict(visit=visit_data(visit,actor=request.user), replayed=replayed))


@endpoint(subject_optional=True)
def subjects(request):
    return result(request,dict(rows=subject_choices(request.user)))


@endpoint(('POST',),subject_optional=True)
def select_subject(request):
    from portal.relationships import select_subject as select
    select(actor=request.user,key=request.POST.get('subject',''))
    request.session.pop('adc_guide',None);request.session.pop('adc_booking_intent',None)
    return result(request,session_data(request))
