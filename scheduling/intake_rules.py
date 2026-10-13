"""SU-32/33: admission policy, independent of ORM, UI and external AI.
Pause changes supply admission, not an existing service promise.
"""
from datetime import datetime
from uuid import UUID
import re

CONTRACT = 'INTAKE-09A8.1'
ACTIONS = {'pause': '暂停接收新预约', 'resume': '恢复接收新预约'}
REASONS = {'COORDINATION': '为已核对的出诊协调暂停新增',
           'CAPACITY_REVIEW': '核对人员或接待能力，暂停新增',
           'READY_TO_REOPEN': '已核对可继续接收新预约'}
ACTION_REASONS = {'pause': frozenset(('COORDINATION', 'CAPACITY_REVIEW')),
                  'resume': frozenset(('READY_TO_REOPEN',))}
PAUSED_MESSAGE = '该出诊已暂停接收新预约。请选择其他开放时段；已发出的有效邀约仍按原期限办理。'

class IntakeError(ValueError):
    pass


def require_new_admission(*, active, paused):
    if type(active) is not bool or type(paused) is not bool:
        raise IntakeError('出诊接收状态需要核对。')
    if not active:
        raise IntakeError('出诊已经停用，不能接收新预约。')
    if paused:
        raise IntakeError(PAUSED_MESSAGE)


def _aware(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise IntakeError('核验时间必须具有时区。')
    return value


def validate_transition(*, active, paused, ends_at, now, clinic_active,
                        dentist_active, action, reason):
    for value in (active, paused, clinic_active, dentist_active):
        if type(value) is not bool:
            raise IntakeError('状态资料格式不正确。')
    _aware(ends_at); _aware(now)
    if type(action) is not str or action not in ACTIONS:
        raise IntakeError('只允许暂停或恢复接收，不取消预约或停诊。')
    if type(reason) is not str or reason not in ACTION_REASONS[action]:
        raise IntakeError('请选择与本次操作相符的核对依据。')
    if not active or ends_at <= now:
        raise IntakeError('已停用或已结束的出诊不能从此入口暂停或恢复接收。')
    if paused == (action == 'pause'):
        raise IntakeError('当前接收状态已经与请求一致，请查看最新状态，不重复办理。')
    if action == 'resume' and not (clinic_active and dentist_active):
        raise IntakeError('诊所或牙医资料已停用，不能恢复接收新预约。')
    return action == 'pause'


def validate_reserved_offer(*, slot_id, patient_id, clinic_id, start, end,
                            offer_slot_id, offer_patient_id, offer_clinic_id,
                            offer_start, offer_end, expires_at, now,
                            offer_state, request_state, visit_id):
    """Only exact, live, already-published promises can bypass a pause.
    Caller must re-read and lock the actual offer, then authorize its owner/front.
    This predicate is NOT an authorization function or an HTTP parameter.
    """
    for value in (slot_id, patient_id, clinic_id, offer_slot_id, offer_patient_id, offer_clinic_id):
        if type(value) is not int or not 0 < value < 2**63:
            raise IntakeError('邀约关联需要核对，不能用于新预约。')
    for value in (start,end,offer_start,offer_end,expires_at,now): _aware(value)
    if (slot_id, patient_id, clinic_id, start, end) != (
            offer_slot_id, offer_patient_id, offer_clinic_id, offer_start, offer_end):
        raise IntakeError('邀约与拟预约的患者、出诊或时间不一致。')
    if (offer_state != 'PENDING' or request_state != 'OFFERED' or visit_id is not None
            or expires_at <= now or expires_at > offer_start or start <= now or end <= start):
        raise IntakeError('原邀约不再是有效待确认承诺，不能据此创建预约。')
    return True


def validate_payload(data, *, proposal):
    fields = {'contract','kind','actor','context','revision','clinic','slot','state'}
    if proposal: fields |= {'operation','action','reason'}
    if type(data) is not dict or set(data) != fields:
        raise IntakeError('接收控制确认字段不正确。')
    if data['contract'] != CONTRACT or data['kind'] != ('proposal' if proposal else 'state'):
        raise IntakeError('接收控制页面版本不匹配。')
    for k in ('actor','clinic','slot'):
        if type(data[k]) is not int or not 0 < data[k] < 2**63:
            raise IntakeError('接收控制对象编号不正确。')
    if type(data['revision']) is not int or data['revision'] < 0:
        raise IntakeError('上下文修订号无效。')
    for k in (('context','operation') if proposal else ('context',)):
        try:
            if type(data[k]) is not str or str(UUID(data[k])) != data[k]: raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise IntakeError('确认编号无效。') from None
    if type(data['state']) is not str or not re.fullmatch('[0-9a-f]{64}',data['state']):
        raise IntakeError('接收控制快照无效。')
    if proposal:
        a,r=data['action'],data['reason']
        if type(a) is not str or a not in ACTION_REASONS or type(r) is not str or r not in ACTION_REASONS[a]:
            raise IntakeError('操作及依据不匹配。')
    return data
