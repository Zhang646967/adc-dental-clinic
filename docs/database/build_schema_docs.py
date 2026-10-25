"""Build current ER views and searchable dictionaries from schema metadata.

No database connection or business data is needed. The snapshot was collected
with a read-only transaction from the identified application version.
"""
from pathlib import Path
import hashlib, html, json, re

ROOT = Path(__file__).resolve().parent

# Selected columns keep the printed views legible; schema_snapshot.json and
# FIELD_CATALOG.md retain every ORM column and every actual SQL constraint.
VIEWS = {
    'er_insurance_settlement': {
        'title':'原实际费用、唯一结算与独立分担',
        'tables': {
            'adc_invoice':['id','current_record_version_id'],
            'adc_visit_record_version':['id','revision_no'],
            'adc_treatment_record':['id','record_version_id','line_no'],
            'adc_insurance_settlement':['id','request_id','invoice_id','record_version_id','state'],
            'adc_insurance_settlement_line':['id','request_id','treatment_record_id','patient_cash','personal_account','fund_amount'],
            'adc_insurance_simulation':['id','request_id','reference','result'],
            'adc_insurance_settlement_review':['id','request_id','decision'],
        },
        'note':'每笔请求保留原账单的确切发布版本和全部实际收费行；同一账单至多一个未终结请求。原始模拟结果和独立分担复核分别一对一引用请求，回复未知时查询原编号，不重新申报。逐行现金责任、个人账户与基金之和等于原行金额；独立通过才影响患者待缴，不产生现金或新增收入。目录、待遇、操作人及事件外键见完整目录。',
    },
    'er_fund_allocation': {
        'title':'银行流水独占使用与基金逐笔分配',
        'tables': {
            'adc_statement_line':['id','account_id','amount','direction'],
            'adc_reconciliation_match':['id','line_id','state'],
            'adc_fund_transfer':['id','line_id','kind','state'],
            'adc_statement_use':['id','line_id','cash_match_id','fund_transfer_id','state'],
            'adc_fund_allocation':['id','transfer_id','total','state'],
            'adc_fund_allocation_line':['id','allocation_id','claim_id','amount'],
            'adc_insurance_settlement':['id','request_id','fund_amount'],
        },
        'note':'流水用途恰好引用现金匹配或基金凭据之一，两个来源各唯一且可空；每条流水至多一个活动用途。旧活动匹配仅派生用途记录，不重写原决定。已核对基金凭据可分批关联多笔同店同币种申报；分配行在批次内按申报唯一。待审及已通过分配共同限制可用银行金额；待审退回不能使用尚未确认的入账。到账、退回、现金账及原收入分开，完整账户和人员关系见目录。',
    },
    'er_fund_followup': {
        'title':'基金差额责任与追加跟进记录',
        'tables': {
            'adc_insurance_settlement':['id','request_id'],
            'adc_user':['id','username'],
            'adc_fund_issue':['id','claim_id','opened_by_id','kind','amount'],
            'adc_fund_issue_event':['id','issue_id','sequence','owner_id','actor_id','state','due_at'],
        },
        'note':'未到账、少到账、扣减或用途未知均关联原申报；金额可空表示尚未核实。事项的责任人、期限、依据和状态由追加事件表达，每项按顺序唯一。负责人失效后可由现任财务明确重分配，原责任和沟通保留。结束跟进不核销基金，不生成平衡分录，也不转为患者欠款。',
    },
    'er_insurance_reversal': {
        'title':'原结算撤销、原结果查询与独立退回核对',
        'tables': {
            'adc_insurance_settlement':['id','request_id','state'],
            'adc_insurance_cancellation':['id','request_id','cancellation_id','state','revision'],
            'adc_insurance_reversal':['id','cancellation_id','reference','result'],
            'adc_insurance_cancellation_review':['id','cancellation_id','sequence','decision'],
            'adc_insurance_settlement_event':['id','request_id','sequence','action'],
        },
        'note':'每笔原结算至多一个保留的撤销请求，撤销结果一对一引用；未知和处理中继续查询同一编号。复核可追加未通过决定，但至多一次通过；实际通过须已核对原撤销结果、基金净到账归零且没有待审分配或患者现金。撤销中的原已通过分担保持，原未通过分担不会产生抵扣。事件记录当时撤销状态；撤销不作废实际费用，不自动收退款。',
    },
    'er_insurance_policy': {
        'title':'医保目录版本、门店安排与收费适配',
        'tables': {
            'adc_clinic':['id','clinic_code'],
            'adc_treatment_type':['id','code','unit_definition'],
            'adc_insurance_catalogue':['id','region','version_code','previous_id','review_attempt','effective_on','source_digest','state'],
            'adc_insurance_policy_item':['id','catalogue_id','code','unit','payment_class','pre_self_pay_percent'],
            'adc_insurance_arrangement':['id','clinic_id','catalogue_id','starts_on','ends_on','state'],
            'adc_insurance_fee_mapping':['id','clinic_id','treatment_type_id','policy_item_id','policy_units_per_fee','state'],
        },
        'note':'目录保留原文件及规范记录，编码在目录内唯一；空白单位及规则保持未知。政策版本与审阅次数分开，同一来源至多一个待核对或已启用记录；未通过或停用后可明确提交下一次审阅，前次引用可空且唯一，原决定不改写。门店已确认安排按本店日期排斥重叠；收费映射按本店与收费项目限制一个启用结果。不同账号独立复核，重新核对不恢复旧安排或映射。图中省略操作人及其余事件分支，全部关系见完整目录；本图不表示真实定点资格或资金结算。',
    },
    'er_insurance_eligibility': {
        'title':'本店模拟待遇版本与办理历史',
        'tables': {
            'adc_clinic':['id','clinic_code'],
            'adc_patient':['id','patient_no'],
            'adc_user':['id','username'],
            'adc_insurance_eligibility':['id','clinic_id','patient_id','recorded_by_id','previous_id','version','insured_region','source'],
            'adc_insurance_event':['id','eligibility_id','actor_id','operation_id','action'],
        },
        'note':'待遇事实按患者、诊所和版号唯一；前版引用可空且一对一，后续版本必须继续同一患者与诊所。记录及事件只追加，最新一版未核实或失效时不回退使用旧版。source固定LOCAL_SIMULATION，参保地不由定位或手机号推断；待遇资料不扩大本人或代约权限。办理事件在目录、安排、映射、待遇四个可空来源中恰选一个，本视图仅展开待遇分支，其余关系见完整外键目录。',
    },
    'er_patient_account': {
        'title':'患者渠道账号、凭证与联络来源',
        'tables': {
            'adc_user':['id','username'],
            'adc_external_identity':['id','provider','app_id','subject','user_id','revision'],
            'adc_local_identity_code':['id','purpose','identity_id','user_id','digest','expires_at','consumed_at'],
            'adc_account_phone':['id','user_id','source','revision'],
            'adc_account_identity_event':['id','user_id','identity_id','operation_id','action'],
            'adc_workspace_context':['id','user_id','login_channel','role','revision'],
        },
        'note':'外部身份按provider、app_id及subject联合唯一，当前账号引用可空；解绑不删除ADC账号及事件。一次性凭证按用途引用外部身份或账号，数据库只存摘要。账号联络按user一对一，不与Patient建立手机号匹配外键。首次绑定事件建立患者渠道账号，未获本人或代约授权时上下文岗位仍为空，不能成为员工或临床权限。本地凭证及手机号来源为LOCAL替身，不能写成微信实名或居民身份证。',
    },
    'er_patient_enrollment': {
        'title':'本人建档申请、前台决定与唯一档案关联',
        'tables': {
            'adc_user':['id','username'],
            'adc_clinic':['id','clinic_code'],
            'adc_patient':['id','patient_no'],
            'adc_patient_access':['id','user_id','patient_id','is_active'],
            'adc_patient_enrollment':['id','user_id','clinic_id','patient_id','kind','state','revision'],
            'adc_patient_enrollment_event':['id','enrollment_id','actor_id','operation_id','action'],
        },
        'note':'申请归属登录账号及办理诊所；同一账号至多一项待核验或待补充申请。患者引用在批准时才有值，待核验不创建正式档案或预约。前台以本店核验职责、当前申请版号及明确原档案核对，新档建档及关联同事务提交；旧档不改资料，暂停复核启用原PatientAccess，决定事件一并追加。本人关联继续保持账号、患者分别一对一；手机号不合并患者。决定与原申请快照追加保留，撤回或解绑不删除原事实。',
    },
    'er_clinic_directory': {
        'title':'门店公开资料与发布历史',
        'tables': {
            'adc_clinic':['id','clinic_code','name'],
            'adc_user':['id','username'],
            'adc_clinic_directory':['id','clinic_id','display_name','city','is_published','revision'],
            'adc_clinic_directory_revision':['id','directory_id','actor_id','revision','operation_id'],
        },
        'note':'每家诊所至多一份当前公开资料；业务名称和既有单据身份不随公开别名改写。发布版本按资料及版号唯一，操作编号唯一，历史只追加。营业时间由科室开放和明确停用区间推导，不在资料中重复维护；WGS84排序与GCJ02导航坐标分开，坐标缺失保持未知。外键不授予岗位权限。',
    },
    'er_clinical_history': {
        'title':'患者自述来源与医师核对',
        'tables': {
            'adc_patient':['id','patient_no'],
            'adc_clinic':['id','clinic_code'],
            'adc_user':['id','username'],
            'adc_visit':['id','patient_id'],
            'adc_clinical_history_version':['id','patient_id','scope_clinic_id','source_visit_id','reported_by_id','previous_id','revision','source'],
            'adc_clinical_record_version':['id','history_id','history_review','history_cursor'],
        },
        'note':'本人提交不归属某次预约或诊所；医师面谈引用实际就诊及当前诊所。患者与来源诊所及版号组成唯一键，空诊所也参与唯一性；各来源分别追加版本。检查记录可引用一个已核对的具体版本，并保留核对结论、差异和可见来源游标。自述不覆盖已复核过敏资料；外键不授予跨店查阅权限。',
    },
    'er_clinical_encounter': {
        'title':'实际检查、草稿与确认版本',
        'tables': {
            'adc_visit':['id','patient_id','clinic_id'],
            'adc_user':['id','username'],
            'adc_clinical_encounter':['id','visit_id','opened_by_id','revision'],
            'adc_clinical_draft':['id','encounter_id','base_record_id'],
            'adc_clinical_record_version':['id','encounter_id','previous_id','recorded_by_id','revision'],
            'adc_tooth_finding':['id','record_id','line_no','tooth','surface','kind'],
            'adc_clinical_record_event':['id','encounter_id','record_id','operation_id','action'],
        },
        'note':'每次实际到诊至多一个检查头，患者与诊所经原就诊推导，不重复维护。每个检查头至多一个可修改草稿，base_record可空；确认版本按检查头和版号唯一，前版引用可空且唯一。牙位观察属于具体确认版本，草稿观察尚在有界工作载荷中。确认版本、观察及决定事件只追加，草稿可明确放弃。检查记录本身不是治疗执行或资金事实。',
    },
    'er_professional_authority': {
        'title':'专业资质来源与限定操作授权',
        'tables': {
            'adc_clinic':['id','clinic_code'],
            'adc_user':['id','username'],
            'adc_booking_service':['id'],
            'adc_clinical_reviewer':['id','user_id','clinic_id','valid_until','is_active'],
            'adc_professional_authorization':['id','user_id','clinic_id','service_id','state','valid_until'],
            'adc_clinical_authority_event':['id','authorization_id','reviewer_id','operation_id'],
            'adc_clinical_authority_policy':['id','clinic_id','activated_by_id'],
        },
        'note':'审核职责按账号与诊所唯一；机构委任不等于病历访问。专业申请分别引用账号、诊所和可空服务；空服务仅指无服务旧记录，不是全服务通配。决定历史及诊所启用事实不可改写。图中仅展开关键外键，来源证据、有效期及查阅／记录／转诊动作见完整目录与命令核验。',
    },
    'er_clinical_referral': {
        'title':'限定跨店转诊与敏感查阅留痕',
        'tables': {
            'adc_patient':['id','patient_no'],
            'adc_clinic':['id','clinic_code'],
            'adc_visit':['id','patient_id'],
            'adc_visit_record_version':['id','visit_id','revision_no'],
            'adc_clinical_record_version':['id','revision'],
            'adc_clinical_referral':['id','patient_id','source_visit_id','source_record_id','source_clinical_record_id','source_clinic_id','destination_clinic_id','receiver_id','state'],
            'adc_clinical_referral_event':['id','referral_id','actor_id','operation_id'],
        },
        'note':'转诊保留原患者、原就诊、转出／接收诊所及指定医师。来源可不选，选择时至多引用一个旧发布版本或结构化检查确认版本；必须属于同次原就诊。后续更正不改写已选择的版本。身份核对、临床披露同意和医师接收分别办理。查阅事件的object_kind/object_id为受控类型与对象编号，不是虚构外键。其余来源及有效期在完整目录保留。',
    },
    'er_patient_relationship': {
        'title': '患者关系核验与预约代办授权',
        'tables': {
            'adc_patient': ['id', 'patient_no'],
            'adc_clinic': ['id', 'clinic_code'],
            'adc_user': ['id', 'username'],
            'adc_patient_relationship': ['id','clinic_id','patient_id','delegate_user_id','kind','state','revision'],
            'adc_patient_appointment_grant': ['id','relationship_id','valid_from','valid_until','is_active','revision'],
            'adc_patient_relationship_event': ['id','relationship_id','actor_id','operation_id','action'],
            'adc_workspace_context': ['id','user_id','patient_grant_id','revision'],
        },
        'note': '关系属于患者及核验诊所，账号可在待核验阶段补充。每项关系至多一项预约授权；联系人和普通亲属关系不生成授权。决定事件仅追加，operation_id唯一。上下文可选一个授权，本人入口保持空；有效期、当前账号与本店范围由事务核验，不从外键连线推断病历、资金或临床同意权限。',
    },
    'er_portal_reschedule': {
        'title': '患者授权与预约改期来源',
        'tables': {
            'adc_user': ['id', 'username'],
            'adc_patient_access': ['id', 'user_id', 'patient_id', 'is_active'],
            'adc_patient': ['id', 'patient_no'],
            'adc_portal_booking_receipt': ['id', 'nonce', 'access_id', 'appointment_grant_id', 'visit_id'],
            'adc_patient_appointment_grant': ['id','relationship_id','revision'],
            'adc_visit': ['id', 'patient_id', 'replaces_visit_id', 'status'],
            'adc_wait_offer': ['id', 'visit_id', 'state'],
            'adc_cancellation_followup': ['id', 'visit_id', 'replacement_visit_id', 'state'],
        },
        'note': '本人绑定保留；预约确认回执必须且只能引用本人绑定或预约代办授权之一，nonce唯一，visit_id唯一。预约自引用可空且唯一，构成原约与后继。邀约和取消跟进保留各自原关联，不因后续改期改写；当前患者、本店代约范围和活动状态由事务命令核验，不能从外键推定权限。',
    },
    'er_schedule_coordination': {
        'title': '前台排班与调班责任',
        'tables': {
            'adc_clinic': ['id', 'clinic_code'],
            'adc_dentist': ['id', 'employee_no'],
            'adc_availability_slot': ['id', 'clinic_id', 'dentist_id', 'starts_at', 'ends_at', 'booking_paused'],
            'adc_visit': ['id', 'availability_slot_id', 'status'],
            'adc_wait_offer': ['id', 'slot_id', 'state', 'expires_at'],
            'adc_coordination_task': ['id', 'slot_id', 'assignee_id', 'due_at', 'state'],
            'adc_user': ['id', 'username'],
        },
        'note': '出诊是医师供给，预约与有效邀约是承诺；协调任务经slot_id归店，assignee_id可空，due_at历史可空。每个出诊至多一个活动任务；独立复核与具体预约变更另行办理。',
    },
    'er_booking': {
        'title': '预约与电话接待',
        'tables': {
            'adc_clinic': ['id', 'clinic_code'],
            'adc_dentist': ['id', 'employee_no'],
            'adc_patient': ['id', 'patient_no'],
            'adc_availability_slot': ['id', 'clinic_id', 'dentist_id', 'starts_at', 'ends_at'],
            'adc_visit': ['id', 'patient_id', 'availability_slot_id', 'status'],
            'adc_reception_case': ['id', 'clinic_id', 'patient_id', 'visit_id', 'state'],
            'adc_reception_communication': ['id', 'case_id', 'sequence'],
        },
        'note': '接待可以尚未建档；visit_id唯一且可空，沟通按case_id与sequence保留历史。诊所与医师等未展开外键见字段目录。',
    },
    'er_catalogue': {
        'title': '排班服务与医师适配',
        'tables': {
            'adc_clinic': ['id', 'clinic_code'],
            'adc_department': ['id', 'clinic_id', 'code'],
            'adc_department_hours': ['id', 'department_id', 'weekday', 'opens_at', 'closes_at'],
            'adc_treatment_room': ['id', 'department_id', 'code'],
            'adc_booking_service': ['id', 'department_id', 'duration_minutes'],
            'adc_service_presentation': ['id', 'service_id', 'category', 'fee_mode', 'fee_amount', 'is_published'],
            'adc_service_requirement': ['id', 'service_id', 'category', 'quantity'],
            'adc_booking_service_dentists': ['id', 'bookingservice_id', 'dentist_id'],
            'adc_dentist': ['id', 'employee_no'],
        },
        'note': '服务与医师的多对多关系通过真实连接表实现；科室开放与医师出诊分别保存。每项预约服务至多一份患者说明，未建立、草稿或不完整说明均不公开；费用说明不生成账单。',
    },
    'er_resource_claims': {
        'title': '设备位置与资源占用',
        'tables': {
            'adc_visit': ['id'],
            'adc_wait_offer': ['id', 'visit_id'],
            'adc_booking_service': ['id'],
            'adc_treatment_room': ['id'],
            'adc_resource_plan': ['id', 'visit_id', 'offer_id', 'service_id', 'room_id', 'version', 'is_current'],
            'adc_resource_claim': ['id', 'plan_id', 'asset_id', 'starts_at', 'ends_at', 'active'],
            'adc_equipment_asset': ['id', 'asset_code', 'state'],
            'adc_resource_binding': ['id', 'asset_id', 'room_id', 'shared'],
        },
        'note': '方案必须引用预约或邀约，接受邀约后允许两者同时存在；每个来源至多一个当前方案。牙椅使用设备资产，每项有效占用受时间排斥约束保护。',
    },
    'er_finance': {
        'title': '诊疗结算与资金凭据',
        'tables': {
            'adc_visit': ['id'],
            'adc_visit_record_version': ['id', 'visit_id', 'revision_no'],
            'adc_treatment_record': ['id', 'record_version_id', 'line_no'],
            'adc_invoice': ['id', 'visit_id', 'current_record_version_id'],
            'adc_cash_entry': ['id', 'invoice_id', 'amount', 'state'],
            'adc_cash_evidence': ['id', 'cash_entry_id', 'account_id', 'version'],
            'adc_payment_account': ['id'],
            'adc_statement_line': ['id', 'account_id', 'transaction_id'],
            'adc_reconciliation_match': ['id', 'cash_entry_id', 'evidence_id', 'line_id', 'state'],
        },
        'note': '每次就诊至多一个逻辑账单；账单另有复合外键保证当前记录版本属于同一次就诊。凭据与匹配保留多次历史，活动匹配的唯一性由条件约束限定。',
    },
}


