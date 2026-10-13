"""Pure validation for the bounded standard-price catalogue (not clinical advice)."""
from decimal import Decimal, InvalidOperation
import re

class CatalogInputError(ValueError):
    pass

def validate_price(value):
    if isinstance(value, (bool, float)):
        raise CatalogInputError('单价须为精确十进制金额，不能使用浮点数。')
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise CatalogInputError('请输入有效的非负金额。')
    if not price.is_finite() or price < 0 or price > Decimal('9999999999.99'):
        raise CatalogInputError('单价须在0至9999999999.99之间。')
    if price.as_tuple().exponent < -2:
        raise CatalogInputError('单价最多两位小数，不会自动舍入你的输入。')
    return price.quantize(Decimal('0.01'))

def validate_definition(code, name, unit):
    code, name, unit = (str(x or '').strip() for x in (code,name,unit))
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,23}',code):
        raise CatalogInputError('项目编码须为1至24位大写字母、数字、下划线或短横线。')
    if not 1 <= len(name) <= 120 or not 1 <= len(unit) <= 120:
        raise CatalogInputError('项目名称和单位说明均须为1至120字。')
    return code,name,unit

def validate_reason(reason):
    reason=str(reason or '').strip()
    if not 4 <= len(reason) <= 500:
        raise CatalogInputError('请填写4至500字的目录变更依据，不填写密码或患者资料。')
    return reason
