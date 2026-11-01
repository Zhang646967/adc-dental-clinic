"""Narrow clinical authority. Never converts an appointment grant."""
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.db.models import OuterRef,Subquery,F
from adc_core.rules import RuleError
from portal.medical_models import MedicalProxy, MedicalProxyVersion


def active_proxies(actor):
    now = timezone.now()
    latest=MedicalProxyVersion.objects.filter(proxy_id=OuterRef('pk')).order_by('-number').values('number')[:1]
    return MedicalProxy.objects.annotate(current_number=Subquery(latest)).filter(versions__number=F('current_number'),delegate=actor, delegate__is_active=True, state='ACTIVE',
        patient__is_active=True, clinic__is_active=True, versions__valid_from__lte=now,
        versions__valid_until__gt=now).distinct()


def latest_version(proxy):
    return proxy.versions.order_by('-number').first()


def verify_version(version, *, step=None, actor=None, lock=False):
    qs = MedicalProxy.objects
    if lock: qs = qs.select_for_update(of=('self',))
    case = qs.select_related('patient','clinic','delegate').get(pk=version.proxy_id)
    now = timezone.now()
    identity=dict(id=case.patient_id,name=case.patient.name,date_of_birth=case.patient.date_of_birth.isoformat())
    if not version.delegate_name or identity!=version.patient_snapshot:
        raise PermissionDenied('患者身份资料已变化，请重新核对独立医疗代理材料。')
    today=timezone.localdate();born=case.patient.date_of_birth
    if case.kind=='GUARDIAN' and today.year-born.year-((today.month,today.day)<(born.month,born.day))>=18:
        raise PermissionDenied('本批未成年监护适用范围已变化，请医师重新核对本人或适用代理依据。')
    if (case.state != 'ACTIVE' or not case.delegate.is_active or not case.patient.is_active or
        not case.clinic.is_active or latest_version(case).pk != version.pk or
        not version.valid_from <= now < version.valid_until):
        raise PermissionDenied('这项医疗授权已变更、暂停、到期或撤销，请联系核验诊所重新办理。')
    if actor is not None and case.delegate_id != actor.pk:
        raise PermissionDenied('这项医疗授权不属于当前账号。')
    if step is not None and (step.version.plan_id != version.plan_id or
        not version.scopes.filter(step_id=step.step_id).exists()):
        raise PermissionDenied('这项医疗授权不包含当前诊所、方案或步骤。')
    return case


def selected_proxy(actor, *, step=None, lock=False):
    from workspaces.context import require_active
    require_active(actor, ('PATIENT',))
    ctx = getattr(actor, '_adc_workspace', None)
    if ctx is None or not ctx.medical_proxy_id:
        raise PermissionDenied('请先选择具有独立医疗授权的就诊人。')
    case = MedicalProxy.objects.get(pk=ctx.medical_proxy_id)
    version = latest_version(case)
    if ctx.medical_proxy_revision != case.revision:
        raise RuleError('所选医疗授权已变化，请重新选择就诊人后核对本次事项。')
    verify_version(version, step=step, actor=actor, lock=lock)
    return version


def is_proxy_context(actor):
    return bool(getattr(getattr(actor, '_adc_workspace', None), 'medical_proxy_id', None))
