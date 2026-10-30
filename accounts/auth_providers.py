"""Server-only WeChat and Tencent SMS adapters. No client-supplied identity claims.

Only fixed official HTTPS endpoints are used. Provider payloads, phone numbers,
codes, AppSecrets and access/session tokens never reach operational logs.
"""
from datetime import datetime,timezone
import hashlib,hmac,json,re,time
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode
from urllib.request import Request,build_opener,HTTPRedirectHandler
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.debug import sensitive_variables
from adc_core.rules import RuleError


def capabilities():
    from accounts.auth_config import live
    real=live()
    mini=real and bool(settings.ADC_WECHAT_MINI_APP_ID and settings.ADC_WECHAT_MINI_APP_SECRET)
    sms=settings.ADC_SMS_PROVIDER
    demo=not real and sms=='demo' and settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_TEACHER_TEST_MODE
    tencent=real and sms=='tencent' and all((settings.ADC_SMS_SECRET_ID,settings.ADC_SMS_SECRET_KEY,settings.ADC_SMS_APP_ID,settings.ADC_SMS_SIGN_NAME,settings.ADC_SMS_TEMPLATE_ID))
    cloudbase=real and sms=='cloudbase' and bool(settings.ADC_CLOUDBASE_ENV_ID and settings.ADC_CLOUDBASE_PUBLISHABLE_KEY and settings.ADC_SMS_FREE_QUOTA_CONFIRMED and settings.ADC_SMS_ALLOWED_TEST_PHONES and settings.ADC_CLOUDBASE_REGION=='ap-shanghai')
    return dict(wechat_mini=mini,wechat_phone=mini and settings.ADC_WECHAT_PHONE_ENABLED,
        wechat_web=real and bool(settings.ADC_WECHAT_WEB_APP_ID and settings.ADC_WECHAT_WEB_APP_SECRET),
        wechat_mp=real and bool(settings.ADC_WECHAT_MP_APP_ID and settings.ADC_WECHAT_MP_APP_SECRET),
        wechat_qr=mini,sms_captcha=bool(cloudbase),sms_enabled=bool(demo or tencent or cloudbase),sms_demo=bool(demo),auth_mode=settings.ADC_PATIENT_AUTH_MODE)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


@sensitive_variables()
def _request(url,*,data=None,headers=None,error_payload=False):
    body=None if data is None else json.dumps(data,separators=(',',':'),ensure_ascii=False).encode()
    req=Request(url,data=body,headers=headers or {'Content-Type':'application/json'})
    try:
        try:
            response=build_opener(NoRedirect).open(req,timeout=10)
        except HTTPError as exc:
            if not error_payload or exc.code not in (400,401,403,429):raise
            response=exc
        with response:raw=response.read(65537)
        if len(raw)>65536:raise ValueError
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError
        return result
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):
        raise RuleError('授权或短信服务暂不可用，请稍后重试；也可使用账号密码登录。') from None


@sensitive_variables()
def mini_access_token():
    if not capabilities()['wechat_mini']:raise RuleError('微信小程序登录尚未配置。')
    key='adc-wechat-token:'+hashlib.sha256((settings.ADC_WECHAT_MINI_APP_ID+settings.ADC_WECHAT_MINI_APP_SECRET).encode()).hexdigest()
    cached=cache.get(key)
    if cached:return cached
    value=_request('https://api.weixin.qq.com/cgi-bin/stable_token',data={'grant_type':'client_credential','appid':settings.ADC_WECHAT_MINI_APP_ID,'secret':settings.ADC_WECHAT_MINI_APP_SECRET,'force_refresh':False})
    token=value.get('access_token')
    if value.get('errcode',0)!=0 or not isinstance(token,str) or not token:raise RuleError('微信服务暂不可用，请稍后重试。')
    cache.set(key,token,max(1,min(int(value.get('expires_in',7200)),7200)-120))
    return token


