"""Authentication assurance is independent of synthetic clinical fixtures."""
from django.conf import settings
from django.core.checks import Error,register


def live():
    return settings.ADC_PATIENT_AUTH_MODE=='live'


def local_enabled():
    return not live() and settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_PATIENT_IDENTITY_PROVIDER=='local'


def has_live_credentials(user):
    from accounts.external_models import ExternalIdentity,AccountPhone
    return (ExternalIdentity.objects.filter(user=user,provider__in=['WECHAT_MINI','WECHAT_WEB','WECHAT_MP']).exists()
        or AccountPhone.objects.filter(user=user,source__in=['SMS_VERIFIED','WECHAT_PHONE']).exists())


@register()
def authentication_settings(app_configs,**kwargs):
    errors=[]
    if settings.ADC_PATIENT_AUTH_MODE not in ('demo','live'):
        errors.append(Error('ADC_PATIENT_AUTH_MODE must be demo or live.',id='accounts.E020'))
    if live() and (settings.ADC_PATIENT_IDENTITY_PROVIDER=='local' or settings.ADC_SMS_PROVIDER=='demo'):
        errors.append(Error('Live authentication cannot enable local credentials or demonstration SMS.',id='accounts.E021'))
    if settings.ADC_WECHAT_QR_ENV_VERSION not in ('develop','trial','release'):
        errors.append(Error('Invalid WeChat QR environment version.',id='accounts.E022'))
    return errors
