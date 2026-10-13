"""SU-27/28: framework-independent rules for bounded reference-data registration.
A recorded qualification is NOT verified licensing or a scheduling eligibility policy.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
import unicodedata
from uuid import UUID

CONTRACT = 'DIRECTORY-09A5.1'
KINDS = {'clinic': '诊所', 'dentist': '牙医', 'qualification': '资格类别'}
FIELDS = {
    'clinic': ('clinic_code', 'name', 'postal_address', 'supervisor_name', 'phone', 'email', 'area_sqm'),
    'dentist': ('employee_no', 'name', 'date_of_birth', 'home_address', 'phone', 'email'),
    'qualification': ('code', 'name'),
}
LABELS = {'clinic_code': '诊所编码', 'employee_no': '牙医员工编号', 'code': '资格编码',
          'name': '名称', 'postal_address': '诊所地址', 'supervisor_name': '主管联络姓名',
          'phone': '联系电话', 'email': '邮箱', 'area_sqm': '面积（平方米）',
          'date_of_birth': '出生日期', 'home_address': '联系地址'}
REASONS = {'SOURCE_RECORD': '依据已核对的合成基础资料登记',
           'CORRECT_LINK': '更正误关联的资格记录', 'RESTORE_LINK': '重新核对后恢复资格关联'}
ACTIONS = frozenset(('attach', 'withdraw'))
CODE_RE = re.compile(r'[A-Z0-9][A-Z0-9_-]{0,23}\Z')

class DirectoryInputError(ValueError):
    pass

@dataclass(frozen=True)
class DisplayRow:
    label: str
    value: str


def clean_text(value, label, limit):
    if type(value) is not str:
        raise DirectoryInputError(f'{label}必须是文本。')
    text = value.strip()
    if not text or len(text) > limit or any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs') for c in text):
        raise DirectoryInputError(f'{label}须为1至{limit}字，不含隐藏控制字符。')
    return text


def clean_code(value, label='编码'):
    value = clean_text(value, label, 24)
    if not CODE_RE.fullmatch(value):
        raise DirectoryInputError(f'{label}须以大写字母或数字开头，仅含大写字母、数字、短横线或下划线。')
    return value


def normalize_registration(kind, details, *, today):
    if type(kind) is not str or kind not in FIELDS or type(details) is not dict or set(details) != set(FIELDS[kind]):
        raise DirectoryInputError('资料类型或字段范围不符；不接受状态、授权或临床字段。')
    if type(today) is not date:
        raise DirectoryInputError('服务器日期不可用。')
    limits = {'name': 80 if kind == 'dentist' else 120, 'postal_address': 255,
              'home_address': 255, 'supervisor_name': 80, 'phone': 32, 'email': 254}
    result = {}
    for key in FIELDS[kind]:
        value = details[key]
        if key in ('clinic_code', 'employee_no', 'code'):
            result[key] = clean_code(value, LABELS[key])
        elif key == 'date_of_birth':
            try:
                dob = value if type(value) is date else date.fromisoformat(value) if type(value) is str else None
            except ValueError:
                dob = None
            if dob is None or dob > today or (type(value) is str and value != dob.isoformat()):
                raise DirectoryInputError('出生日期须为有效日期且不晚于服务器今天；不从年龄推断执业资格。')
            result[key] = dob.isoformat()
        elif key == 'area_sqm':
            if type(value) not in (str, Decimal):
                raise DirectoryInputError('面积须为正数，最多两位小数。')
            text = str(value).strip()
            if not re.fullmatch(r'\d{1,8}(?:\.\d{1,2})?', text):
                raise DirectoryInputError('面积须为正数，整数部分最多8位、小数最多2位；不自动舍入。')
            amount = Decimal(text)
            if amount <= 0:
                raise DirectoryInputError('面积必须大于0。')
            result[key] = format(amount.quantize(Decimal('0.01')), 'f')
        else:
            result[key] = clean_text(value, LABELS[key], limits[key])
    # EmailField validation is deliberately left to the model field at the framework boundary.
    return result


def display_rows(kind, values):
    if kind not in FIELDS or set(values) != set(FIELDS[kind]):
        raise DirectoryInputError('无法形成资料核对摘要。')
    return tuple(DisplayRow(LABELS[key], str(values[key])) for key in FIELDS[kind])


def validate_reason(reason, *, action='register'):
    allowed = {'SOURCE_RECORD'} if action == 'register' else {'CORRECT_LINK'} if action == 'withdraw' else {'SOURCE_RECORD', 'RESTORE_LINK'}
    if type(reason) is not str or reason not in allowed:
        raise DirectoryInputError('请选择与本次操作一致的登记依据。')
    return reason


def positive_id(value):
    if type(value) is not int or value <= 0 or value > 9223372036854775807:
        raise DirectoryInputError('对象编号不合法。')
    return value


def association_transition(action, *, dentist_active, qualification_active, link_active):
    if type(action) is not str or action not in ACTIONS or type(dentist_active) is not bool or type(qualification_active) is not bool or (link_active is not None and type(link_active) is not bool):
        raise DirectoryInputError('关联状态或动作不合法。')
    if action == 'withdraw':
        if link_active is not True:
            raise DirectoryInputError('当前没有可撤回的有效关联；请重新核对。')
        return 'WITHDRAW', False
    if not dentist_active or not qualification_active:
        raise DirectoryInputError('牙医或资格目录已停用，不能新增或恢复关联。')
    if link_active is True:
        raise DirectoryInputError('该牙医已经登记此资格，不重复关联。')
    return ('RESTORE' if link_active is False else 'ATTACH'), True


def state_digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def validate_payload(payload):
    if type(payload) is not dict:
        raise DirectoryInputError('确认载荷无效。')
    common = {'contract', 'actor', 'context', 'revision', 'operation', 'kind', 'action', 'values', 'reason_code'}
    expected = common | ({'state'} if payload.get('kind') == 'association' else set())
    if set(payload) != expected or payload.get('contract') != CONTRACT:
        raise DirectoryInputError('确认资料版本或字段不符。')
    positive_id(payload['actor'])
    if type(payload['revision']) is not int or payload['revision'] < 0:
        raise DirectoryInputError('工作上下文修订无效。')
    for key in ('context', 'operation'):
        try:
            if type(payload[key]) is not str or str(UUID(payload[key])) != payload[key]:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise DirectoryInputError('确认编号无效。') from None
    if payload['kind'] == 'association':
        if payload['action'] not in ACTIONS or type(payload['values']) is not dict or set(payload['values']) != {'dentist_id', 'qualification_id'}:
            raise DirectoryInputError('资格关联载荷无效。')
        for value in payload['values'].values():
            positive_id(value)
        if type(payload['state']) is not str or not re.fullmatch(r'[0-9a-f]{64}', payload['state']):
            raise DirectoryInputError('关联快照无效。')
    elif payload['kind'] not in FIELDS or payload['action'] != 'register' or type(payload['values']) is not dict or set(payload['values']) != set(FIELDS[payload['kind']]):
        raise DirectoryInputError('登记资料无效。')
    validate_reason(payload['reason_code'], action=payload['action'])
    return payload