@sensitive_variables()
def mini_login_image(scene):
    token=mini_access_token()
    payload={'scene':scene,'page':'pages/web-login/index','check_path':False,'env_version':settings.ADC_WECHAT_QR_ENV_VERSION,'width':280}
    req=Request('https://api.weixin.qq.com/wxa/getwxacodeunlimit?'+urlencode({'access_token':token}),data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect).open(req,timeout=10) as response:raw=response.read(1048577)
        if len(raw)>1048576:raise ValueError
        mini_image_content_type(raw)
        return raw
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):
        raise RuleError('暂未取得微信小程序码，请刷新重试或使用其他登录方式。') from None


def mini_image_content_type(raw):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if raw.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    raise RuleError('暂未取得微信小程序码，请刷新重试或使用其他登录方式。')


@sensitive_variables()
def cloudbase(path,data,*,captcha_token=None):
    env=settings.ADC_CLOUDBASE_ENV_ID
    if (settings.ADC_SMS_PROVIDER!='cloudbase' or not capabilities()['sms_enabled'] or
            not re.fullmatch(r'[a-zA-Z0-9-]{3,100}',env)):
        raise RuleError('免费短信联调条件尚未确认，暂未发送短信。')
    headers={'Content-Type':'application/json','Authorization':'Bearer '+settings.ADC_CLOUDBASE_PUBLISHABLE_KEY}
    if captcha_token:headers['x-captcha-token']=captcha_token
    return _request('https://'+env+'.api.tcloudbasegateway.com/auth/v1/'+path,data=data,headers=headers,error_payload=True)


@sensitive_variables()
def cloudbase_send(phone,*,captcha_token=None):
    # The provider creates the OTP; ADC stores only the returned challenge ID.
    value=cloudbase('verification',{'phone_number':'+86 '+phone,'target':'ANY'},captcha_token=captcha_token)
    reference=value.get('verification_id')
    if not isinstance(reference,str) or not 1<=len(reference)<=512:
        raise RuleError('短信平台未接受发送，请核对免费额度、测试号码或图片验证码后重试。')
    return reference,min(600,max(1,int(value.get('expires_in',600))))


@sensitive_variables()
def cloudbase_verify(reference,code):
    value=cloudbase('verification/verify',{'verification_id':reference,'verification_code':code})
    if value.get('error') or not isinstance(value.get('verification_token'),str) or not value['verification_token']:
        raise RuleError('验证码未通过平台核验，请核对或重新获取。')
    # Provider tokens never become ADC sessions and are never returned to clients.


@sensitive_variables()
def cloudbase_captcha():
    value=cloudbase('captcha/data',{})
    image=value.get('data','');token=value.get('token','')
    if not isinstance(image,str) or len(image)>60000 or not re.fullmatch(r'data:image/(?:gif|png|jpeg);base64,[A-Za-z0-9+/=]+',image) or not isinstance(token,str) or not 1<=len(token)<=4096:
        raise RuleError('暂未取得图片验证码，请稍后重试。')
    return image,token


@sensitive_variables()
def cloudbase_verify_captcha(token,key):
    value=cloudbase('captcha/data/verify',{'token':token,'key':key})
    result=value.get('captcha_token')
    if not isinstance(result,str) or not result:raise RuleError('图片验证码不正确或已过期，请刷新后重试。')
    return result


def _code(code):
    if not isinstance(code,str) or not re.fullmatch(r'[A-Za-z0-9_\-]{8,512}',code):
        raise RuleError('授权码无效，请重新点击微信授权。')
    return code


@sensitive_variables()
def wechat_subject(code,kind):
    code=_code(code)
    if kind not in ('MINI','WEB','MP') or not capabilities()['wechat_'+kind.lower()]:
        raise RuleError('微信登录尚未配置，请使用手机号或账号登录。')
    app=getattr(settings,'ADC_WECHAT_'+kind+'_APP_ID');secret=getattr(settings,'ADC_WECHAT_'+kind+'_APP_SECRET')
    query={'appid':app,'secret':secret,'grant_type':'authorization_code'}
    if kind=='MINI':query['js_code']=code;path='/sns/jscode2session'
    else:query['code']=code;path='/sns/oauth2/access_token'
    result=_request('https://api.weixin.qq.com'+path+'?'+urlencode(query))
    subject=result.get('openid')
    if result.get('errcode',0)!=0 or not isinstance(subject,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,160}',subject):
        raise RuleError('微信授权未成功或已过期，请重新点击授权。')
    # The provider session_key/access_token is deliberately discarded.
    return 'WECHAT_'+kind,app,subject


