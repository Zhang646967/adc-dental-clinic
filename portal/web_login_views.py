"""Same-origin QR endpoints; polling never logs a browser in."""
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from accounts import web_login,auth_providers,patient_auth
from adc_core.rules import RuleError
from portal.account_access import account_context
from portal.auth_views import complete_login
from portal.mini_api import endpoint,result


@endpoint(('POST',),public=True)
def start(request):
    row=web_login.start(request)
    return result(request,dict(**web_login.describe(row),image=reverse('patient_wechat_qr_image')+'?ticket='+row.pk.hex,poll_seconds=2))


@endpoint(public=True)
def status(request):return result(request,web_login.describe(web_login.browser_ticket(request,request.GET.get('ticket'))))


@endpoint(public=True)
def image(request):
    row=web_login.browser_ticket(request,request.GET.get('ticket'))
    if web_login.describe(row)['state']!='PENDING':raise RuleError('二维码已办理或过期，请重新生成。')
    raw=bytes(row.image)
    response=HttpResponse(raw,content_type=auth_providers.mini_image_content_type(raw));response['Cache-Control']='no-store'
    return response


@endpoint(('POST',),public=True)
def complete(request):
    user=web_login.consume(request,request.POST.get('ticket'))
    return result(request,dict(redirect=complete_login(request,user,request.session.pop('adc_auth_service',None))))


@sensitive_post_parameters()
@endpoint(('GET','POST'),subject_optional=True)
def mini(request):
    account_context(request,unsafe=request.method=='POST')
    if request.method=='GET':data=web_login.inspect(request.user,request.GET.get('ticket'))
    else:data=web_login.decide(actor=request.user,value=request.POST.get('ticket'),decision=request.POST.get('decision'),code=request.POST.get('code',''),confirmed=request.POST.get('confirmed')=='on')
    return result(request,data)


@endpoint(('POST',),public=True)
def captcha(request):
    patient_auth.writable()
    image,token=auth_providers.cloudbase_captcha()
    from django.utils import timezone
    request.session['adc_sms_captcha']=dict(token=token,session=patient_auth.session_key(request,create=True),expires=timezone.now().timestamp()+300)
    return result(request,dict(image=image,expires_seconds=300))
