"""Read the retained case tables and render the full, indexed specifications."""
import json
import re

from reportlab.platypus import Table


GROUPS = (
    ("A", "基础业务与共享核验"),
    ("B", "资料维护、排班协调与站内消息"),
    ("C", "患者服务、诊疗、药事及经营业务"),
)
CASE_HEADING = re.compile(r"^#### ((?:SU-\d{2,3}|SF-01))\s+(.+)$", re.M)
FIELD_NAMES = {"前置": "前置条件", "触发/前置": "触发与前置条件",
               "成功后置": "成功结果", "成功后置条件": "成功结果", "扩展": "扩展路径"}


def publication_wording(text):
    text = re.sub(r'(?i)\btests?/[\w./-]+(?:\.py)?\s*', '', text)
    text = re.sub(r'[“「]?\bAI\b[”」]?', '智能引导', text)
    replacements = {
        "课程合成软件业务": "独立环境的软件业务",
        "课程合成资料": "验收资料",
        "课程合成": "验收",
        "合成身份": "验收身份",
        "合成患者": "验收患者",
        "合成": "验收",
        "医保模拟": "医保测算",
        "模拟待遇": "待遇测算",
        "模拟结算": "费用测算",
        "模拟": "受控",
        "开发者工具": "微信运行工具",
        "实际开发者": "系统维护人员",
        "开发者": "系统维护人员",
        "全量测试": "完整核验",
        "测试": "验证",
        "用例用例": "用例",
        "功能范围及业务验证见第5章。": "第 5 章列明本次实测范围。",
    }
    for before, after in replacements.items():
        text = text.replace(before, after)
    return text


def read_cases(source, index):
    entries = json.loads(index.read_text())
    body = source.read_text()
    matches = list(CASE_HEADING.finditer(body))
    specifications = {}
    for i, match in enumerate(matches):
        identifier = match[1]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        lines = body[match.end():end].splitlines()
        heading = next(line for line in lines if line.startswith("表"))
        group, number = re.match(r"表([A-C])-(\d+)", heading).groups()
        rows = []
        for line in lines:
            if not line.startswith("|"):
                continue
            row = [value.strip() for value in line.strip("|").split("|", maxsplit=1)]
            if row[0] in ("标题", "---", "用例名称", "实现状态"):
                continue
            rows.append([FIELD_NAMES.get(row[0], row[0]), publication_wording(row[1])])
        fields = {row[0] for row in rows}
        required = ({"调用关系", "输入及前置", "行为", "结果与最低保证"} if identifier == "SF-01"
                    else {"前置条件", "基本路径", "扩展路径", "成功结果", "最低保证"})
        if group == "B":
            required = {"基本路径", "扩展路径", "成功结果"}
        missing = required - fields
        if missing or identifier in specifications:
            raise ValueError(f"Incomplete or duplicate specification: {identifier}, {missing}")
        specifications[identifier] = {
            "id": identifier, "group": group, "number": number,
            "title": publication_wording(match[2].strip()), "rows": rows,
        }
    specifications["SF-01"]["rows"][-1][1] = (
        "返回可继续办理或具体失败原因。普通预约、改期及邀约确认须复核授权、本人适用范围"
        "和完整时段。已开通统一资源的门店同时检查诊室、椅位与设备。仅查询不占位。"
    )
    if set(specifications) != {entry["id"] for entry in entries}:
        raise ValueError("Use-case index differs from the retained set of specifications")
    return [specifications[match[1]] for match in matches]


def formatted_rows(entries):
    steps = re.compile(r"(?:\s+|(?<=[。；]))(?=\d{1,2}(?:）|\.\s))")
    return [["规约项目", "办理内容"]] + [
        [name, "\n".join(steps.split(value.replace(" / ", " "))) if name == "基本路径"
         else value.replace(" / ", "\n") if name in ("扩展路径", "验收目标")
         else value]
        for name, value in entries
    ]


def specification_tables(specification, make_table, width, available_height):
    table = make_table(formatted_rows(specification["rows"]), width, 1)
    if not isinstance(table, Table):
        raise TypeError("Expected a structured case table")
    fragments = []
    while table is not None:
        _, height = table.wrap(width, available_height)
        if height <= available_height:
            fragments.append(table)
            break
        pieces = table.split(width, available_height)
        if len(pieces) != 2:
            raise ValueError(f"Cannot split {specification['id']} at row boundary")
        fragments.append(pieces[0])
        table = pieces[1]
    return fragments
