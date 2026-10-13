"""Typed task notices, not instructions to perform task/business transitions.
No Django, network, free-form payload, patient data, or arbitrary URLs here.
"""
from datetime import datetime, timedelta

CONTRACT = 'TASK-NOTICE-1'
MAX_RECIPIENTS = 500
MAX_ATTEMPTS = 5
BATCH_MAX = 100
ACTIONS = {
    'open': ('有新的出诊协调任务', ('FRONT_DESK',)),
    'claim': ('协调任务已被受理', ('MANAGER',)),
    'progress': ('协调任务新增办理声明', ('MANAGER',)),
    'release': ('协调任务已退回待受理队列', ('FRONT_DESK', 'MANAGER')),
    'return': ('主管已退回协调任务', ('FRONT_DESK', 'MANAGER')),
    'submit': ('协调任务等待独立复核', ('MANAGER',)),
    'approve': ('协调任务的核对已通过', ('FRONT_DESK', 'MANAGER')),
    'cancel': ('协调任务已撤销', ('FRONT_DESK', 'MANAGER')),
}
EVENT_TYPES = {
    'open': 'TASK_CREATED', 'claim': 'TASK_CLAIMED', 'progress': 'TASK_REPORTED',
    'release': 'TASK_RELEASED', 'return': 'TASK_REQUEUED', 'submit': 'TASK_SUBMITTED',
    'approve': 'TASK_APPROVED', 'cancel': 'TASK_CANCELLED',
}
TASK_STATES = ('OPEN', 'IN_PROGRESS', 'READY', 'CLOSED', 'CANCELLED')
ACTION_STATE = {'open':'OPEN','claim':'IN_PROGRESS','progress':'IN_PROGRESS','release':'OPEN',
                'return':'OPEN','submit':'READY','approve':'CLOSED','cancel':'CANCELLED'}
DELIVERY_LABELS = {
    'PENDING': '等待后台派发', 'DELIVERED': '已生成站内消息',
    'NO_RECIPIENTS': '没有符合条件的收件人', 'FAILED': '派发失败，待处理',
}
ERROR_LABELS = {
    '': '', 'DELIVERY_ERROR': '消息写入失败，未记录原始异常内容',
    'INVALID_EVENT': '事件结构或关联需核对',
    'NO_RECIPIENTS': '事件发生时没有目标授权，或派发时授权已失效',
}
NOTICE_BOUNDARY = '通知不等于已受理、患者同意或业务完成；打开任务重新核对当前事实。'


def positive_int(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError('编号格式无效。')
    return value


def recipient_snapshot(rows):
    """Reject malformed/duplicate targets; never silently truncate recipients."""
    if not isinstance(rows, list) or len(rows) > MAX_RECIPIENTS:
        raise ValueError('收件范围超过本版上限，需要受控核对。')
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'user_id', 'grant_id', 'role'}:
            raise ValueError('收件范围结构无效。')
        positive_int(row['user_id']); positive_int(row['grant_id'])
        if row['role'] not in ('FRONT_DESK', 'MANAGER') or row['grant_id'] in seen:
            raise ValueError('收件授权重复或角色无效。')
        seen.add(row['grant_id']); result.append(dict(row))
    return sorted(result, key=lambda r: r['grant_id'])


def validate_event(*, action, event_state, task_id, clinic_id, task_revision, recipients):
    if action not in ACTIONS or event_state not in TASK_STATES:
        raise ValueError('通知类别无效。')
    if ACTION_STATE[action] != event_state:
        raise ValueError('事件状态与动作不一致。')
    positive_int(task_id); positive_int(clinic_id)
    if type(task_revision) is not int or task_revision < 0:
        raise ValueError('任务修订无效。')
    targets = recipient_snapshot(recipients)
    if any(r['role'] not in ACTIONS[action][1] for r in targets):
        raise ValueError('收件角色与事件类别不一致。')
    return targets


def retry_time(attempt, now):
    if type(attempt) is not int or not 1 <= attempt <= MAX_ATTEMPTS:
        raise ValueError('重试次数无效。')
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError('需要带时区的服务器时点。')
    if attempt == MAX_ATTEMPTS:
        return None
    return now + timedelta(seconds=(15, 60, 300, 900)[attempt - 1])


def bounded_batch(value):
    if type(value) is not int or not 1 <= value <= BATCH_MAX:
        raise ValueError('单轮批量必须在1到100之间。')
    return value


def validate_retry(state, retry_round, expected_round):
    if state != 'FAILED' or type(expected_round) is not int or expected_round < 0 or expected_round != retry_round:
        raise ValueError('通知状态已改变；请重新核对，不能重复重置。')


def title(action):
    if action not in ACTIONS:
        raise ValueError('通知类别无效。')
    return ACTIONS[action][0]
