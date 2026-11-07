"""Human-readable labels shared by archive review and fixed PDF output."""
from datetime import datetime
from zoneinfo import ZoneInfo

LABELS={
 'header':'就诊身份与机构','visit':'本次接诊','document':'完整病历文书','clinical_source':'确认文书的临床来源',
 'actuals':'实际治疗与更正记录','plan_versions':'治疗方案版本','steps':'准确方案步骤','scheme_decisions':'方案选择历史',
 'medical_consents':'医疗告知事项','medical_notices':'医疗告知版本','medical_events':'告知、问答与医疗决定历史',
 'proxy_versions':'医疗代理依据版本','proxy_events':'代理材料核验与适用性历史','preflights':'治疗前核对依据',
 'rules':'适用的临床规则','gaps':'已发生治疗的事前材料缺口','gap_reviews':'独立医务复核（不构成事前通过）',
 'laboratory':'加工件记录','laboratory_reviews':'临床验收','laboratory_events':'加工流转历史','fee':'选定的已发布收费版本',
 'issues':'未完成事项','drafts':'未确认草稿（仅资料保全，不作为确认文书）',
 'examinations':'检查草稿','documents':'文书草稿','payload':'草稿原文',
 'id':'来源编号','patient_id':'患者编号来源','patient_no':'患者业务编号','patient_name':'患者姓名','clinic_id':'诊所来源编号',
 'clinic_name':'诊所名称','dentist_id':'医师来源编号','dentist_name':'负责医师','employee_no':'医师工号','visit_no':'就诊编号',
 'status':'接诊状态','attended_at':'实际到诊时间','completed_at':'接诊结束时间','content':'文书内容','source':'记录来源',
 'revision':'版本号','number':'版本序号','confirmed_by':'确认账号编号','confirmed_at':'确认时间','recorded_at':'录入时间',
 'observed_at':'实际发生时间','occurred_at':'实际表达时间','evidence_kind':'确认凭据类型','evidence_reference':'纸质原件引用',
 'kind':'类别','diagnosis':'诊断与判断依据','ancillary_results':'辅助检查及来源','instructions':'离诊医嘱','follow_up':'复诊与联系安排',
 'prior_context':'既往资料与本次变化','prior_visit_version':'既往准确文书来源','amendment_reason':'更正原因','late_reason':'迟记说明',
 'chief_complaint':'主诉','examination':'检查说明','history':'健康自述来源','history_review':'自述核对方式',
 'history_assessment':'病史核对结论','history_discrepancy':'差异与待明确事项','medical_status':'既往健康情况状态',
 'medical_history':'既往健康自述','medication_status':'用药情况状态','medications':'用药自述','allergy_status':'过敏情况状态',
 'reported_allergies':'过敏自述','dentition':'牙列','findings':'牙位观察','tooth':'牙位','surface':'牙面','detail':'观察说明',
 'plans':'本次方案来源','actual':'实际治疗摘要','care':'接诊处置','clinical_note':'接诊说明','outcome':'接诊结果',
 'medication_lines':'实际发退药费用','no_treatment_reason':'本次无治疗依据','lines':'收费或处置项目','line_no':'项目序号','name':'项目名称','name_snapshot':'当时项目名称',
 'unit_snapshot':'当时计量单位','unit_price':'单价','quantity':'实际数量','line_amount':'项目金额','total_amount':'合计',
 'amount':'合计金额','published_at':'发布时间','billing_header_snapshot':'当时开单身份','summary':'方案说明','discussion_note':'沟通说明',
 'disclosures':'具体医疗说明','description':'步骤说明','goal':'治疗目标','estimated_quantity':'预计数量',
 'estimated_unit_price':'预计单价','estimate_note':'费用估计说明','alternative_group':'替代选项分组','charge_basis':'计费依据',
 'requires_lab':'是否需要加工件','definition_snapshot':'当时项目定义','decision':'方案表态','reference':'原始依据引用','note':'说明',
 'action':'历史动作','sequence':'顺序','text':'原始说明与表达','reply_to_id':'所答复问题的来源编号','signer_kind':'实际决定人类型',
 'patient_snapshot':'当时身份与适用范围','identity_reference':'身份核对依据','scope_clinic_id':'诊所范围编号',
 'authority_reference':'医疗代理材料编号','delegate_name':'实际医疗代理人','applicability':'本次医疗代理适用原因',
 'valid_from':'依据生效时间','valid_until':'依据失效时间','resulting_state':'当次办理结果','state':'记录状态','progress':'执行进展',
 'charge_mode':'本次是否另计费','charge_snapshot':'当时实际项目','reason':'办理原因与依据','snapshot':'当时核对事实',
 'communication':'本次沟通与身份核对','checked_by_id':'开治核对账号','checked_at':'开治核对时间','mode':'临床规则要求',
 'explanation':'适用说明','missing':'实际保留的缺失事前依据','recorded_by_id':'记录账号','signer':'实际表达者',
 'case_no':'加工业务编号','work_kind':'加工类别','specification':'加工要求','vendor_name':'登记合作方','logistics_note':'流转说明',
 'needed_on':'约定需要日期','cycle':'流转周期','followup_due_at':'跟进期限','requested_at':'请求时间','review_note':'独立审核意见',
 'record':'检查来源','message':'待办说明','owner':'责任岗位','route':'继续办理入口'}
