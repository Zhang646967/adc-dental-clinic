# C3.2B1：本人医疗决定

认可方案 → 医师核对本人及告知 → 提问答复 → 准确版本决定 → 撤回与历史。

本批为成年患者本人医疗沟通与决定的课程软件实现。复用实际检查、已确认方案步骤和八项具体治疗说明；不以微信登录、预约代办、查看说明或认可方案替代医疗同意。适格医疗代理、完整开治核对、病案归档及可靠电子签名验收在后续批次。

## 岗位与办理

- 负责医师须具备当前诊所及服务的RECORD范围，核对本人身份和理解表达条件，登记依据编号、准确检查和方案步骤。年龄只作本批办理范围检查，不能自动判断决定能力。首次确认和重新告知均预览后原子保存。
- 患者本人在网站或小程序查看同一投影，可提问、同意、拒绝、暂缓；未答复疑问阻止新同意。医师答复只解决沟通事项，不产生患者决定。重新告知不能隐去未回答问题。
- 每份告知版本保留一次明确决定。改变拒绝／暂缓等决定时，医师重新告知并建立新版本；旧决定继续可读。原同意可明确撤回未实施部分，已有治疗、预约、收费与资金历史均不被回滚。
- 患者账号决定与医师登记本人纸质原件明确区分；纸件须原件编号、核对确认及实际时间，另存服务器登记时间。不倒签早于本份告知的纸件。
- 预约监护／代办授权不授予临床读取或医疗代签。前台、主管、财务、总部及技术岗位不继承临床权限。医师撤权阻止新增同意，但不阻止仍具本人访问权的患者表达拒绝或撤回。
- 医师在“检查记录工作台 → 医疗告知与疑问待办”办理未答复事项；患者从治疗方案的具体步骤进入。两端均可回看原方案和各告知版本。

## 数据与事务

追加`clinical/0009_medical_consent.py`，原66份迁移保持不变。新增稳定步骤级`MedicalConsent`、不可改写`ConsentVersion`、追加式`ConsentEvent`。前者只允许变更并发游标；后两者由PostgreSQL触发器保护，外键与触发器核对患者、诊所、步骤、检查来源和问答归属。

所有写入沿用工作区签名、CSRF、本人访问或专业授权及统一患者／方案锁。参与账号按编号加锁后进入既有锁序。预览绑定方案游标、检查版本、患者快照、告知游标、动作和操作编号，确认重新核对；重复原操作返回原事件。并发决定只允许一个有效结果。审计仅含编号、动作与来源，不记录临床正文。

旧方案选择`PlanDecision`继续保持原意义，不自动转为同意。新告知、提问、答复、决定均不制造实际执行、账单、收款或退款。检查／方案／患者资料变化使新增肯定决定重新核对，旧事实保留。读取使用一致性快照，不通过GET改变状态。

## 需求追踪

| 编号 | 可观察规则 | 直接验证 |
|---|---|---|
| MC01 | 告知绑定真实检查、准确步骤和负责医师，预览不写入 | `test_preview_is_read_only_and_first_publish_has_exact_source` |
| MC02 | 本人决定与方案选择、实际治疗及资金分离 | `test_self_decision_retains_evidence_without_changing_scheme_care_or_money` |
| MC03 | 疑问待答阻止同意，医师答复不代作决定 | `test_question_requires_answer_and_answer_is_not_consent` |
| MC04 | 拒绝、暂缓、撤回和重新告知均保留 | `test_decline_defer_and_withdraw_are_explicit_and_do_not_cancel_visit` |
| MC05 | 换版不继承旧同意，旧版可撤回 | `test_new_explanation_does_not_inherit_old_agreement`、`test_old_agreement_can_be_withdrawn_without_affecting_new_version` |
| MC06 | 换版不能抹去未回答问题 | `test_unanswered_questions_survive_republication` |
| MC07 | 旧预览、重复确认及并发不覆盖或重复登记 | `test_stale_preview_and_same_operation_replay`、`test_parallel_confirmations_create_one_decision` |
| MC08 | 撤权、跨患者、七角色和预约监护关系不扩大权限 | `test_revoked_patient_authority_blocks_pending_confirmation`及同文件角色／代理负例 |
| MC09 | 纸签来源与实际时间明确，不倒签 | `test_paper_original_is_explicit_with_two_timestamps`及纸签负例 |
| MC10 | PostgreSQL保留历史；日志无临床原文 | `test_versions_events_and_head_identity_are_retained_in_postgresql`、`test_audit_contains_only_metadata_not_clinical_question` |
| MC11 | 新方案、身份变化及本人资格重新核对 | 同文件新方案、身份变化、未成年／未核对负例 |
| MC12 | 网站、小程序和医师待办引用同一事实 | 同文件HTTP／待办测试及`verify_native_consents.cjs` |

## 交付边界

18342用于本轮独立合成病例；原18332病例11／方案1和18315历史不改动。本机主系统需准确提交CI、加密独立恢复及原数据／配置比对后才更新。WorkBuddy只负责冻结包导入、编译和官方工具患者操作回归，不改业务源码、数据库或密钥。390工具、375／430及字体放大、真实微信、手机、体验权限和公网各自记状态。

思维导图：本人医疗决定 → {准确告知、身份核对、提问答复、来源区分} → {同意、拒绝、暂缓、撤回} → 版本与权限 → 后续代理核验／开治核对／归档。
