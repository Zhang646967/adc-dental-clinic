"""One actor/subject boundary for website, native and shared appointment commands."""
from dataclasses import dataclass
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from portal.models import PatientAccess, PatientAppointmentGrant, PatientRelationship

class SubjectRequired(PermissionDenied):
    pass

def active_grants(user):
    now = timezone.now()
    return PatientAppointmentGrant.objects.filter(is_active=True, valid_from__lte=now, valid_until__gt=now,
        relationship__state='VERIFIED', relationship__delegate_user_id=user.pk,
        relationship__delegate_user__is_active=True, relationship__patient__is_active=True,
        relationship__clinic__is_active=True)

def has_patient_access(user):
    return user.is_authenticated and user.is_active and (PatientAccess.objects.filter(user_id=user.pk,
        is_active=True, patient__is_active=True).exists() or active_grants(user).exists())

@dataclass(frozen=True)
class PatientAuthority:
    patient: object
    source: object
    delegated: bool = False
    @property
    def pk(self):
        return f'grant:{self.source.pk}' if self.delegated else self.source.pk
    @property
    def patient_id(self):
        return self.patient.pk
    @property
    def clinic_id(self):
        return self.source.relationship.clinic_id if self.delegated else None
    @property
    def receipt_fields(self):
        return {'appointment_grant': self.source, 'access': None} if self.delegated else {'access': self.source, 'appointment_grant': None}
    @property
    def stamp(self):
        return {'key': self.pk, 'patient': self.patient_id, 'clinic': self.clinic_id,
            'revision': self.source.revision if self.delegated else 0}
    def require_clinic(self, clinic_id):
        if self.delegated and self.clinic_id != clinic_id:
            raise PermissionDenied('本次代约授权仅适用于核验诊所，请切换患者授权或联系该店前台。')
    def scope(self, queryset, *, patient_field='patient_id', clinic_field='clinic_id'):
        queryset = queryset.filter(**{patient_field: self.patient_id})
        return queryset.filter(**{clinic_field: self.clinic_id}) if self.delegated else queryset

def patient_access(user, *, lock=False, self_only=False):
    from workspaces.context import require_active
    require_active(user, ('PATIENT',))
    if not user.is_authenticated:
        raise PermissionDenied('请先登录患者端。')
    ctx = getattr(user, '_adc_workspace', None)
    grant_id = getattr(ctx, 'patient_grant_id', None)
    if grant_id:
        if self_only:
            raise PermissionDenied('预约代办不包含病历、结算单或知情同意权限。')
        # Verification changes and appointment effects serialize on case -> grant.
        if lock:
            case_id = PatientAppointmentGrant.objects.filter(pk=grant_id,
                relationship__delegate_user_id=user.pk).values_list('relationship_id', flat=True).first()
            PatientRelationship.objects.select_for_update().filter(pk=case_id).first()
        qs = active_grants(user).select_related('relationship__patient', 'relationship__clinic')
        if lock: qs = qs.select_for_update(of=('self',))
        grant = qs.filter(pk=grant_id).first()
        if grant is None:
            raise SubjectRequired('所选患者的代约授权已暂停、到期或撤销，请重新选择患者或联系前台。')
        return PatientAuthority(grant.relationship.patient, grant, True)
    qs = PatientAccess.objects.filter(user_id=user.pk, user__is_active=True, is_active=True,
        patient__is_active=True).select_related('patient')
    if lock: qs = qs.select_for_update(of=('self',))
    access = qs.first()
    if access is None:
        raise SubjectRequired('请先选择获授权的就诊人；联系人、手机号或患者编号不能代替授权。')
    return PatientAuthority(access.patient, access)

def check_authority(access, stamp):
    from adc_core.rules import RuleError
    if stamp != access.stamp:
        raise RuleError('就诊人或代约授权已变化，请重新核对；本次没有执行业务操作。')

def subject_choices(user):
    rows=[]
    own=PatientAccess.objects.filter(user_id=user.pk, is_active=True, patient__is_active=True).select_related('patient').first()
    if own:
        rows.append(dict(key='self', name=own.patient.name, capacity='本人', clinic='', expires=None))
    for grant in active_grants(user).select_related('relationship__patient','relationship__clinic').order_by('relationship__patient__patient_no','pk'):
        r=grant.relationship
        rows.append(dict(key=f'grant:{grant.pk}', name=r.patient.name, capacity=r.get_kind_display()+' · 预约代办',
            clinic=r.clinic.name, expires=grant.valid_until.isoformat()))
    return rows


def form_authority(user):
    from django.core import signing
    ctx=getattr(user,'_adc_workspace',None)
    return signing.dumps({'authority':patient_access(user).stamp,'context':str(ctx.pk) if ctx else None,
        'revision':ctx.revision if ctx else None},salt='adc.patient.subject.v1')


def read_form_authority(user,token):
    from django.core import signing
    from adc_core.rules import RuleError
    if not token:return None
    try:
        data=signing.loads(token,salt='adc.patient.subject.v1',max_age=900)
        ctx=getattr(user,'_adc_workspace',None)
        if data['context']!=(str(ctx.pk) if ctx else None) or data['revision']!=(ctx.revision if ctx else None):raise ValueError
        return data['authority']
    except (signing.BadSignature,ValueError,KeyError,TypeError):
        raise RuleError('就诊人核对页已失效，请重新打开。') from None


def check_action_authority(access,stamp):
    # Existing direct self-service calls remain valid; delegation always binds a preview.
    if access.delegated or stamp is not None:check_authority(access,stamp)
