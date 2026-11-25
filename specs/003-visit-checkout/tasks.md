# 离店核对实施与验收

| 要求 | 实现与检查 | 交付证据 |
| --- | --- | --- |
| LC1、LC2 | 患者原就诊和前台就诊详情共用离店摘要。结算单以当前发布版本、独立记账的收退、预收分配、已核对医保分摊为准。已发布处置与净发药按本人权限读取。 | `tests.test_patient_visit_review`、`tests.test_visit_checkout`。另按 A 至 F 核对候选环境的三处读数和历史账单。 |
| LC2 并发 | 在查询已取当前版本时由另一数据库连接独立批准更正，两次读取分别看到完整旧版与完整新版。 | `test_concurrent_correction_yields_one_bill_version_and_its_actual_balance`。 |
| LC3 | 各指示逐行区分有效预约、历史预约、未约与原店协助。报告自助查号绑定原就诊、检查与发布版本。账单和关联预约可返回原就诊。 | `test_current_bill_and_linked_return_are_scoped_and_read_only`、`tests.test_examination_followup`；合成库另查取消、超窗、旧依据关联有效预约及无指示。 |
| LC4 | 前台按当前角色和门店，只展示安排与账务。患者接口和网页复核就诊人。代办、医疗代理、另一患者及他店前台沿用原权限。 | 按本人、预约代办、医疗代理、另一患者和两家门店前台取证。独立记录查询前后业务表差异。 |
| 原生与手机 | WorkBuddy 在已接入 18547 的源码上完成原生离店展示，在隔离库九笔就诊上进行只读验收。集成时补查旧接口金额缺失、取消预约回查、看诊中及身份切换。 | WorkBuddy 提交 `cf2167a`。见[验收记录](verification.md)，原生回归包含 `checks/test_visit_checkout_node.cjs`、`checks/test_return_sources_node.cjs` 和 `scripts/verify_native_alignment.cjs`。关闭调试的真机和首次使用者任务另行留证。 |

字段和空值以[离店接口](contracts/checkout.md)为准。九笔就诊的实际金额、关联预约和分端验证进度见[18548 离店核对验收记录](verification.md)。合成库初始化、凭据和原始截图保存在包外私有目录。
