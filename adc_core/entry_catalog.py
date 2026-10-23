"""Curated, public business walkthroughs. No identities, records or commands.

The same catalogue renders the HTTP entry and the portable local entry. Links
are navigation only: each destination keeps its own authentication and scope.
"""
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template


@dataclass(frozen=True)
class Step:
    role: str
    instruction: str
    route: str
    link_label: str


@dataclass(frozen=True)
class Scenario:
    key: str
    title: str
    summary: str
    roles: tuple[str, ...]
    steps: tuple[Step, ...]
    expected: str
    exception: str


SCENARIOS = (
    Scenario("booking", "预约、改期与取消", "先核对安排，再确认决定，最后检查原新记录。",
        ("患者", "前台"), (
            Step("患者", "选择服务和未来时间，核对诊所、医师及起止时间后明确预约。", "portal_slots", "选择就诊时间"),
            Step("患者", "从本人预约进入改期，比较原新安排，再明确确认；另选一条合成预约演示取消。", "portal_appointments", "查看我的预约"),
            Step("前台", "使用同一诊所的前台账号核对日周排班和预约结果。", "schedule_calendar", "核对日周排班"),
        ), "一次确认只形成一个结果；改期保留原约历史并关联唯一新约；取消保留取消历史。",
        "核对后时段被占：提交失败，原预约仍保留；重新查询后再决定。"),
    Scenario("waitlist", "候补与限时邀约", "没有合适时间时，登记偏好并等待前台协调。",
        ("患者", "前台"), (
            Step("患者", "登记可接受的诊所、服务和未来时间范围，查看候补状态。", "waitlist", "查看候补与邀约"),
            Step("前台", "在同店生成建议，核对资源后明确发布限时邀约。", "schedule_plans", "办理候补排班"),
            Step("患者", "核对邀约截止时间，选择新增预约或替换指定原约，预览后确认。", "waitlist", "核对并处理邀约"),
        ), "登记和建议不形成预约；明确接受后，两端显示同一正式预约；替换时保留唯一后继。",
        "拒绝邀约或退出候补：未确认的暂占按规则释放，已有正式预约继续保留。"),
    Scenario("reception", "电话接待与成约", "把咨询、联系责任和正式预约分别核对。",
        ("前台",), (
            Step("前台", "核对患者身份和需求，新建合成接待单；不按相同手机号自动认定身份。", "reception_list", "打开电话接待"),
            Step("前台", "查可用资源，记录协商与后续责任；取得明确同意后办理正式预约。", "resource_candidates", "查询服务与资源"),
            Step("前台", "返回原接待单，核对沟通历史、成约状态及关联预约。", "reception_list", "核对接待结果"),
        ), "咨询记录与预约各有历史；成功成约有唯一关联，联系未完成时仍有责任与期限。",
        "患者拒绝或资源冲突：保留未成约原因及后续处理，不显示预约成功。"),
    Scenario("care", "到诊、治疗与账单", "由实际负责岗位记录服务，再核对已发布账单。",
        ("前台", "医生", "患者"), (
            Step("前台", "找到本店预约，核对资源与到诊事实，再明确登记到诊。", "visits", "查看预约与到诊"),
            Step("医生", "使用负责该次就诊的医生账号，记录合成治疗事实，核对后完成接诊。", "doctor_home", "进入本人接诊"),
            Step("患者", "在本人就诊详情查看已发布账单，比较治疗项目和金额。", "portal_appointments", "查看本人就诊与账单"),
        ), "账单来自已完成接诊的发布版本；无治疗应保留原因和零金额，不伪造治疗项目。",
        "未完成接诊或资料不全：显示待处理原因，不能把草稿当作已发布账单。"),
    Scenario("cash", "收款、退款与独立复核", "分清账单收入、待审请求和已入账资金。",
        ("前台", "财务", "诊所主管"), (
            Step("前台", "对合成账单核对应收并提出资金记录请求；请求本身不是收款成功。", "cash_receivables", "核对应收与余额"),
            Step("财务", "由不同人员核对依据和金额后审核；另行核对退款或冲销。", "cash_list", "打开现金账与审核"),
            Step("诊所主管", "核对本店当日四类资金、未决事项与差异，再交由财务独立复核。", "daily_close_list", "核对日结与交接"),
        ), "待审不计入已入账资金；原申请人不能自批；收款、退款、账单收入分别保留。",
        "重复确认返回既有结果；金额或账单已变化时重新核对，不重复计款。"),
    Scenario("equipment", "设备维护与预约协调", "先看受影响安排，再交接维护与验收责任。",
        ("诊所主管", "前台", "财务"), (
            Step("诊所主管", "在本店设备台账提出合成维护工单，核对受影响预约。", "maintenance_list", "查看维护工单"),
            Step("前台", "逐条核对影响，与患者协商兼容资源或改期；未经确认不自动更改。", "resource_coordination_list", "查看资源影响"),
            Step("诊所主管", "完成维护后的事实核对与独立验收，再核对费用来源和财务状态。", "equipment_expenses", "查看设备费用"),
        ), "维修历史、安排协调和费用各自保留；送修不自动取消预约，也不自动记为付款。",
        "资源不适配或患者拒绝：保留原约及待协调责任；缺失费用不能当作零费用。"),
)

