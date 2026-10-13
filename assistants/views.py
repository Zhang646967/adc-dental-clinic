import json
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET,require_POST
from django.views.decorators.debug import sensitive_post_parameters
from assistants.protocol import AIProtocolError
from assistants.quotas import RateLimited
from assistants.services import authorize,respond

@login_required(login_url="portal_login")
@require_GET
def patient_page(request):
    authorize(request.user,"patient")
    return render(request,"assistants/chat.html",{"audience":"patient","base_template":"portal/base.html",
        "assistant_title":"预约与就诊小助手","is_remote":settings.AI_MODE=="remote",
        "examples":["我想预约","查一下我的预约","怎么取消预约","账单怎么看","字体太小"]})

@login_required
@require_GET
def staff_page(request):
    authorize(request.user,"staff")
    return render(request,"assistants/chat.html",{"audience":"staff","base_template":"base.html",
        "assistant_title":"员工业务助手","is_remote":settings.AI_MODE=="remote",
        "examples":["今天的工作概览","改期有什么规则","接诊需要确认什么","结算单怎么生成","使用大字模式"]})

@sensitive_post_parameters()
@require_POST
def chat_api(request,audience):
    if not request.user.is_authenticated:
        return JsonResponse({"error":"请先登录。"},status=401)
    if request.content_type!="application/json": return JsonResponse({"error":"需要JSON请求。"},status=415)
    if len(request.body)>8192: return JsonResponse({"error":"请求过大。"},status=413)
    try:
        data=json.loads(request.body)
        if type(data) is not dict or set(data)-{"message","consent"} or type(data.get("consent",False)) is not bool:
            raise AIProtocolError("请求字段不合规。")
        result=respond(user=request.user,audience=audience,message=data.get("message"),consent=data.get("consent",False))
    except (ValueError,UnicodeError,AIProtocolError) as exc:
        return JsonResponse({"error":str(exc) if isinstance(exc,AIProtocolError) else "请求格式错误。"},status=400)
    except PermissionDenied:
        return JsonResponse({"error":"当前账号没有这个助手的访问权限，或授权已经变化。"},status=403)
    except RateLimited:
        response=JsonResponse({"error":"请求次数已达当前上限，请稍后再试。预约等普通按钮仍可使用。"},status=429)
        response["Retry-After"]="60";return response
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error("Assistant unavailable; error_class=%s",type(exc).__name__)
        return JsonResponse({"error":"助手暂时不可用。可以继续使用普通业务按钮；请稍后再试。"},status=503)
    response=JsonResponse(result)
    response["Cache-Control"]="no-store"
    return response
