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
from django.views.decorators.debug import sensitive_variables
from adc_core.rules import RuleError


def capabilities():
    mini=bool(settings.ADC_WECHAT_MINI_APP_ID and settings.ADC_WECHAT_MINI_APP_SECRET)
    sms=settings.ADC_SMS_PROVIDER
    demo=sms=='demo' and settings.ADC_CLINICAL_SYNTHETIC and settings.ADC_TEACHER_TEST_MODE
    live=sms=='tencent' and all((settings.ADC_SMS_SECRET_ID,settings.ADC_SMS_SECRET_KEY,settings.ADC_SMS_APP_ID,settings.ADC_SMS_SIGN_NAME,settings.ADC_SMS_TEMPLATE_ID))
    return dict(wechat_mini=mini,wechat_phone=mini and settings.ADC_WECHAT_PHONE_ENABLED,
        wechat_web=bool(settings.ADC_WECHAT_WEB_APP_ID and settings.ADC_WECHAT_WEB_APP_SECRET),
        wechat_mp=bool(settings.ADC_WECHAT_MP_APP_ID and settings.ADC_WECHAT_MP_APP_SECRET),sms_enabled=bool(demo or live),sms_demo=bool(demo))


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


@sensitive_variables()
def _request(url,*,data=None,headers=None):
    body=None if data is None else json.dumps(data,separators=(',',':'),ensure_ascii=False).encode()
    req=Request(url,data=body,headers=headers or {'Content-Type':'application/json'})
    try:
        with build_opener(NoRedirect).open(req,timeout=10) as response:
            raw=response.read(65537)
        if len(raw)>65536:raise ValueError
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError
        return result
    except (HTTPError,URLError,TimeoutError,OSError,ValueError):
        raise RuleError('授权或短信服务暂不可用，请稍后重试；也可使用账号密码登录。') from None


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