VALUES={'INITIAL':'初诊病历','FOLLOWUP':'复诊病历','ACCOUNT_CONFIRMATION':'医师账号确认（非可靠电子签名）',
 'PAPER_REFERENCE':'纸质原件登记（原件另行保管）','SELF_ACCOUNT':'本人账号确认','PROXY_ACCOUNT':'医疗代理账号确认',
 'DOCTOR_ACCOUNT':'医师账号记录','SELF':'患者本人','PROXY':'经核验医疗代理','INTERVIEW':'医师记录面谈自述',
 'UNKNOWN':'尚未明确','NO_KNOWN':'自述目前无已知情况','REPORTED':'自述有相关情况','REVIEWED':'已完成对应核对或历史复核',
 'UNAVAILABLE':'未取得指定自述，未知保留','UNASSESSED':'尚未核对牙列','PERMANENT':'恒牙列','PRIMARY':'乳牙列','MIXED':'混合牙列',
 'ACTIVE':'有效','VOIDED':'已更正撤回，历史保留','COMPLETE':'本步骤实际完成','PARTIAL':'尚待分次继续',
 'CHARGE':'本次按实际项目开单','NO_CHARGE':'本次不另计费','TREATED':'本次有实际治疗','NO_TREATMENT':'本次无治疗','PHARMACY_ONLY':'本次仅发药',
 'COMPLETED':'接诊已完成','CLOSED_NO_TREATMENT':'本次无治疗，接诊已结束','PUBLISHED':'已确认或发布',
 'QUESTION':'医疗提问','ANSWER':'医师答复','AGREED':'明确同意','DECLINED':'明确拒绝','DEFERRED':'暂缓',
 'WITHDRAWN':'已撤回，旧记录保留','ACCEPTED':'认可或已验收','CONSENT':'须取得具体医疗同意','COMMUNICATION':'完成沟通记录',
 'REVIEW':'需进一步专业判断','PENDING':'待办理','PER_EXECUTION':'按实际已提供项目计费','ON_COMPLETION':'步骤实际完成时计费',
 'GUARDIAN':'未成年监护','WRITTEN':'成年患者书面委托','OBSERVATION':'检查发现','MISSING':'牙缺失','EXISTING_WORK':'既往处置'}
SECTIONS=['document','clinical_source','plan_versions','steps','scheme_decisions','medical_notices','medical_events',
 'proxy_versions','proxy_events','actuals','preflights','rules','gaps','gap_reviews','laboratory','laboratory_reviews','laboratory_events','fee','issues','drafts']
TECHNICAL={'operation_id','scope_digest','source_cursor','content_digest','history_cursor','digest','contract'}


def label(key):
    if key in LABELS:return LABELS[key]
    if key.endswith('_id'):return LABELS.get(key[:-3],key[:-3].replace('_',' '))+'来源编号'
    return key.replace('_',' ')


def scalar(value):
    if value is None:return '未记录或不适用（按本项上下文核对）'
    if isinstance(value,bool):return '是' if value else '否'
    if isinstance(value,str):
        if len(value)>18 and value[4:5]=='-' and 'T' in value[:12]:
            try:return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S（北京时间）')
            except ValueError:pass
        return VALUES.get(value,value) or '未补充说明'
    return str(value)


def flatten(value,prefix=''):
    if isinstance(value,dict):
        for key,item in value.items():
            if key in TECHNICAL:continue
            title=(prefix+' · ' if prefix else '')+label(key)
            yield from flatten(item,title)
    elif isinstance(value,list):
        if not value:yield prefix,'无本类记录，不据此推定临床情况'
        for i,item in enumerate(value,1):yield from flatten(item,(prefix+' · ' if prefix else '')+'条目'+str(i))
    else:yield prefix,scalar(value)


def sections(snapshot):
    result=[];empty=[]
    for key in SECTIONS:
        value=snapshot.get(key)
        if not value:
            empty.append((label(key),'无本类记录；不推定临床情况'))
            continue
        if key=='document':value={k:v for k,v in value.items() if k!='source'}
        result.append(dict(title=label(key),rows=list(flatten(value))))
    if empty:result.append(dict(title='其他资料范围',rows=empty))
    return result


def changes(candidate):
    before=candidate.get('before',{});after=candidate.get('payload',{});result=[]
    for key in dict.fromkeys([*before,*after]):
        if before.get(key)!=after.get(key):
            def display(value):return '\n'.join(k+'：'+v for k,v in flatten(value)) if isinstance(value,(dict,list)) else scalar(value)
            result.append(dict(label=label(key),before=display(before.get(key)),after=display(after.get(key))))
    return result
