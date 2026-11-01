# 医疗代理与开治：需求—业务规则—测试追踪

业务问题 → 责任岗位 → 可观察结果 → 不变量 → 失败后继续 → 测试证据。

| 用例／业务问题 | 岗位与可观察结果 | 不变量及失败后继续 | PostgreSQL测试（tests/test_medical_proxy_preflight.py） |
|---|---|---|---|
| SU126 材料与临床资格混淆 | 有专项职责前台提交、核对版本；医师另行确认 | 默认不授予专项职责；跨店或撤权拒绝；退回后追加版本 | test_materials_and_clinical_approval_are_separate；test_front_duty_is_explicit_and_does_not_grant_medical_approval；test_return_resubmission_preserves_original_and_current_scope |
| SU127 未成年／成年适用性与争议 | 负责医师确认具体患者与步骤；疑难由另一指定医师处理 | 代理人及自己整理／核验的材料不能自审；重叠代理不能最后提交覆盖；本人拒绝不能由代理覆盖 | test_same_person_cannot_switch_from_materials_to_medical_approval；test_second_proxy_cannot_silently_replace_current_signer；test_proxy_cannot_override_existing_patient_refusal |
| SU128 代理选方案被误作同意 | 代理独立认可、拒绝或暂缓指定方案步骤 | 只有医疗权限不能预约或看全病历；方案选择不生成治疗或收费 | test_proxy_scheme_and_medical_decision_do_not_make_treatment_or_money；test_only_medical_authority_cannot_book_or_read_full_chart |
| SU129 代签范围及未答疑问 | 代理提问、医师答复、代理另行明确决定，保留实际来源 | 无同意继承；未答疑问阻止同意；预约授权不授予医疗读取 | test_unanswered_proxy_question_is_not_agreement；test_guardian_has_an_independent_scope_not_appointment_authority；test_proxy_cannot_read_unscoped_step_or_other_clinic_record |
| SU130 失效后旧预览继续生效 | 暂停／撤销后只保留本人相关办理状态与旧历史 | 新读取和确认重新核验；历史不可覆盖；重复确认一个效果 | test_revoke_invalidates_preview_without_rewriting_decisions；test_expired_proxy_cannot_create_new_decision；test_withdrawn_delegate_retains_status_without_new_clinical_access；test_revocation_and_agreement_serialize_and_preserve_history |
| SU131 按金额或服务名推定医疗规则 | 指定专业审核医师发布项目规则并明确启用诊所 | 未知为REVIEW；新规则需重核；不自动免责或补造旧依据 | test_review_required_rule_does_not_default_to_no_consent；test_changed_rule_requires_fresh_check；test_communication_rule_cannot_hide_unanswered_medical_question |
| SU132 同意与实际执行脱节 | 医师先保存开治依据，再引用其登记实际治疗 | 核对不收费；撤回、疑问、设备故障使旧依据不能继续；直接治疗入口不能绕过；实际／收费唯一 | test_normal_execution_needs_prior_check_and_uses_existing_charge_source；test_old_direct_charge_entry_cannot_bypass_control；test_equipment_failure_invalidates_prior_check；test_withdrawal_and_preflight_cannot_leave_usable_stale_check；test_partial_stage_uses_own_check_without_duplicate_charge |
| SU133 已发生治疗缺事前资料 | 如实补记发生时间与缺口，另一医师独立复核 | 不补造开治、不倒签；历史缺口不变成事前通过；无重复收费 | test_historical_fact_is_saved_with_gap_without_fabricating_preflight；test_actual_time_cannot_be_backdated_before_check |

专项文件有43项实际PostgreSQL测试，其中并发场景使用独立连接。完整回归、准确提交CI、浏览器、负载及恢复分别见本目录执行记录；不能将其中任何一种测试等同于专业审定、小程序官方工具或实际手机验收。

真实Chrome在18352验证资料受理→专项前台核验→负责医师确认、代理问答→明确同意、本人开治→执行、真实补记→独立复核。独立财务复算为两项实际治疗合计400、净收160、未收240；核对及医务复核不制造资金事实。

思维导图：材料版本与身份 → 适用性与指定范围 → 方案选择／医疗决定 → 准确开治依据 → 实际执行／真实补记 → 唯一收费与独立验证。
