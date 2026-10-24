"""Bounded structured drafts; both interaction paths use the same rules."""
from datetime import datetime
import hashlib,json
from django.utils import timezone
from adc_core.rules import RuleError
from clinical.tooth_rules import DENTITIONS,validate_finding

HISTORY_KEYS=('medical_status','medical_history','medication_status','medications','allergy_status','reported_allergies')
TEXT_KEYS={'chief_complaint':2000,'examination':4000,'history_assessment':2000,'history_discrepancy':2000,'amendment_reason':500}


def history_fields(data):
    result={}
    for status,text in [('medical_status','medical_history'),('medication_status','medications'),('allergy_status','reported_allergies')]:
        if data.get(status) not in ('UNKNOWN','REPORTED','NO_KNOWN'):
            raise RuleError('请分别明确自述情况；不清楚时保留“尚未明确”。')
        value=data.get(text,'')
        if not isinstance(value,str) or len(value.strip())>2000:raise RuleError('每项自述说明最多2000字。')
        if data[status]=='REPORTED' and not value.strip():raise RuleError('自述有相关情况时，请补充说明。')
        result[status]=data[status];result[text]=value.strip()
    return result


def normalize_draft(data,*,complete=False):
    result={}
    for key,limit in TEXT_KEYS.items():
        value=data.get(key,'')
        if not isinstance(value,str) or len(value.strip())>limit:raise RuleError(f'检查说明超过允许长度（{limit}字），请精简后保存。')
        result[key]=value.strip()
    result['dentition']=data.get('dentition','UNASSESSED')
    if result['dentition'] not in DENTITIONS:raise RuleError('请选择当前核对的牙列。')
    history=data.get('history_id')
    try:result['history_id']=int(history) if history not in ('',None) else None
    except (TypeError,ValueError):raise RuleError('患者自述来源无效，请重新选择。')
    result['history_review']=data.get('history_review','UNAVAILABLE')
    if result['history_review'] not in ('REVIEWED','UNAVAILABLE'):raise RuleError('请明确记录本次自述核对情况。')
    findings=data.get('findings',[])
    if not isinstance(findings,list) or len(findings)>104:raise RuleError('一次检查版本最多保存104项观察。')
    result['findings']=[validate_finding(x,result['dentition']) for x in findings]
    locations=[(f['tooth'],f['surface'],f['kind']) for f in result['findings']]
    if len(set(locations))!=len(locations):raise RuleError('同牙位、牙面和类别已存在，请修改原条目。')
    observed=data.get('observed_at')
    try:
        moment=observed if isinstance(observed,datetime) else datetime.fromisoformat(observed) if observed else None
        if moment and not timezone.is_aware(moment):raise ValueError
    except (TypeError,ValueError):raise RuleError('请填写完整的检查发生时间。')
    result['observed_at']=moment.isoformat() if moment else None
    if complete:
        if any(not result[k] for k in ('chief_complaint','examination','history_assessment')):
            raise RuleError('确认前请补齐主诉、检查说明和病史核对结论；未知仍应明确说明。')
        if bool(result['history_id'])!=(result['history_review']=='REVIEWED'):
            raise RuleError('自述来源和核对状态不一致；尚无自述时请保留未知并说明。')
        if moment is None or moment>timezone.now():raise RuleError('检查发生时间不能为空或晚于当前时间。')
    return result


def draft_digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()
