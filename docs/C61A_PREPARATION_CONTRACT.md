# C6.1A 医保资料与模拟待遇

官方来源 → 原件及规范记录 → 独立复核 → 本店安排与收费适配 → 前台待遇核对 → 原费用结算准备。

本批为已实现的源码候选，交付验证进行中。当前在用版本仍为已验收C1-WX。C6.1B费用分担及唯一结算、C6.1C基金到账及退费继续按[总合同](C61_LOCAL_INSURANCE_CONTRACT.md)推进；资料准备不表示这些资金能力已经实现。真实微信及医保联网仍等待平台和机构条件。

## 可办理流程

1. 财务从`/insurance/`预览随版本核对的湖南口腔目录，明确导入原件、规范记录及202个项目编码；另一财务账号查阅原件及项目，预览后决定启用或未通过。
2. 未通过或停用后，从原目录明确“重新提交同一来源核对”。政策版本保持原值，审阅次数递增并引用前次；新记录再次等待独立复核。原决定不覆盖，旧安排和映射不自动恢复。
3. 主管在当前店准备有效期安排，财务独立核对。已启用安排的日期包含首尾两日，同店不能重叠；目录、门店和日期分别核验。
4. 主管明确选择原收费项目与政策项目，核对含义、原收费单位和每单位对应的目录数量；财务独立核对后启用。缺失单位或支付规则保持待核对，定义改变须重新适配，不改变原收费价格或实际数量。
5. 前台从当前店可见患者档案进入“核对模拟医保待遇”，登记合成参保地、类型、有效期、结果及SIM依据。变更追加新版本，最新未知或过期不回退使用旧已核对结果。参保地与就诊城市或定位不一致时给出待核对提示。

## 权限与模块责任

医保模块拥有来源目录、审阅链、门店安排、收费映射、待遇版本及办理事件。收费定义继续由原目录维护，实际治疗与原账单仍由原模块管理，财务资金不由本批改写。

| 岗位 | 可办理范围 |
|---|---|
| 财务 | 全链政策来源、独立资料复核及停用；不能复核自己提交的记录 |
| 本店主管 | 本店安排、项目适配及明确停用；不读取患者待遇明细 |
| 本店前台 | 本店可见患者的合成待遇核对及已发布政策查阅 |
| 总部 | 数量及待办汇总，不取得患者或来源复核明细 |
| 医师、患者、技术管理 | 不因其他岗位或技术身份取得本批职能权限 |

候选查询与GET不办理业务。写入需要有效岗位、当前诊所、CSRF、工作区签名、限时预览和明确确认；事务内重读授权和版本。医保资料不能扩大PatientAccess或代约授权。患者待遇查阅记录类型、对象编号、目的及结果，不记录姓名、证件或说明文字到运行日志。

## 来源与已知缺失

来源为[湘医保发〔2026〕12号](https://ybj.hunan.gov.cn/ybj/first113541/firstF/f3113607/202603/t20260331_33945644.html)，口腔项目支付政策自2026年6月1日起执行。甲类先自付为零仍须按基本医保分担，不是统一报销100%。

原件实际为OLE Word，虽官方附件名为docx，仍保留原始字节；下载使用正确doc扩展名。232行对应202个不同编码，30行完全相同的重复保留原表位置；202编码包含项目变体。`013105010310000`的支付规则及先自付保持UNKNOWN／NULL；`013105170060001`和`013105170060011`的单位保持NULL。

[来源包说明](../insurance/policy_sources/README.md)记录来源、原件与规范摘要。服务端加载固定审阅包，不接受浏览器自报行或比例。导入在同一事务保存原始字节、规范数据及项目；不同账号并发导入和再次核对按来源事务锁串行，并以数据库唯一和版本约束防止重复效果。

## 需求与验收追踪

| 业务规则 | 验收证据入口 |
|---|---|
| 原字节、规范项目、重复行和未知来源可追溯 | `test_catalogue_retains_source_bytes_all_rows_and_exact_duplicates`、`test_source_unknown_classification_and_two_missing_units_remain_missing` |
| 原件或规范包改变时整批不保存 | `test_raw_or_normalized_asset_changes_reject_entire_import` |
| 独立复核、角色切换不能自己审批 | `test_import_requires_finance_and_publication_requires_different_account`、`test_manager_cannot_self_review_by_changing_role` |
| 拒绝或停用后可继续，不伪造政策变更 | `test_rejected_source_can_be_explicitly_resubmitted_without_fabricating_policy`、`test_disabled_source_retry_does_not_revive_previous_arrangement` |
| 原负责人失效时由现任账号明确接续 | `test_departed_original_importer_does_not_block_new_account_resubmission` |
| 当前店、撤权与过时预览正确拒绝 | `test_current_clinic_rejects_other_patient_and_other_arrangement`、`test_revoked_authority_after_http_preview_never_creates_record` |
| 首次导入及再次提交各保留唯一结果 | `test_concurrent_first_imports_from_different_accounts_keep_one_source`、`test_concurrent_explicit_resubmissions_create_one_next_review` |
| 安排首尾日期、并发重叠与数据库排斥一致 | `test_arrangement_has_independent_review_and_inclusive_date_range`、`test_concurrent_overlapping_arrangements_only_one_confirmed` |
| 缺失单位、规则、定义变化继续待核对 | `test_missing_policy_unit_or_rule_keeps_mapping_awaiting_review`、`test_fee_change_before_review_or_after_activation_is_visible` |
| 待遇不按定位或手机号推断 | `test_eligibility_is_append_only_and_does_not_follow_location_or_phone`、`test_eligibility_dates_and_clinic_arrangement_checked_separately` |
| 版本不能跨患者，同次重试不新增版本 | `test_eligibility_chain_cannot_cross_patient_by_direct_insert`、`test_concurrent_eligibility_versions_have_single_current_result` |
| 七岗位、CSRF和目标页分别约束 | `test_all_seven_role_entry_boundaries_and_hq_projection`、`test_csrf_and_current_workspace_are_both_required`、`test_confirmation_cannot_be_retargeted_to_other_record_page` |
| 历史超过20条后仍可查阅 | `test_arrangement_history_remains_reachable_after_twenty_rows` |
| 准备不制造治疗或资金 | `test_preparation_workflow_creates_no_clinical_invoice_or_cash_facts` |

测试实现在[业务与并发验收](../tests/test_insurance_preparation.py)及[HTTP验收](../tests/test_insurance_preparation_http.py)。编写、执行、准确版本CI、同镜像浏览器、加密恢复和本机安装分别记录，不能由测试名称推定通过。

## 结构与交付边界

原54份迁移保持原字节，追加两份；实际独立PostgreSQL观察为115张SQL表、114张ORM表、1128个ORM字段、318条SQL外键及83项触发器。两幅新ER按实际列、可空、唯一和外键生成，与已有二十幅视图合并为二十二幅。已知框架连接表整数／大整数差异保留，不缩窄原字段。

银行流水仍沿用R1的一对一适用范围，本批不虚构基金现金、个人账户扣款或平衡分录。连续临床使用、真实平台／接口、云部署、24小时运行和历史Windows数据恢复按原边界记录。

思维导图：政策原件 → {来源核对、缺失、独立审阅链} → {本店日期、收费单位、患者参保资料} → 明确适用／待核实 → 原实际费用结算准备；各步骤不直接产生资金。
