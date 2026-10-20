"""Pure coordination-task policy. Task statements are NOT patient consent.
The task owns workflow only; it never cancels a Visit, accepts an offer, or
changes the slot's admission/availability state.
"""
from dataclasses import dataclass
import re
from uuid import UUID
from scheduling.availability_rules import aware, parse_time, positive_id

CONTRACT = 'COORDINATION-TASK-09A9.1'
STATES = {'OPEN': '待前台受理', 'IN_PROGRESS': '前台协调中', 'READY': '待主管复核',
          'CLOSED': '协调核对已通过', 'CANCELLED': '任务已撤销'}
ACTIVE_STATES = ('OPEN', 'IN_PROGRESS', 'READY')
PURPOSES = {'DEACTIVATE': '为停用原出诊协调', 'REPLACE': '为调整原出诊协调'}
ACTIONS = {'open': '发起协调任务', 'claim': '受理任务', 'progress': '记录办理声明',
           'release': '退回待受理队列', 'submit': '提交主管复核', 'return': '退回重新受理',
           'approve': '确认协调核对通过', 'cancel': '撤销协调任务'}
REASONS = {'PLAN_CHANGE': '已核对的出诊计划变化', 'STAFF_UNAVAILABLE': '已核对的人员安排变化',
           'TAKE_RESPONSIBILITY': '本人受理并承担跟进责任', 'HANDOVER': '本人需要交接处理',
           'NO_RESPONSE': '已尝试联络，尚未得到回复（本人声明）',
           'WAIT_DECISION': '已说明安排，仍等待患者决定（本人声明）',
           'USED_ORIGINAL': '已转原业务流程办理（本人声明，需核对记录）',
           'NEED_HELP': '需要主管进一步协调（本人声明）',
           'CHECKED_FACTS': '已核对当前关联业务，请主管独立复核',
           'REVIEW_RETURN': '复核需补充或重新办理', 'OWNER_UNAVAILABLE': '原受理人无法继续跟进',
           'REVIEW_PASSED': '已独立核对当前事实与维护条件',
           'PLAN_WITHDRAWN': '原协调计划已撤回', 'OTHER_HANDLING': '需转其他受控流程处理'}
ACTION_REASONS = {
    'open': ('PLAN_CHANGE', 'STAFF_UNAVAILABLE'), 'claim': ('TAKE_RESPONSIBILITY',),
    'progress': ('NO_RESPONSE','WAIT_DECISION','USED_ORIGINAL','NEED_HELP'),
    'release': ('HANDOVER',), 'submit': ('CHECKED_FACTS',),
    'return': ('REVIEW_RETURN','OWNER_UNAVAILABLE'), 'approve': ('REVIEW_PASSED',),
    'cancel': ('PLAN_WITHDRAWN','OTHER_HANDLING')}
MANAGER_ACTIONS = frozenset(('open','return','approve','cancel'))
FRONT_ACTIONS = frozenset(('open','claim','progress','release','submit'))

class TaskError(ValueError):
    pass

@dataclass(frozen=True)
class ReviewGate:
    reasons: tuple
    @property
    def clear(self):
        return not self.reasons


def review_gate(slot, impact, now):
    """A fresh readiness assessment; neither a freeze nor a maintenance permit."""
    aware(now)
    reasons = []
    if not slot['is_active']:
        reasons.append('原出诊已停用；不能把本任务复核当成维护成功，请主管核对或撤销任务。')
    if parse_time(slot['starts_at']) <= now:
        reasons.append('出诊已开始或已结束；本任务不处理临床停诊，请转受控现场流程。')
    if not slot['booking_paused']:
        reasons.append('当前仍接收新增；请前台先暂停新增，再重新核对。')
    if impact.too_many:
        reasons.append('关联记录超过完整核对上限，不能用当前页或部分结果结案。')
    if impact.anomalies:
        reasons.append('关联记录需核对；不自动修补，也不能结案。')
    if impact.blocking_visits:
        reasons.append('仍有受保护的预约或接诊记录；办理声明不能替代原流程处置。')
    if impact.effective_offers:
        reasons.append('仍有未到期邀约；暂停新增不撤销已经发出的承诺。')
    return ReviewGate(tuple(reasons))


def validate_options(action, reason, *, purpose='', target_kind='', target_id=None):
    if type(action) is not str or action not in ACTIONS:
        raise TaskError('不支持此任务操作。')
    if type(reason) is not str or reason not in ACTION_REASONS[action]:
        raise TaskError('请选择与本次操作相符的依据。')
    if action == 'open':
        if type(purpose) is not str or purpose not in PURPOSES:
            raise TaskError('请选择协调目标；不会自动停用或调整出诊。')
    elif purpose != '':
        raise TaskError('已有任务不能夹带新的协调目标。')
    if action == 'progress':
        if target_kind not in ('', 'visit', 'offer') or type(target_kind) is not str:
            raise TaskError('办理对象类别无效。')
        if target_kind:
            try: positive_id(target_id)
            except ValueError as exc: raise TaskError('办理对象编号无效。') from exc
        elif target_id is not None or reason != 'NEED_HELP':
            raise TaskError('除请求主管协助外，请选择本出诊的明确预约或邀约。')
    elif target_kind != '' or target_id is not None:
        raise TaskError('本操作不能夹带患者、预约或邀约编号。')


