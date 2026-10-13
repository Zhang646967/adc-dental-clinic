"""SU-26 pure contact-change rules. No ORM, secrets, clinical fields or external AI.
The audit cursor prevents an old A -> B -> A form from looking current again.
It is an application protocol, not protection against arbitrary owner SQL.
"""
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from types import MappingProxyType
import unicodedata
from uuid import UUID

CONTACT_LABELS = MappingProxyType({
    'phone': '联系电话', 'email': '邮箱', 'billing_address': '账单地址',
    'emergency_name': '紧急联系人', 'emergency_phone': '紧急联系电话',
})
CONTACT_FIELDS = tuple(CONTACT_LABELS)
LIMITS = MappingProxyType({'phone': 32, 'email': 254, 'billing_address': 255,
                          'emergency_name': 80, 'emergency_phone': 32})
REASONS = MappingProxyType({
    'PATIENT_UPDATE': '患者提供新的联络资料',
    'ENTRY_CORRECTION': '更正已核对的录入错误',
    'EMERGENCY_UPDATE': '患者确认更新紧急联系人',
})
CONTRACT = 'CONTACT-09A3.1'

class ContactInputError(ValueError):
    def __init__(self, field, message):
        super().__init__(message)
        self.field = field

@dataclass(frozen=True)
class ContactDifference:
    field: str
    label: str
    before: str
    after: str

def normalize_details(details):
    if not isinstance(details, Mapping) or set(details) != set(CONTACT_FIELDS):
        raise ContactInputError(None, '仅接收五项完整联络资料；身份、过敏和账号字段不在本次更正范围。')
    result = {}
    for name in CONTACT_FIELDS:
        value = details[name]
        if not isinstance(value, str):
            raise ContactInputError(name, f'{CONTACT_LABELS[name]}必须是文本。')
        # Reject, rather than silently delete, invisible/bidirectional control text.
        if any(unicodedata.category(c) in ('Cc', 'Cf', 'Cs', 'Zl', 'Zp') for c in value):
            raise ContactInputError(name, f'{CONTACT_LABELS[name]}含换行或不可见控制字符，请改为单行文本。')
        value = value.strip()
        if len(value) > LIMITS[name] or (name != 'email' and not value):
            raise ContactInputError(name, f'{CONTACT_LABELS[name]}不能为空且不能超过{LIMITS[name]}字。' if name != 'email'
                                    else '邮箱不能超过254字。')
        result[name] = value
    return result

def validate_reason(code):
    if not isinstance(code, str) or code not in REASONS:
        raise ContactInputError('reason_code', '请选择本次更正的核对依据。')
    return code

def differences(before, after):
    return tuple(ContactDifference(k, CONTACT_LABELS[k], before[k], after[k])
                 for k in CONTACT_FIELDS if before[k] != after[k])

def state_digest(*, patient_id, values, audit_cursor):
    if type(patient_id) is not int or patient_id < 1 or type(audit_cursor) is not int or audit_cursor < 0:
        raise ContactInputError(None, '资料版本不可用，请重新核对。')
    if set(values) != set(CONTACT_FIELDS) or any(not isinstance(v, str) for v in values.values()):
        raise ContactInputError(None, '资料快照不完整，请重新核对。')
    text = json.dumps([CONTRACT, patient_id, audit_cursor, [[k, values[k]] for k in CONTACT_FIELDS]],
                      ensure_ascii=True, separators=(',', ':'))
    return sha256(text.encode('utf-8')).hexdigest()

def validate_proposal(payload):
    required = {'contract', 'actor', 'patient', 'clinic', 'context', 'revision',
                'state', 'operation', 'values', 'reason_code'}
    if type(payload) is not dict or set(payload) != required or payload.get('contract') != CONTRACT:
        raise ContactInputError(None, '确认资料格式不正确，请重新开始。')
    for field in ('actor', 'patient', 'clinic'):
        if type(payload[field]) is not int or payload[field] < 1:
            raise ContactInputError(None, '确认目标不正确。')
    if type(payload['revision']) is not int or payload['revision'] < 0:
        raise ContactInputError(None, '工作上下文版本不正确。')
    for field in ('context', 'operation'):
        value = payload[field]
        try:
            if not isinstance(value, str) or str(UUID(value)) != value:
                raise ValueError
        except (ValueError, AttributeError, TypeError):
            raise ContactInputError(None, '确认标识不正确。') from None
    state = payload['state']
    if not isinstance(state, str) or len(state) != 64 or any(c not in '0123456789abcdef' for c in state):
        raise ContactInputError(None, '资料版本不正确。')
    normalized = normalize_details(payload['values'])
    if normalized != payload['values']:
        raise ContactInputError(None, '确认值必须与预览值一致，请重新开始。')
    validate_reason(payload['reason_code'])
    return payload