ENTRY_ROUTES = frozenset({"login", "portal_login", "dashboard", "select_role", "guide_index"}
    | {step.route for scenario in SCENARIOS for step in scenario.steps})


def render_entry(routes, *, standalone=False, root=None):
    """Render only curated paths. Never interpolate request/query/user data.

    `routes` contains resolved local paths. The standalone entry pins its links
    to the established loopback gateway; HTTP rendering stays on its own origin.
    """
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    paths = {}
    for name in ENTRY_ROUTES:
        path = routes[name]
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise ValueError("Entry destinations must be local absolute paths.")
        if any(c in path for c in ("<", ">", "\\", "?", "#", "\r", "\n")):
            raise ValueError("Entry destinations must be resolved routes without parameters.")
        paths[name] = ("http://127.0.0.1:18000" if standalone else "") + path

    def link(name, label, css=""):
        return '<a class="' + escape(css, quote=True) + '" href="' + escape(paths[name], quote=True) + '">' + escape(label) + '</a>'

    cards = []
    for index, scenario in enumerate(SCENARIOS, 1):
        steps = "".join('<li><span class="step-role">' + escape(step.role) + '</span><div><p>'
            + escape(step.instruction) + '</p>' + link(step.route, step.link_label + " →") + '</div></li>'
            for step in scenario.steps)
        roles = "、".join(scenario.roles)
        choices = "".join('<label><input type="radio" name="result-' + scenario.key + '" value="' + code
            + '"' + (' checked' if code == 'NOT_CHECKED' else '') + '><span>' + label + '</span></label>'
            for code, label in (("NOT_CHECKED", "尚未核验"), ("MATCHED", "符合预期"), ("ISSUE", "发现问题")))
        cards.append('<article class="scenario" id="' + scenario.key + '" data-scenario="' + scenario.key
            + '" data-roles="' + escape(roles, quote=True) + '"><div class="scenario-heading"><span class="scenario-number">'
            + f'{index:02}' + '</span><div><p class="scenario-roles">' + escape(roles) + '</p><h3>'
            + escape(scenario.title) + '</h3></div></div><p class="scenario-summary">' + escape(scenario.summary)
            + '</p><details><summary>查看办理步骤与核对标准</summary><ol class="scenario-steps">' + steps
            + '</ol><div class="expected"><strong>应看到的结果</strong><p>' + escape(scenario.expected)
            + '</p></div><div class="exception"><strong>再核对一种异常</strong><p>' + escape(scenario.exception)
            + '</p></div></details><fieldset class="result-picker" hidden><legend>个人核对结果 · '
            + escape(scenario.title) + '</legend>' + choices + '</fieldset></article>')

    if standalone:
        assets = '<style>' + (root / 'static/system_entry.css').read_text(encoding='utf-8') + '</style>'
        assets += '<script defer>' + (root / 'static/system_entry.js').read_text(encoding='utf-8') + '</script>'
    else:
        assets = '<link rel="stylesheet" href="/static/system_entry.css"><script defer src="/static/system_entry.js"></script>'
    return Template((root / 'templates/entry/index.html').read_text(encoding='utf-8')).substitute(
        assets=assets, scenarios="\n".join(cards),
        patient_link=link('portal_login', '进入患者服务 →', 'entry-button'),
        staff_link=link('login', '进入员工工作台 →', 'entry-button entry-button-light'),
        workspace_link=link('dashboard', '回到当前工作台 →'),
        role_link=link('select_role', '查看已授权身份 →'),
        guide_link=link('guide_index', '打开当前身份的逐步指南 →'),
        location_note=('本入口连接当前电脑上的 ADC：127.0.0.1:18000。请在运行系统的 Mac 上打开。' if standalone
            else '使用已分配的课程账号，按本人身份和诊所范围办理。'),
    )