def validate_step(task, *, action, actor_id, role, slot, impact, now,
                  observation_digest, another_active=False):
    positive_id(actor_id)
    if role not in ('MANAGER','FRONT_DESK') or action not in ACTIONS:
        raise TaskError('请使用本店获授权的主管或前台身份。')
    if action not in (MANAGER_ACTIONS if role == 'MANAGER' else FRONT_ACTIONS):
        raise TaskError('当前身份不能执行这项任务操作。')
    aware(now)
    if action == 'open':
        if task is not None or another_active:
            raise TaskError('本出诊已有未结束任务，请先查看原任务，不能重复发起。')
        if not slot['is_active'] or parse_time(slot['starts_at']) <= now:
            raise TaskError('仅对尚未开始的有效出诊发起本类协调任务。')
        if not slot['booking_paused']:
            raise TaskError('请先在原出诊明确暂停新增，再发起任务；本页不会自动暂停。')
        if impact.too_many or impact.anomalies:
            raise TaskError('关联事实需要受控核对，暂不创建普通协调任务。')
        return 'OPEN'
    if task is None or task['state'] not in STATES:
        raise TaskError('任务不存在或状态异常。')
    state = task['state']
    if state not in ACTIVE_STATES:
        raise TaskError('任务已结束，不能改写历史；请查看当前记录。')
    if type(task['revision']) is not int or not 0 <= task['revision'] < 2**31-1:
        raise TaskError('任务修订号异常或已达上限，需受控维护。')
    if action == 'claim':
        if state != 'OPEN' or task['assignee_id'] is not None:
            raise TaskError('已有前台受理，或任务不是待受理状态。')
        return 'IN_PROGRESS'
    if action in ('progress','release','submit'):
        if state != 'IN_PROGRESS' or task['assignee_id'] != actor_id:
            raise TaskError('仅当前受理人可以记录声明、交接或提交复核。')
        if action == 'submit':
            gate = review_gate(slot, impact, now)
            if not gate.clear: raise TaskError(' '.join(gate.reasons))
            return 'READY'
        return 'OPEN' if action == 'release' else 'IN_PROGRESS'
    if action == 'return':
        if state not in ('IN_PROGRESS','READY'):
            raise TaskError('任务已经在待受理队列，无需重复退回。')
        return 'OPEN'
    if action == 'approve':
        if state != 'READY': raise TaskError('须先由受理前台提交复核。')
        if task['submitted_by_id'] is None or task['submitted_by_id'] != task['assignee_id']:
            raise TaskError('任务提交人与受理关系异常。')
        if actor_id == task['submitted_by_id']:
            raise TaskError('不能切换身份复核自己提交的任务；请另一位授权主管复核。')
        gate = review_gate(slot, impact, now)
        if not gate.clear: raise TaskError(' '.join(gate.reasons))
        if task['submitted_digest'] != observation_digest:
            raise TaskError('前台提交后关联事实或接收状态已变化；请退回重新核对。')
        return 'CLOSED'
    if action == 'cancel': return 'CANCELLED'
    raise TaskError('不支持此任务迁移。')


def validate_payload(value, *, proposal):
    keys = {'contract','kind','actor','role','context','context_revision','clinic',
            'slot','task','state'}
    if proposal: keys |= {'operation','action','reason','purpose','target_kind','target_id','due_at'}
    if type(value) is not dict or set(value) != keys:
        raise TaskError('确认字段不完整或含未允许字段。')
    if value['contract'] != CONTRACT or value['kind'] != ('proposal' if proposal else 'state'):
        raise TaskError('页面版本不匹配。')
    for key in ('actor','clinic','slot'):
        positive_id(value[key])
    if value['task'] is not None: positive_id(value['task'])
    if value['role'] not in ('MANAGER','FRONT_DESK'):
        raise TaskError('身份类型不正确。')
    if type(value['context_revision']) is not int or value['context_revision'] < 0:
        raise TaskError('上下文修订不正确。')
    for key in (('context','operation') if proposal else ('context',)):
        try:
            if type(value[key]) is not str or str(UUID(value[key])) != value[key]: raise ValueError()
        except (ValueError,AttributeError,TypeError) as exc: raise TaskError('确认编号不正确。') from exc
    if type(value['state']) is not str or not re.fullmatch('[0-9a-f]{64}',value['state']):
        raise TaskError('状态摘要不正确。')
    if proposal:
        if value['due_at'] is not None:parse_time(value['due_at'])
        validate_options(value['action'],value['reason'],purpose=value['purpose'],
            target_kind=value['target_kind'],target_id=value['target_id'])
        if (value['task'] is None) != (value['action'] == 'open'):
            raise TaskError('任务编号与操作类型不匹配。')
    return value
