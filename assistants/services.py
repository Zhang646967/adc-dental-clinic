"""Two-sided AI -> allowlisted intent -> permissioned deterministic answer cards.
The network classifier receives NO ORM data, identifiers, summaries, or medical notes.
"""
import time
from uuid import uuid4
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.urls import reverse
from django.utils import timezone
from accounts.policies import bindings
from assistants import provider
from assistants.models import AssistantEvent
from assistants.protocol import validate_message,redact,local_intent,CLINICAL
from assistants.quotas import consume
from portal.policies import patient_access
from scheduling.models import Visit
from scheduling.selectors import visible_visits

LABELS={"demo":"本地规则演示（未调用AI）","remote":"AI识别意图 · 系统生成事实回答",
        "fallback":"AI不可用 · 已切换本地规则","local_only":"未同意外发 · 仅本地规则",
        "safety":"医学问题转人工 · 未调用AI","disabled":"AI已关闭 · 本地帮助"}

def authorize(user,audience):
    if audience=="patient": return patient_access(user)
    if audience!="staff" or not bindings(user).filter(role__in=["FRONT_DESK","DENTIST","MANAGER","HQ","FINANCE"]).exists():
        raise PermissionDenied("当前账号没有员工助手权限。")
    return None

def _answer(user,audience,intent):
    links=[];facts=[]
    if intent=="clinical":
        return {"title":"这个问题需要由牙医判断","answer":"本助手只处理预约、就诊流程和账单说明，不提供诊断、用药或治疗安全判断。请联系诊所或实际接诊医生；紧急不适请联系当地急救服务，不要等待聊天答复。",
            "facts":[],"links":[],"source":"AI-SAFE-01 · 非诊疗助手边界"}
    if intent=="accessibility":
        return {"title":"使用适合自己的显示方式","answer":"页面顶部可以切换“标准模式”和“大字简明模式”。主要操作有独立按钮；不必通过聊天完成预约。可用键盘操作，回答可在设备支持本地中文声音时朗读。",
            "facts":[],"links":[],"source":"UX-01 · 显示偏好与非聊天路径"}
    if audience=="patient":
        access=patient_access(user)
        entries={
            "book":("选择预约时间","先选择诊所与日期，再打开一个可用时段。下一页会列出诊所、牙医和北京时间；只有你点击确认，系统才写入预约。30分钟是课程演示的预约单位，不表示实际治疗所需时间。","portal_slots","去选择时间","PORTAL-01 · 人工确认预约"),
            "appointments":("你的预约概览","下面是当前账号未来的有效预约。更完整的记录在“我的预约”中；这里没有自动按聊天中的相对日期筛选。","portal_appointments","查看我的预约","PORTAL-02 · 本人数据范围"),
            "cancel":("取消前再核对一次","进入“我的预约”，打开尚未开始的预约，选择取消并填写原因，再确认。已到诊或已经开始的预约请联系前台。本次对话没有取消任何记录。","portal_appointments","打开我的预约","PORTAL-03 · 取消与历史保留"),
            "bill":("账单中的金额是什么","账单逐行显示已经确认的治疗、单位数量、单价和小计。总价由系统精确计算；它是开单金额，不代表已经付款。请在对应就诊详情中打开账单。","portal_appointments","查找就诊账单","BR-09/12/13 · 账单与实收款区分"),
            "human":("不通过聊天也能完成操作","可使用页面导航和按钮。需要更改身份资料、委托家属或处理过去的预约，请联系前台；本演示不提供真实电话转接、短信或家属代办授权。","portal_help","查看帮助","PORTAL-04 · 人工协助与范围"),
            "help":("你可以直接选一个任务","我支持预约入口、本人预约概览、取消步骤和账单说明。请只输入办理事项，不输入真实姓名、电话、证件或病情。也可以不使用AI，直接点击页面按钮。","portal_home","返回患者首页","AI-01 · 受限服务目录"),
        }
        title,answer,name,label,source=entries.get(intent,entries["help"])
        if intent=="appointments":
            qs=Visit.objects.filter(patient_id=access.patient_id,status="SCHEDULED",scheduled_start__gte=timezone.now()).select_related("clinic","dentist").order_by("scheduled_start")[:3]
            facts=[f"{timezone.localtime(v.scheduled_start):%Y-%m-%d %H:%M}（北京时间） · {v.clinic.name} · {v.dentist.name}" for v in qs]
            if not facts: facts=["目前没有未来的有效预约；这不表示你没有历史记录。"]
    else:
        entries={
            "overview":("当前账号的今日工作概览","统计范围为当前业务角色可访问、计划日期是今天（北京时间）的预约。未到诊不等于取消，费用与临床质量不在这组计数中。","visits","查看授权范围内的预约","OPS-01 · 查询时权限范围与计划日期"),
            "appointment_policy":("预约与改期规则","患者与牙医均检查跨店时段冲突。改期保留原记录并创建后继预约；失败会撤销本次修改。爽约需在预约结束后人工核实，不能从未到诊直接推断。","visits","查看预约","BR-04/05/06/07 · 预约规则"),
            "care_help":("接诊需要牙医明确确认","由本次负责牙医复核过敏信息，逐项记录实际提供的治疗，再查看完成预览。预约意向不是实际治疗，AI不替代牙医确认。","visits","打开就诊列表","UC-06/07 · 实际治疗与责任"),
            "billing_policy":("完成开单的一致性","有治疗必须有实际明细并复核过敏；无治疗关闭保留到诊事实，生成零金额、零明细单。已发布单据不允许原地编辑；历史账单的原行数字更正须由负责牙医申请并由不同财务账号审核。","visits","查看就诊","BR-09/10/11/12 · 唯一账单与历史保护"),
            "help":("员工助手可以协助什么","支持授权范围内的今日计数，以及预约、接诊和结算规则说明。不生成SQL，不批量导出患者，不自动操作预约，不评判牙医临床水平。","dashboard","返回工作台","AI-02 · 员工助手边界"),
        }
        title,answer,name,label,source=entries.get(intent,entries["help"])
        if intent=="overview":
            qs=visible_visits(user).filter(scheduled_start__date=timezone.localdate())
            from adc_core.rules import STATUS_LABELS
            facts=[f"{STATUS_LABELS.get(r['status'],r['status'])}：{r['n']} 次" for r in qs.values("status").annotate(n=Count("id")).order_by("status")]
            if not facts: facts=["当前授权范围下今天没有可见预约；不代表全链没有预约。"]
    links=[{"label":label,"url":reverse(name)}]
    return {"title":title,"answer":answer,"facts":facts,"links":links,"source":source}