VIEWS.update({'er_treatment_plan': {'title': '跨次就诊方案与保留版本',
                       'tables': {'adc_clinical_encounter': ['id', 'visit_id'],
                                  'adc_clinical_record_version': ['id', 'encounter_id', 'revision'],
                                  'adc_treatment_plan': ['id', 'origin_encounter_id', 'revision'],
                                  'adc_plan_draft': ['id',
                                                     'plan_id',
                                                     'source_record_id',
                                                     'base_version_id'],
                                  'adc_plan_version': ['id',
                                                       'plan_id',
                                                       'previous_id',
                                                       'source_record_id',
                                                       'revision'],
                                  'adc_treatment_step': ['id', 'plan_id', 'step_key'],
                                  'adc_plan_step_version': ['id',
                                                            'version_id',
                                                            'step_id',
                                                            'requires_lab',
                                                            'definition_snapshot']},
                       'note': '患者与诊所经原检查头及就诊推导；不重复维护患者归属。工作草稿可修改，确认方案和步骤版本保留历史。稳定步骤只表达沿革，不能把旧版本人决定或加工验收当作新版授权。目录定义与时长保留发布时快照，旧记录空值表示未登记，不补造历史。'},
 'er_plan_decisions': {'title': '具体方案步骤与本人决定',
                       'tables': {'adc_plan_version': ['id', 'revision'],
                                  'adc_plan_step_version': ['id', 'version_id', 'alternative_group'],
                                  'adc_patient_access': ['id', 'patient_id', 'user_id'],
                                  'adc_visit': ['id', 'patient_id'],
                                  'adc_plan_decision': ['id',
                                                        'step_version_id',
                                                        'self_access_id',
                                                        'source_visit_id',
                                                        'decision',
                                                        'source']},
                       'note': '每次决定绑定具体步骤版本。本人网站决定引用本人PatientAccess，医师手工登记的讨论决定引用本次就诊，来源二选一；这不是手术知情同意签署。代约授权不授予方案或病历访问。互斥组不能同时形成两个已接受的当前选择；所有决定只追加。'},
 'er_performed_billing': {'title': '实际执行、原始开单与账单版本',
                          'tables': {'adc_clinical_encounter': ['id', 'visit_id'],
                                     'adc_clinical_record_version': ['id', 'encounter_id'],
                                     'adc_plan_step_version': ['id'],
                                     'adc_performed_procedure': ['id',
                                                                 'encounter_id',
                                                                 'source_record_id',
                                                                 'step_version_id',
                                                                 'charge_line_id',
                                                                 'charge_mode',
                                                                 'state'],
                                     'adc_treatment_record': ['id', 'record_version_id', 'line_no'],
                                     'adc_visit_record_version': ['id', 'visit_id', 'revision_no'],
                                     'adc_invoice': ['id', 'visit_id', 'current_record_version_id']},
                          'note': '实际执行可引用计划内步骤，也可明确登记计划外依据。原始收费行至多归属一个实际执行；审核后的账单版本副本不生成第二次执行。原开单快照保留在实际执行JSON中，不伪画为外键。完成时计费方案的中间阶段可不另收费，但仍属已治疗；未发布作废保留原执行与快照，已发布执行不能作废。'},
 'er_next_visit': {'title': '医师后续要求与原预约关联',
                   'tables': {'adc_clinical_record_version': ['id'],
                              'adc_plan_step_version': ['id'],
                              'adc_booking_service': ['id'],
                              'adc_next_visit_instruction': ['id',
                                                             'source_record_id',
                                                             'step_version_id',
                                                             'service_id',
                                                             'completion_rule',
                                                             'earliest_on',
                                                             'latest_on'],
                              'adc_visit': ['id', 'replaces_visit_id', 'status'],
                              'adc_plan_appointment': ['id', 'instruction_id', 'visit_id']},
                   'note': '后续要求保留原检查、具体步骤、服务、建议窗口和完成标准；前台只读取安排所需投影。先经统一资源规则成约，再明确关联原预约；改期沿唯一后继关系跟踪，取消不代表复诊完成。一次部分治疗关闭后，如未达到明确完成标准，可以继续安排。历史未登记完成标准的记录保留未明确状态。'},
 'er_clinical_recall': {'title': '复诊责任、沟通与实际完成依据',
                        'tables': {'adc_next_visit_instruction': ['id', 'state', 'completion_rule'],
                                   'adc_clinical_record_version': ['id'],
                                   'adc_performed_procedure': ['id'],
                                   'adc_user': ['id'],
                                   'adc_clinical_recall': ['id',
                                                           'instruction_id',
                                                           'owner_id',
                                                           'state',
                                                           'completion_record_id',
                                                           'completion_performed_id'],
                                   'adc_clinical_recall_event': ['id',
                                                                 'episode_id',
                                                                 'actor_id',
                                                                 'operation_id']},
                        'note': '一条后续要求至多一份随访责任，状态、负责人和期限变化追加事件。完成时仅选择同患者、同店、同服务且明确关联的已关闭后续就诊事实；确认检查或指定步骤完成依据二选一。晚于建议窗口如实记录，不改原日期。患者暂不继续转医师核对，未经明确恢复不重复对外联系，也不自动取消预约。'},
 'er_laboratory': {'title': '加工请求、物理送返与具体版本验收',
                   'tables': {'adc_clinical_record_version': ['id'],
                              'adc_plan_step_version': ['id', 'step_id', 'requires_lab'],
                              'adc_treatment_step': ['id'],
                              'adc_lab_case': ['id',
                                               'source_record_id',
                                               'step_version_id',
                                               'state',
                                               'cycle',
                                               'coordinator_id'],
                              'adc_lab_review': ['id',
                                                 'case_id',
                                                 'target_step_version_id',
                                                 'source_record_id',
                                                 'cycle',
                                                 'decision'],
                              'adc_lab_event': ['id', 'case_id', 'review_id', 'operation_id']},
                   'note': '医师请求绑定原确认检查及已接受具体方案步骤。送出、返回是手工交接事实，不代表临床适配；每次返工须经过新送返周期。验收绑定本周期及当前确切步骤版本，跨版本复用必须重新明确核对。前台不读取加工临床规格或验收详情；原需要日期与预约保留。只在所需加工件全部有效验收后允许相应实际执行，不自动产生收费。'}})

