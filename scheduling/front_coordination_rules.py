"""SU-31: read-only, per-slot coordination projection.

A projection is NOT a ticket, a booking hold, a patient consent or a maintenance
permission. Reuse availability policy for blockers; never mutate its facts.
"""
from dataclasses import dataclass
from datetime import datetime
from scheduling.availability_rules import (AvailabilityError, Impact, aware,
    parse_time, positive_id, block_reasons)

CONTRACT = 'FRONT-COORDINATION-09A7.1'
PAGE_SIZE = 20
VISIT_LABELS = {
    'SCHEDULED': '已预约', 'CHECKED_IN': '已到诊', 'COMPLETED': '治疗完成',
    'CLOSED_NO_TREATMENT': '无治疗关闭', 'CANCELLED': '已取消',
    'NO_SHOW': '已核实爽约', 'RESCHEDULED': '已改期替代',
}
OFFER_LABELS = {'PENDING': '等待确认', 'ACCEPTED': '已接受',
    'DECLINED': '已拒绝', 'EXPIRED': '已过期', 'REVOKED': '已撤回'}


@dataclass(frozen=True)
class CoordinationAssessment:
    code: str
    title: str
    explanation: str
    can_ask_manager_to_recheck: bool
    blockers: tuple[str, ...]


def assessment(slot: dict, impact: Impact, now: datetime, *, clinical_count: int,
               additional_anomalies: int = 0) -> CoordinationAssessment:
    aware(now)
    blockers = block_reasons(slot, impact, now)
    if impact.too_many or impact.anomalies or additional_anomalies:
        return CoordinationAssessment('REVIEW', '需要受控核对，不能判断已清空',
            '关联不一致或超过完整核对上限。本页不展示可能混入的患者记录，不自动修复，请联系获授权维护人员。', False, blockers)
    if not slot['is_active']:
        return CoordinationAssessment('INACTIVE', '原出诊已停用，保留关联历史',
            '本页不能恢复或改写原出诊；已取消或已改期的记录仍保留历史。', False, blockers)
    if parse_time(slot['starts_at']) <= now:
        return CoordinationAssessment('STARTED', '原出诊已开始，不属于空闲出诊维护范围',
            '请按实际接待状态核对。不要为调整排班而把已到诊或已完成记录取消、改期或改成爽约。', False, blockers)
    if clinical_count:
        return CoordinationAssessment('CARE_PROTECTED', '包含受保护接诊，不应为排班清空记录',
            '已到诊、治疗完成或无治疗关闭不走普通取消／改期。其他确需协调的预约仍须逐条核实患者意思。', False, blockers)
    if impact.blocking_visits or impact.effective_offers:
        return CoordinationAssessment('COORDINATE', '仍有关联承诺需要逐条核对',
            '列表表示关联业务，不表示已经下达停诊指令。前台须先与主管和患者核实，再通过原有入口分别处理。', False, blockers)
    return CoordinationAssessment('RECHECK', '当前未发现维护阻断，可请主管重新核对',
        '这是本次读取时点的结果，不是停用许可。本页未暂停接收新预约；主管提交变更时仍须重新核验。', True, blockers)


def visit_instruction(status: str, *, starts_at: datetime, now: datetime) -> dict:
    aware(starts_at); aware(now)
    if status not in VISIT_LABELS:
        raise AvailabilityError('预约状态需要核对。')
    if status == 'SCHEDULED':
        return {'label': VISIT_LABELS[status], 'group': 'promises', 'view': True,
            'reschedule': starts_at > now,
            'instruction': '先核对患者意思，再到预约详情办理；改到原出诊内不会解除原出诊的占用。' if starts_at > now else
            '计划开始时间已到。先核实实际到诊情况，不要仅因时间已过就认定爽约。'}
    if status in ('CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT'):
        return {'label': VISIT_LABELS[status], 'group': 'care', 'view': True,
            'reschedule': False, 'instruction': '受保护接诊。不得为了排班调整取消、改期或删除；由对应业务流程处理。'}
    return {'label': VISIT_LABELS[status], 'group': 'history', 'view': True,
        'reschedule': False, 'instruction': '这是保留的历史记录，不重复办理。后继预约请在原预约详情中核对。'}


def offer_instruction(state: str, *, expires_at: datetime, now: datetime) -> dict:
    aware(expires_at); aware(now)
    if state not in OFFER_LABELS:
        raise AvailabilityError('邀约状态需要核对。')
    if state == 'PENDING' and expires_at > now:
        return {'label': '有效，等待患者确认', 'group': 'promises', 'offer': True,
            'appointment': False, 'instruction': '仍在保留机会。先取得患者明确意思；本页不会代为拒绝或接受。'}
    if state == 'PENDING':
        return {'label': '已到期，状态尚未回收', 'group': 'expiry', 'offer': False,
            'appointment': False, 'instruction': '已不占用机会，也不能首次接受。可到本店候补执行原有回收操作；本页不自动回收。'}
    if state == 'ACCEPTED':
        return {'label': '已接受，已关联预约', 'group': 'history', 'offer': False,
            'appointment': True, 'instruction': '处理对象已是对应正式预约，不再次确认邀约。原确认截止时间不代表预约失效。'}
    return {'label': OFFER_LABELS[state], 'group': 'history', 'offer': False,
        'appointment': False, 'instruction': '保留历史；不通过本页恢复或重新发布。'}


def relation_anomalies(*, slot_id: int, visits: list, offers: list) -> int:
    """Strengthen identity/link consistency without loading names or contacts."""
    positive_id(slot_id)
    found = 0
    by_id = {v['id']: v for v in visits}
    for v in visits:
        if v.get('availability_slot_id') != slot_id:
            found += 1
        try:
            positive_id(v.get('patient_id'))
        except AvailabilityError:
            found += 1
    for o in offers:
        if o.get('slot_id') != slot_id:
            found += 1
        try:
            positive_id(o.get('request__patient_id'))
        except AvailabilityError:
            found += 1
        if o['state'] == 'ACCEPTED':
            v = by_id.get(o.get('visit_id'))
            if v is None or (v['patient_id'] != o['request__patient_id'] or
                    parse_time(v['scheduled_start']) != parse_time(o['starts_at']) or
                    parse_time(v['scheduled_end']) != parse_time(o['ends_at']) or
                    o['request__state'] != 'BOOKED'):
                found += 1
    return found


def safe_page(raw, count: int, size: int = PAGE_SIZE) -> tuple[int, int, int]:
    """Bound pagination; invalid/oversized text goes to page one, never SQL."""
    if type(count) is not int or count < 0 or type(size) is not int or not 1 <= size <= 200:
        raise AvailabilityError('分页范围无效。')
    pages = max(1, (count + size - 1) // size)
    value = str(raw) if raw is not None else '1'
    number = int(value) if len(value) <= 8 and value.isascii() and value.isdigit() else 1
    number = max(1, min(number, pages))
    return number, (number - 1) * size, pages


def origin_id(raw):
    """An object ID, not an arbitrary return URL or a permission token."""
    if type(raw) is not str or not raw.isascii() or not raw.isdigit() or len(raw)>19:
        return None
    value = int(raw)
    return value if 0 < value < 2**63 else None
