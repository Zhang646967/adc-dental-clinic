"""One bounded entry validator for chart buttons and keyboard forms.

C2.1 synthetic notation subset. It records observations, not a diagnosis or a
clinical treatment recommendation. Other locations remain narrative entries.
"""
from adc_core.rules import RuleError

DENTITIONS = {"PERMANENT": "恒牙列", "PRIMARY": "乳牙列", "MIXED": "混合牙列", "UNASSESSED": "尚未核对牙列"}
PERMANENT = tuple(q*10+n for q in range(1,5) for n in range(1,9))
PRIMARY = tuple(q*10+n for q in range(5,9) for n in range(1,6))
KINDS = {"OBSERVATION": "检查发现", "MISSING": "缺失", "EXISTING_WORK": "既往处置", "OTHER": "其他观察"}
SURFACES = {"M": "近中面", "D": "远中面", "B": "唇颊面", "L": "舌腭面", "O": "咬合面", "I": "切缘"}

def validate_finding(data, dentition):
    if not isinstance(data,dict): raise RuleError("请使用牙位观察表单录入。")
    try: tooth=int(data["tooth"])
    except (KeyError,ValueError,TypeError): raise RuleError("请选择完整牙位编号。")
    if dentition not in DENTITIONS or dentition=="UNASSESSED":
        raise RuleError("记录牙位前请明确核对牙列。")
    allowed=PERMANENT if dentition=="PERMANENT" else PRIMARY if dentition=="PRIMARY" else PERMANENT+PRIMARY
    if tooth not in allowed: raise RuleError("此牙位不属于已核对牙列；请检查乳牙或恒牙编号。")
    surface=data.get("surface","")
    if not isinstance(surface,str): raise RuleError("请使用页面提供的牙面选项。")
    surface=surface.upper().strip()
    if any(s not in SURFACES for s in surface) or len(surface)!=len(set(surface)):
        raise RuleError("牙面选项无效或重复，请重新核对。")
    if tooth%10<=3 and "O" in surface or tooth%10>3 and "I" in surface:
        raise RuleError("切缘与咬合面不适用于此牙位，请重新核对。")
    kind=data.get("kind")
    if kind not in KINDS: raise RuleError("请选择本次观察类别。")
    if kind=="MISSING" and surface: raise RuleError("整牙缺失不应记录为局部牙面。")
    detail=data.get("detail","")
    if not isinstance(detail,str) or not 1<=len(detail.strip())<=1000:
        raise RuleError("观察说明须填写1至1000字。")
    return dict(tooth=tooth,surface="".join(s for s in SURFACES if s in surface),kind=kind,detail=detail.strip())
