"""Website and native authentication share the same patient credential commands."""
import secrets,time
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect,render
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods,require_POST,require_GET
from accounts import auth_providers,patient_auth
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.rules import RuleError
from portal import account_forms as forms
from portal.account_access import account_context,account_data,remember_pending_service,resume_service
from portal.mini_api import endpoint,result,session_data,validated
from portal.policies import has_patient_access
from workspaces.activation import begin_login_workspace


def complete_login(request,user,service=None):
    login(request,user,backend='django.contrib.auth.backends.ModelBackend');request.session.set_expiry(3600)
    route=begin_login_workspace(request,channel='PATIENT');remember_pending_service(request,service)
    request.session.pop('adc_auth_session',None)
    return resume_service(request) or route if has_patient_access(user) else reverse('patient_account')


def login_context(request,*,form=None,sms_form=None,sent=None,booking_service=None):
    """Both password and OTP errors stay on the same patient entry page."""
    if booking_service is None:
        from scheduling.service_content import positive_id
        from portal.service_catalogue import public_profiles
        raw=request.POST.get('booking_service','') if request.method=='POST' else request.GET.get('service','')
        selected=positive_id(raw)
        booking_service=next((p for p in public_profiles() if p.service_id==selected),None) if selected else None
    caps=auth_providers.capabilities()
    return dict(form=form if form is not None else AuthenticationForm(request),
        sms_form=sms_form if sms_form is not None else forms.SmsAuthForm(),sent=sent,auth=caps,
        booking_service=booking_service,
        password_mode=request.POST.get('login_method')=='password' or bool(form is not None and form.is_bound) or not caps['sms_enabled'],
        wechat_in_browser='micromessenger' in request.headers.get('User-Agent','').lower())


@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def sms(request,binding=False,inline=False):
    if binding:account_context(request,unsafe=request.method=='POST')
    caps=auth_providers.capabilities();sent=None
    context=login_context(request) if inline else None
    if inline and context['booking_service']:
        request.session['adc_auth_service']=context['booking_service'].service_id
    form=forms.SmsAuthForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data;purpose='BIND' if binding else 'LOGIN'
        try:
            if request.POST.get('action')=='send':
                sent=patient_auth.request_sms(request=request,phone=d['phone'],purpose=purpose,confirmed=d['confirmed'])
                data=request.POST.copy();data['challenge']=sent['challenge'];data['code']='';form=forms.SmsAuthForm(data)
            else:
                if not d['challenge'] or not d['code']:raise RuleError('请先获取验证码，再输入收到的六位验证码。')
                user=patient_auth.confirm_sms(request=request,challenge=d['challenge'],phone=d['phone'],code=d['code'],purpose=purpose,confirmed=d['confirmed'])
                if binding:messages.success(request,'手机号已核验并绑定，可以用于本人账号登录。');return redirect('patient_account')
                return redirect(complete_login(request,user,request.session.pop('adc_auth_service',None)))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    elif request.method=='GET' and not binding:
        # Typed service intent only; activation and booking retain their own rules.
        from scheduling.service_content import positive_id
        service=positive_id(request.GET.get('service',''))
        if service:request.session['adc_auth_service']=service
    if inline:
        context.update(sms_form=form,sent=sent)
        return render(request,'portal/login.html',context)
    return render(request,'portal/sms_login.html',dict(form=form,sent=sent,binding=binding,auth=caps,account_token=account_data(request)['account_token'] if binding else ''))