@sensitive_variables()
def wechat_phone(code):
    code=_code(code)
    if not capabilities()['wechat_phone']:raise RuleError('微信手机号授权尚未开通，请使用短信验证绑定。')
    token=_request('https://api.weixin.qq.com/cgi-bin/stable_token',data={'grant_type':'client_credential','appid':settings.ADC_WECHAT_MINI_APP_ID,'secret':settings.ADC_WECHAT_MINI_APP_SECRET,'force_refresh':False})
    access=token.get('access_token')
    if token.get('errcode',0)!=0 or not isinstance(access,str) or not access:
        raise RuleError('微信手机号服务暂不可用，请稍后重试。')
    payload=_request('https://api.weixin.qq.com/wxa/business/getuserphonenumber?'+urlencode({'access_token':access}),data={'code':code})
    info=payload.get('phone_info',{});phone=info.get('purePhoneNumber')
    if payload.get('errcode',0)!=0 or str(info.get('countryCode'))!='86' or not isinstance(phone,str) or not re.fullmatch(r'1[3-9][0-9]{9}',phone):
        raise RuleError('未取得中国大陆手机授权，请重新授权或使用短信验证。')
    return phone


@sensitive_variables()
def send_sms(phone,code):
    if not capabilities()['sms_enabled']:raise RuleError('短信注册尚未开通，请使用已分配账号登录。')
    if settings.ADC_SMS_PROVIDER=='demo':return
    host='sms.tencentcloudapi.com';stamp=int(time.time());date=datetime.fromtimestamp(stamp,timezone.utc).strftime('%Y-%m-%d')
    payload={'PhoneNumberSet':['+86'+phone],'SmsSdkAppId':settings.ADC_SMS_APP_ID,'SignName':settings.ADC_SMS_SIGN_NAME,'TemplateId':settings.ADC_SMS_TEMPLATE_ID,'TemplateParamSet':[code,'5']}
    body=json.dumps(payload,separators=(',',':'),ensure_ascii=False).encode()
    canonical='POST\n/\n\ncontent-type:application/json\nhost:'+host+'\n\ncontent-type;host\n'+hashlib.sha256(body).hexdigest()
    scope=date+'/sms/tc3_request';to_sign='TC3-HMAC-SHA256\n'+str(stamp)+'\n'+scope+'\n'+hashlib.sha256(canonical.encode()).hexdigest()
    sign=lambda key,value:hmac.new(key,value.encode(),hashlib.sha256).digest()
    key=sign(sign(sign(('TC3'+settings.ADC_SMS_SECRET_KEY).encode(),date),'sms'),'tc3_request')
    signature=hmac.new(key,to_sign.encode(),hashlib.sha256).hexdigest()
    headers={'Content-Type':'application/json','Host':host,'X-TC-Action':'SendSms','X-TC-Version':'2021-01-11','X-TC-Timestamp':str(stamp),'X-TC-Region':settings.ADC_SMS_REGION,
        'Authorization':'TC3-HMAC-SHA256 Credential='+settings.ADC_SMS_SECRET_ID+'/'+scope+', SignedHeaders=content-type;host, Signature='+signature}
    response=_request('https://'+host+'/',data=payload,headers=headers).get('Response',{})
    statuses=response.get('SendStatusSet',[])
    if response.get('Error') or len(statuses)!=1 or statuses[0].get('Code')!='Ok':
        raise RuleError('短信服务未接受发送，请稍后重试；没有完成号码核验。')