# Keep the execution/billing projection readable at the report's printed width.
# Origin/step relations are expanded in the adjacent plan views and full catalog.
for _table in ('adc_clinical_encounter','adc_plan_step_version'):
    VIEWS['er_performed_billing']['tables'].pop(_table)

def sql_foreign_key(item):
    m = re.match(r'FOREIGN KEY \(([^)]+)\) REFERENCES ([^ (]+)\(([^)]+)\)', item['definition'])
    assert m, item
    return item['table'], [s.strip() for s in m[1].split(',')], m[2], [s.strip() for s in m[3].split(',')]


def build():
    data = json.loads((ROOT/'schema_snapshot.json').read_text())
    models = {m['table']: m for m in data['models']}
    assert set(data['tables']) == set(models) | {'django_migrations'}
    normalize_type=lambda s: re.sub(r'\s+','',s.replace('character varying','varchar').replace('time without time zone','time'))
    actual_columns={(c['table'],c['column']):c for c in data['columns']}
    checked_columns=0
    type_differences=[]
    for table,model in models.items():
        assert {f['column'] for f in model['fields']}=={c['column'] for c in data['columns'] if c['table']==table}
        for f in model['fields']:
            column=actual_columns[table,f['column']]
            assert f['null']==column['null'], (table,f['column'],'nullability')
            if normalize_type(f['db_type'])!=normalize_type(column['db_type']):
                type_differences.append(dict(table=table,column=f['column'],model_type=f['db_type'],database_type=column['db_type']))
            if f['unique']:
                key='PRIMARY KEY' if f['pk'] else 'UNIQUE'
                assert any(c['table']==table and c['definition']==key+' ('+f['column']+')' for c in data['constraints']), (table,f['column'],'single-column key')
            checked_columns+=1
    sql_fks = [sql_foreign_key(c) for c in data['constraints'] if c['kind']=='f']
    expected = {(t, (f['column'],), f['target_table'], (f['target_column'],))
                for t,m in models.items() for f in m['fields'] if f['target_table']}
    actual = {(t, tuple(cols), parent, tuple(targets)) for t,cols,parent,targets in sql_fks}
    assert expected <= actual, 'ORM relation missing from actual SQL constraints'
    assert actual-expected == {('adc_invoice', ('current_record_version_id', 'visit_id'),
                               'adc_visit_record_version', ('id', 'visit_id'))}, 'Review additional SQL-only relations before publishing'
    # Preserve actual SQL semantics, including the invoice composite foreign key.
    dbml = ['// Current database ER source; selected view diagrams are projections.',
            f'// All {len(models)} ORM tables; django_migrations is a framework migration journal.',
            '// Partial uniqueness, exclusions and triggers are documented separately.', '']
    catalog = ['# 当前数据库字段目录', '',
        '结构基线日期：'+data['observed_on']+f'。本目录列出{len(models)}张ORM业务／框架表；另1张django_migrations为框架迁移日志。', '',
        '字段类型、可空、SQL约束及索引来自数据库只读结构核对；模型映射来自同版本已运行应用。没有读取任何业务行、密码、配置值或字段默认值。', '',
        'PK=主键；UK=单列唯一；FK=外键；NULL=可空。复合唯一、条件唯一和排斥约束另列，不用单列UK代替。', '']
    for name,m in models.items():
        catalog += ['## '+name, '', '模型：`'+m['model']+'`'+('；ORM生成的连接表。' if m['auto_created'] else '。'), '',
                    '| 列 | PostgreSQL类型 | 键 | 可空 | 引用 |', '|---|---|---|---|---|']
        dbml += ['Table '+name+' {']
        for f in m['fields']:
            actual_type=actual_columns[name,f['column']]['db_type']
            flags = [v for k,v in [('pk','PK'),('unique','UK'),('target_table','FK')] if f.get(k) and not (k=='unique' and f['pk'])]
            target = f"`{f['target_table']}.{f['target_column']}`" if f['target_table'] else '—'
            catalog += [f"| {f['column']} | {actual_type} | {' / '.join(flags) or '—'} | {'是' if f['null'] else '否'} | {target} |"]
            dbflags = (['pk'] if f['pk'] else ['unique'] if f['unique'] else []) + (['null'] if f['null'] else ['not null'])
            dbml += ['  '+f['column']+' '+json.dumps(actual_type)+' ['+', '.join(dbflags)+']']
        for diff in type_differences:
            if diff['table']==name:
                catalog += ['', '兼容性记录：`'+diff['column']+'`的模型类型为`'+diff['model_type']+'`，实际数据库类型为`'+diff['database_type']+'`。本目录按实际类型记录；未执行缩窄字段或改写历史。']
        catalog += ['', '数据库约束：', '']
        catalog += ['- `'+c['name']+'`：`'+c['definition'].replace('|','\\|')+'`。'
                    for c in data['constraints'] if c['table']==name]
        catalog += ['', '索引（含条件唯一索引）：', '']
        catalog += ['- `'+i['name']+'`：`'+i['definition'].replace('|','\\|')+'`。'
                    for i in data['indexes'] if i['table']==name]
        catalog += ['', '跨表及历史触发器：', '']
        catalog += ['- `'+t['name']+'`：`'+t['definition'].replace('|','\\|')+'`。'
                    for t in data.get('triggers',[]) if t['table']==name]
        catalog += ['']
        composite=[]
        for c in data['constraints']:
            if c['table']!=name or c['kind']!='u':continue
            match=re.fullmatch(r'UNIQUE \(([^)]+)\)',c['definition'])
            if match and ',' in match[1]:composite.append((match[1],c['name']))
        if composite:
            dbml += ['  indexes {']
            dbml += ["    ("+cols+") [unique, name: '"+constraint+"']" for cols,constraint in composite]
            dbml += ['  }']
        dbml += ['}', '']
    for t,cols,parent,targets in sql_fks:
        side=lambda table,columns: table+'.'+(columns[0] if len(columns)==1 else '('+', '.join(columns)+')')
        unique=any(f['column'] in cols and f['unique'] for f in models[t]['fields'])
        dbml += ['Ref: '+side(t,cols)+(' - ' if unique else ' > ')+side(parent,targets)]
    (ROOT/'schema.dbml').write_text('\n'.join(dbml).rstrip()+'\n')
    (ROOT/'FIELD_CATALOG.md').write_text('\n'.join(catalog).rstrip()+'\n')
    relation_lines=['# 当前数据库外键关系', '',
        f'{len(sql_fks)}条实际SQL外键，其中{len(expected)}条对应ORM单列关系，1条为账单同次就诊复合外键。', '',
        '| 子表 | 外键列 | 父表 | 被引用列 |', '|---|---|---|---|']
    relation_lines += ['| '+t+' | '+', '.join(cols)+' | '+parent+' | '+', '.join(targets)+' |' for t,cols,parent,targets in sql_fks]
    (ROOT/'RELATIONSHIPS.md').write_text('\n'.join(relation_lines)+'\n')
    result = {}
    for name,view in VIEWS.items():
        parts=['digraph schema {', 'graph [rankdir=TB, bgcolor="white", pad="0.2", nodesep="0.40", ranksep="0.48", splines=polyline, outputorder=edgesfirst];',
               'node [shape=plain, fontname="Arial", fontsize=14];',
               'edge [color="#505965", arrowsize=0.8, dir=both];']
        edges=[]
        for table,columns in view['tables'].items():
            fields={f['column']:f for f in models[table]['fields']}
            assert set(columns)<=set(fields), (table,set(columns)-set(fields))
            rows=['<TR><TD COLSPAN="2" BGCOLOR="#e8edf2" BORDER="1"><B>'+table+'</B></TD></TR>']
            for col in columns:
                f=fields[col]
                key='PK' if f['pk'] else ('FK/UK' if f['unique'] else 'FK') if f['target_table'] else 'UK' if f['unique'] else ''
                rows += ['<TR><TD ALIGN="LEFT">'+key+'</TD><TD ALIGN="LEFT" PORT="'+col+'">'+html.escape(col)+(' ?' if f['null'] else '')+'</TD></TR>']
                if f['target_table'] in view['tables']:
                    assert f['target_column'] in view['tables'][f['target_table']]
                    edges.append((table,col,f['target_table'],f['target_column'], '0..1' if f['unique'] else '0..*', '0..1' if f['null'] else '1'))
            parts += ['"'+table+'" [label=<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">'+''.join(rows)+'</TABLE>>];']
        for t,col,parent,pcol,child_mult,parent_mult in edges:
            parent_symbol='teeodot' if parent_mult=='0..1' else 'teetee'
            child_symbol='teeodot' if child_mult=='0..1' else 'crowodot'
            layout=', constraint=false' if (t,col)==('adc_reception_case','visit_id') else ''
            parts += ['"'+parent+'" -> "'+t+'" [arrowtail="'+parent_symbol+'", arrowhead="'+child_symbol+'"'+layout+', tooltip="'+t+'.'+col+' references '+parent+'.'+pcol+'; '+child_mult+':'+parent_mult+'"];']
        parts += ['}']
        (ROOT/(name+'.dot')).write_text('\n'.join(parts)+'\n')
        result[name]=dict(title=view['title'],tables=len(view['tables']),relationships=len(edges),note=view['note'],columns=view['tables'])
    result['validation'] = dict(passed=True,tables=len(data['tables']),orm_tables=len(models),columns_types_and_nullability_checked=checked_columns,model_database_type_differences=type_differences,orm_foreign_keys=len(expected),sql_foreign_keys=len(sql_fks),
        sql_only_composite_foreign_keys=1, snapshot_sha256=hashlib.sha256((ROOT/'schema_snapshot.json').read_bytes()).hexdigest(),
        scope='Structure documentation only; this is not a new business or capacity acceptance result.')
    (ROOT/'view_manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:({i:v[i] for i in ('tables','relationships')} if k!='validation' else v) for k,v in result.items()},ensure_ascii=False))


if __name__=='__main__':
    build()