def respond(*,user,audience,message,consent=False):
    authorize(user,audience)
    text=validate_message(message)
    consume(user.pk)
    request_id=uuid4();start=time.monotonic();code=""
    intent=local_intent(text,audience)
    if intent=="clinical": mode="safety"
    elif settings.AI_MODE=="disabled": mode="disabled"
    elif settings.AI_MODE=="remote" and (not consent or settings.ADC_READ_ONLY): mode="local_only"
    elif settings.AI_MODE=="remote":
        cfg=provider.ProviderConfig(settings.AI_BASE_URL,settings.AI_API_KEY,settings.AI_MODEL,
            tuple(settings.AI_ALLOWED_HOSTS),settings.AI_TIMEOUT_SECONDS,settings.AI_TOKEN_LIMIT_FIELD)
        try:
            intent=provider.classify(redact(text),audience,cfg);mode="remote"
        except provider.ProviderError as exc:
            mode="fallback";code=exc.code
    else: mode="demo"
    # Re-query authorization and scoped facts AFTER the external request, not before.
    authorize(user,audience)
    ctx=getattr(user,'_adc_workspace',None)
    if ctx is not None:
        from workspaces.models import WorkspaceContext
        from workspaces.context import valid_context
        latest=WorkspaceContext.objects.get(pk=ctx.pk,user_id=user.pk)
        if latest.revision!=ctx.revision or latest.role!=ctx.role or latest.clinic_id!=ctx.clinic_id or not valid_context(user,latest):
            raise PermissionDenied('工作台已切换，请在当前页面重新发问。')
    from guidance.answers import navigation_answer
    result=navigation_answer(user,intent,text) or _answer(user,audience,intent)
    AssistantEvent.objects.create(request_id=request_id,user=user,audience=audience,intent=intent,mode=mode,
        result_code=code,input_chars=len(text),duration_ms=int((time.monotonic()-start)*1000))
    result.update({"request_id":str(request_id),"mode":mode,"mode_label":LABELS[mode],"intent":intent,
        "as_of":timezone.localtime().isoformat(),"actions_executed":False,
        "notice":"AI仅用于识别问题类别。回答来自系统规则和当前身份的任务目录；步骤进度不等于业务已保存。本次对话没有修改业务记录。"})
    return result
