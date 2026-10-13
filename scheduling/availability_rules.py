"""SU-29/30: pure contracts for replacing/stopping future availability.
No Django, SQL, user records or network. A replacement preserves its predecessor.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256
import json
import re
from uuid import UUID
from zoneinfo import ZoneInfo

CONTRACT = 'AVAILABILITY-09A6.1'
ACTIONS = {'replace': '调整并新建替代时段', 'deactivate': '停用原出诊时段'}
REASONS = {'PLAN_CHANGED': '已核对的出诊计划调整',
           'TIME_CORRECTION': '已核对的时间录入更正',
           'UNAVAILABLE': '已核对的人员或诊所不可用情况'}
LIVE_VISIT_STATES = frozenset(('SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT'))
TERMINAL_VISIT_STATES = frozenset(('CANCELLED', 'NO_SHOW', 'RESCHEDULED'))
OFFER_STATES = frozenset(('PENDING', 'ACCEPTED', 'DECLINED', 'EXPIRED', 'REVOKED'))
MAX_RELATIONS = 1000
LOCAL_ZONE = ZoneInfo('Asia/Shanghai')

class AvailabilityError(ValueError):
    pass


def positive_id(value):
    if type(value) is not int or not 0 < value < 2**63:
        raise AvailabilityError('对象编号无效。')
    return value


def aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise AvailabilityError('时间必须明确时区。请按北京时间重新输入。')
    return value


def interval(start, end, now):
    aware(start); aware(end); aware(now)
    if start <= now:
        raise AvailabilityError('新开始时间必须晚于当前时间。')
    if end <= start:
        raise AvailabilityError('新结束时间必须晚于新开始时间。')
    if start.second or start.microsecond or end.second or end.microsecond:
        raise AvailabilityError('新出诊时间请精确到分钟，不要输入秒或小数秒。')
    return start, end


def parse_time(value):
    if type(value) is not str or not 1 <= len(value) <= 40:
        raise AvailabilityError('确认时间格式不正确。')
    try:
        return aware(datetime.fromisoformat(value))
    except (TypeError, ValueError, OverflowError) as exc:
        raise AvailabilityError('确认时间格式不正确或缺少时区。') from exc


def overlaps(a, b, c, d):
    return a < d and c < b  # Half-open intervals: adjacent periods are allowed.


def display_time(value):
    return aware(value).astimezone(LOCAL_ZONE).strftime('%Y年%m月%d日 %H:%M')


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Impact:
    visit_count: int
    blocking_visits: int
    offer_count: int
    effective_offers: int
    expired_pending: int
    anomalies: int
    too_many: bool

    @property
    def clear(self):
        return not (self.blocking_visits or self.effective_offers or self.anomalies or self.too_many)


def assess_relations(*, slot, visits, offers, now, visit_count=None, offer_count=None):
    """Count promises, not patients. No names, contacts or clinical facts required.
    All related history participates in the snapshot; truncated input fails closed.
    """
    aware(now)
    start, end = parse_time(slot['starts_at']), parse_time(slot['ends_at'])
    vc = len(visits) if visit_count is None else visit_count
    oc = len(offers) if offer_count is None else offer_count
    too_many = vc > MAX_RELATIONS or oc > MAX_RELATIONS or vc != len(visits) or oc != len(offers)
    blocked = effective = expired = anomalies = 0
    visit_ids = {row['id'] for row in visits}
    for row in visits:
        st = row['status']
        a, b = parse_time(row['scheduled_start']), parse_time(row['scheduled_end'])
        blocked += st in LIVE_VISIT_STATES
        anomalies += bool(st not in LIVE_VISIT_STATES | TERMINAL_VISIT_STATES or
            row['clinic_id'] != slot['clinic_id'] or row['dentist_id'] != slot['dentist_id'] or
            a < start or b > end or a >= b)
    for row in offers:
        a, b, expiry = parse_time(row['starts_at']), parse_time(row['ends_at']), parse_time(row['expires_at'])
        st = row['state']
        effective += st == 'PENDING' and expiry > now
        expired += st == 'PENDING' and expiry <= now
        anomalies += bool(st not in OFFER_STATES or row['request__clinic_id'] != slot['clinic_id'] or
            a < start or b > end or a >= b or expiry > a or
            (st == 'ACCEPTED' and (row['visit_id'] is None or row['visit_id'] not in visit_ids)) or
            (st != 'ACCEPTED' and row['visit_id'] is not None) or
            (st == 'PENDING' and row['request__state'] != 'OFFERED'))
    return Impact(vc, blocked, oc, effective, expired, anomalies, too_many)


def block_reasons(slot, impact, now):
    aware(now)
    reasons = []
    if not slot['is_active']:
        reasons.append('原时段已停用；历史记录不能从本入口恢复或改写。')
    if parse_time(slot['starts_at']) <= now:
        reasons.append('原时段已经开始或已经结束；本入口只处理尚未开始的出诊。')
    if impact.too_many:
        reasons.append('关联记录超过本次完整核对上限；请交由受控维护处理，不按截断结果提交。')
    if impact.blocking_visits:
        reasons.append('仍有关联预约、已到诊或已完成接诊记录；请由前台按原业务流程协调，不能随出诊调整一并修改。')
    if impact.effective_offers:
        reasons.append('仍有未到期的候补邀约；请等待患者决定或期限结束，再重新核对。')
    if impact.anomalies:
        reasons.append('出诊与业务记录的关联需要核对；暂不允许变更，也不自动修补。')
    return tuple(reasons)


def validate_action(action, reason_code):
    if type(action) is not str or action not in ACTIONS:
        raise AvailabilityError('仅支持调整替换或停用，不支持删除、换牙医、换诊所或恢复历史时段。')
    if type(reason_code) is not str or reason_code not in REASONS:
        raise AvailabilityError('请选择已核对的变更依据。')


def validate_replacement(slot, impact, now, *, action, start=None, end=None):
    if action not in ACTIONS:
        raise AvailabilityError('未知操作。')
    reasons = block_reasons(slot, impact, now)
    if reasons:
        raise AvailabilityError(' '.join(reasons))
    if action == 'replace':
        if not slot['clinic_active'] or not slot['dentist_active']:
            raise AvailabilityError('诊所或牙医已停用，不能建立替代出诊。')
        interval(start, end, now)
        if start == parse_time(slot['starts_at']) and end == parse_time(slot['ends_at']):
            raise AvailabilityError('新旧时间相同，无需创建替代记录。')
    elif start is not None or end is not None:
        raise AvailabilityError('停用操作不能夹带新时间。')


def validate_payload(payload, *, proposal):
    common = {'contract', 'kind', 'actor', 'context', 'revision', 'clinic', 'slot', 'state'}
    wanted = common | ({'operation', 'action', 'reason', 'start', 'end'} if proposal else set())
    if type(payload) is not dict or set(payload) != wanted:
        raise AvailabilityError('确认资料字段不正确。')
    if payload['contract'] != CONTRACT or payload['kind'] != ('proposal' if proposal else 'state'):
        raise AvailabilityError('确认资料版本不正确。')
    for key in ('actor', 'clinic', 'slot'):
        positive_id(payload[key])
    if type(payload['revision']) is not int or payload['revision'] < 0:
        raise AvailabilityError('上下文版本无效。')
    for key in (('context', 'operation') if proposal else ('context',)):
        try:
            if type(payload[key]) is not str or str(UUID(payload[key])) != payload[key]:
                raise ValueError()
        except (ValueError, TypeError, AttributeError) as exc:
            raise AvailabilityError('确认编号无效。') from exc
    if type(payload['state']) is not str or not re.fullmatch('[0-9a-f]{64}', payload['state']):
        raise AvailabilityError('状态摘要无效。')
    if proposal:
        validate_action(payload['action'], payload['reason'])
        if payload['action'] == 'replace':
            a, b = parse_time(payload['start']), parse_time(payload['end'])
            if a >= b:
                raise AvailabilityError('确认时间倒置。')
        elif payload['start'] is not None or payload['end'] is not None:
            raise AvailabilityError('停用确认中不应包含替代时间。')
    return payload
