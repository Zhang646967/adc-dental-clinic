"""Mini-program approval and browser consumption are separate transactions."""
from datetime import timedelta
import secrets
from uuid import UUID
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts import auth_providers
from accounts.external_identity import _account_actor,_record
from accounts.external_models import ExternalIdentity,WebLoginTicket
from accounts.models import UserAccount
from accounts.patient_auth import digest,writable
from adc_core.rules import RuleError
from workspaces.models import WorkspaceContext


def ticket_id(value):
    try:return UUID(str(value))
    except (ValueError,TypeError,AttributeError):raise RuleError('扫码链接无效，请在网站重新生成。') from None


def _browser(request,pk):
    data=request.session.get('adc_web_qr',{})
    current=request.user.pk if request.user.is_authenticated else None
    if (data.get('ticket')!=str(pk) or data.get('user')!=current or
            data.get('auth')!=(request.user.get_session_auth_hash() if current else '')):
        raise PermissionDenied('请使用生成二维码的原浏览器；登录页面已变化时请重新扫码。')
    return digest('web-qr:'+data['secret'])


def _state(row):
    return 'EXPIRED' if row.state in ('PENDING','APPROVED') and row.expires_at<=timezone.now() else row.state


def describe(row):
    return dict(ticket=row.pk.hex,state=_state(row),origin=row.origin,expires_at=row.expires_at.isoformat(),
        remaining_seconds=max(0,int((row.expires_at-timezone.now()).total_seconds())))


def start(request):
    writable()
    if not auth_providers.capabilities()['wechat_qr']:raise RuleError('微信扫码登录尚未配置，请使用其他登录方式。')
    previous=request.session.get('adc_web_qr',{}).get('ticket')
    if previous:WebLoginTicket.objects.filter(pk=ticket_id(previous),state__in=['PENDING','APPROVED']).update(state='REJECTED',decided_at=timezone.now())
    secret=secrets.token_urlsafe(32)
    row=WebLoginTicket.objects.create(browser_digest=digest('web-qr:'+secret),origin=request.build_absolute_uri('/').rstrip('/'),expires_at=timezone.now()+timedelta(seconds=180))
    request.session['adc_web_qr']=dict(ticket=str(row.pk),secret=secret,user=request.user.pk if request.user.is_authenticated else None,auth=request.user.get_session_auth_hash() if request.user.is_authenticated else '')
    try:image=auth_providers.mini_login_image(row.pk.hex)
    except RuleError:
        WebLoginTicket.objects.filter(pk=row.pk).update(state='REJECTED',decided_at=timezone.now())
        raise
    row.image=image;row.save(update_fields=['image'])
    return row


def browser_ticket(request,value):
    pk=ticket_id(value);binding=_browser(request,pk)
    row=WebLoginTicket.objects.get(pk=pk,browser_digest=binding)
    return row


def inspect(actor,value):
    _account_actor(actor)
    return describe(WebLoginTicket.objects.get(pk=ticket_id(value)))


def decide(*,actor,value,decision,code='',confirmed=False):
    writable();_account_actor(actor)
    if decision not in ('approve','reject'):raise RuleError('请明确确认或拒绝网站登录。')
    proof=auth_providers.wechat_subject(code,'MINI') if decision=='approve' and confirmed is True else None
    if decision=='approve' and proof is None:raise RuleError('请明确同意在所示网站登录。')
    error=None
    with transaction.atomic():
        row=WebLoginTicket.objects.select_for_update().get(pk=ticket_id(value))
        if _state(row)=='EXPIRED':row.state='EXPIRED';row.save(update_fields=['state']);error='二维码已过期，请在网站刷新。'
        elif row.state!='PENDING':error='此二维码已办理，请在网站核对结果或重新生成。'
        elif decision=='reject':
            row.state='REJECTED';row.decided_at=timezone.now();row.save(update_fields=['state','decided_at'])
        else:
            provider,app,subject=proof
            identity=ExternalIdentity.objects.select_for_update().filter(provider=provider,app_id=app,subject=subject,user=actor).first()
            if identity is None:raise PermissionDenied('请使用当前账号已绑定的微信确认；仅密码或短信登录不能批准。')
            user=UserAccount.objects.select_for_update().get(pk=actor.pk,is_active=True)
            _account_actor(actor);ctx=actor._adc_workspace
            row.user=user;row.identity=identity;row.identity_revision=identity.revision
            row.workspace=ctx;row.workspace_revision=ctx.revision;row.auth_digest=digest(user.get_session_auth_hash())
            row.state='APPROVED';row.decided_at=timezone.now();row.save()
            _record(user,'WEB_LOGIN_APPROVE',identity=identity,snapshot={'ticket':row.pk.hex,'identity_revision':identity.revision})
    if error:raise RuleError(error)
    return describe(row)


def consume(request,value):
    writable();pk=ticket_id(value);binding=_browser(request,pk);error=None;user=None
    with transaction.atomic():
        row=WebLoginTicket.objects.select_for_update().get(pk=pk,browser_digest=binding)
        if _state(row)=='EXPIRED':row.state='EXPIRED';row.save(update_fields=['state']);error='二维码已过期，请重新扫码。'
        elif row.state!='APPROVED':error='此二维码尚未确认或已办理，请重新核对。'
        else:
            identity=ExternalIdentity.objects.select_for_update().get(pk=row.identity_id)
            user=UserAccount.objects.select_for_update().get(pk=row.user_id)
            from portal.policies import has_patient_account
            valid=(auth_providers.capabilities()['wechat_qr'] and user.is_active and has_patient_account(user) and
                identity.user_id==user.pk and identity.provider=='WECHAT_MINI' and identity.app_id==settings.ADC_WECHAT_MINI_APP_ID and
                identity.revision==row.identity_revision and digest(user.get_session_auth_hash())==row.auth_digest and
                WorkspaceContext.objects.filter(pk=row.workspace_id,user=user,revision=row.workspace_revision,login_channel='PATIENT',role__in=['','PATIENT']).exists())
            if not valid:
                row.state='REJECTED';row.save(update_fields=['state']);error='授权或账号状态已变化，请重新登录并扫码。'
            else:
                row.state='CONSUMED';row.consumed_at=timezone.now();row.save(update_fields=['state','consumed_at'])
                _record(user,'WEB_LOGIN_CONSUME',identity=identity,snapshot={'ticket':row.pk.hex,'identity_revision':identity.revision})
    if error:raise RuleError(error)
    request.session.pop('adc_web_qr',None)
    return user