@require_POST
def wechat_start(request):
    patient_auth.writable()
    kind=request.POST.get('kind','WEB')
    if kind not in ('WEB','MP') or not auth_providers.capabilities()['wechat_'+kind.lower()]:
        messages.error(request,'微信登录尚未开通，请使用手机号或账号登录。');return redirect('portal_login')
    if request.POST.get('confirmed')!='on':
        messages.error(request,'请先同意使用微信身份登录患者账号。');return redirect('portal_login')
    state=secrets.token_urlsafe(32)
    data=dict(state=state,issued=time.time(),kind=kind,service=request.POST.get('booking_service',''))
    if request.POST.get('bind')=='on':
        ctx=account_context(request,unsafe=True)
        data.update(binding_user=request.user.pk,auth_hash=request.user.get_session_auth_hash(),workspace=str(ctx.pk),revision=ctx.revision)
    request.session['adc_wechat_oauth']=data
    app=getattr(settings,'ADC_WECHAT_'+kind+'_APP_ID')
    callback=request.build_absolute_uri(reverse('patient_wechat_callback'))
    query=dict(appid=app,redirect_uri=callback,response_type='code',scope='snsapi_login' if kind=='WEB' else 'snsapi_base',state=state)
    return redirect('https://open.weixin.qq.com/connect/'+('qrconnect' if kind=='WEB' else 'oauth2/authorize')+'?'+urlencode(query)+'#wechat_redirect')


@sensitive_post_parameters()
@require_GET
def wechat_callback(request):
    data=request.session.pop('adc_wechat_oauth',None);state=request.GET.get('state','')
    if not data or not secrets.compare_digest(data['state'],state) or time.time()-data['issued']>300:
        messages.error(request,'微信授权页面已失效，请重新发起登录。');return redirect('portal_login')
    try:
        actor=None
        if data.get('binding_user'):
            ctx=account_context(request)
            if (request.user.pk!=data['binding_user'] or not secrets.compare_digest(request.user.get_session_auth_hash(),data['auth_hash']) or str(ctx.pk)!=data['workspace'] or ctx.revision!=data['revision']):
                raise RuleError('账号会话已变化，请从当前账号重新发起微信绑定。')
            actor=request.user
        provider,app,subject=auth_providers.wechat_subject(request.GET.get('code',''),data['kind'])
        user=patient_auth.exchange_identity(provider=provider,app_id=app,subject=subject,binding_actor=actor)
    except EXPECTED_ERRORS as exc:
        messages.error(request,str(exc));return redirect('portal_login')
    return redirect('patient_account') if actor else redirect(complete_login(request,user,data.get('service')))


@sensitive_post_parameters()
@endpoint(('POST',),public=True)
def mini_wechat_login(request,binding=False):
    if binding:account_context(request,unsafe=True)
    d=validated(forms.WechatCodeForm(request.POST));old=None
    if d['username'] and not binding:
        form=AuthenticationForm(request,data={'username':d['username'],'password':d['password']})
        if not form.is_valid():return result(request,status=401,code='LOGIN_FAILED',message='原账号或密码不正确，或账号已停用。')
        old=form.get_user()
    provider,app,subject=auth_providers.wechat_subject(d['code'],'MINI')
    user=patient_auth.exchange_identity(provider=provider,app_id=app,subject=subject,existing_user=old,existing_password=d['password'],binding_actor=request.user if binding else None)
    if not binding:complete_login(request,user)
    return result(request,session_data(request))


@sensitive_post_parameters()
@endpoint(('POST',),public=True)
def mini_sms_send(request,binding=False):
    if binding:account_context(request,unsafe=True)
    d=validated(forms.SmsAuthForm(request.POST))
    sent=patient_auth.request_sms(request=request,phone=d['phone'],purpose='BIND' if binding else 'LOGIN',confirmed=d['confirmed'])
    return result(request,sent)


@sensitive_post_parameters()
@endpoint(('POST',),public=True)
def mini_sms_confirm(request,binding=False):
    if binding:account_context(request,unsafe=True)
    d=validated(forms.SmsAuthForm(request.POST))
    if not d['challenge'] or not d['code']:raise RuleError('请先获取并输入验证码。')
    user=patient_auth.confirm_sms(request=request,challenge=d['challenge'],phone=d['phone'],code=d['code'],purpose='BIND' if binding else 'LOGIN',confirmed=d['confirmed'])
    if not binding:complete_login(request,user)
    return result(request,session_data(request))


@sensitive_post_parameters()
@endpoint(('POST',),public=True)
def mini_phone(request):
    account_context(request,unsafe=True);d=validated(forms.WechatCodeForm(request.POST))
    patient_auth.bind_wechat_phone(actor=request.user,code=d['code'],confirmed=d['confirmed'])
    return result(request,account_data(request))
