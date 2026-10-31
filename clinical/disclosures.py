"""Per-step treatment explanations retained by the existing plan version.

Prepared content is not a patient's medical-consent decision or permission to
start care. Professional scope and transactions remain owned by clinical.plans.
"""
from copy import deepcopy
from datetime import datetime
from django.utils import timezone
from adc_core.rules import RuleError
from clinical.clinical_payload import draft_digest

FIELDS = (
    ('purpose', '治疗目的与适用范围', 1000),
    ('risks', '主要风险与不确定性', 2000),
    ('alternatives', '其他选择与暂缓影响', 2000),
    ('anesthesia', '麻醉安排', 1000),
    ('materials', '材料及相关安排', 1000),
    ('cost_notes', '费用范围与可能变化', 1000),
    ('aftercare', '术后注意与异常联系', 2000),
    ('questions', '待沟通问题与已记录答复', 2000),
)


def content(values):
    result = {}
    prepared = values.get('prepared', False)
    if type(prepared) is not bool:
        raise RuleError('请明确治疗说明是否准备完成。')
    for key, label, limit in FIELDS:
        value = values.get(key, '')
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise RuleError(label + '请控制在' + str(limit) + '字以内。')
        result[key] = value.strip()
        if prepared and key != 'questions' and not result[key]:
            raise RuleError('提供给患者核对前请补齐' + label + '；不涉及的安排也请明确说明。')
    result['prepared'] = prepared
    return result


def scope_digest(row, *, summary, source_record, definition):
    return draft_digest(dict(step=row, summary=summary, source_record=source_record, definition=definition))


def normalize(values, rows):
    if not isinstance(values, dict) or len(values) > 30:
        raise RuleError('治疗说明需按本方案的具体步骤保存。')
    keys = {r['step_key'] for r in rows}
    result = {}
    for key, raw in values.items():
        if key not in keys or not isinstance(raw, dict):
            raise RuleError('治疗说明对应步骤已变化，请重新核对。')
        row = content(raw)
        row.update({name: raw.get(name) for name in
                    ('scope_digest', 'prepared_by', 'prepared_by_name', 'prepared_at')})
        result[key] = row
    return result


def validate_prepared(payload, *, source_record, definitions):
    for row in payload['steps']:
        notice = payload['disclosures'].get(row['step_key'])
        if notice and notice['prepared']:
            expected = scope_digest(row, summary=payload['summary'], source_record=source_record,
                                    definition=definitions[row['step_key']])
            if notice['scope_digest'] != expected:
                raise RuleError('步骤、检查依据、方案摘要或目录已变化，请复核并重新保存相应治疗说明。')


def projection(notice, *, expected_digest=None):
    if not notice:
        return dict(available=False, state='MISSING', label='此版本尚未提供本步骤治疗说明', fields=[])
    if not notice.get('prepared'):
        return dict(available=False, state='DRAFT', label='本步骤治疗说明待医师完善', fields=[])
    if expected_digest is not None and notice.get('scope_digest') != expected_digest:
        return dict(available=False, state='STALE', label='步骤或依据已变化，治疗说明待复核', fields=[])
    return dict(available=True, state='PREPARED', label='治疗说明已准备，待沟通核对',
                prepared_at=notice['prepared_at'], prepared_by_name=notice['prepared_by_name'],
                prepared_time_label=timezone.localtime(datetime.fromisoformat(notice['prepared_at'])).strftime('%Y-%m-%d %H:%M'),
                fields=[dict(key=key, label=label, value=notice[key]) for key, label, _ in FIELDS
                        if notice.get(key)])


def retained(version):
    return deepcopy(version.disclosures)
