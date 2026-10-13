# 工程追踪 v0.3

`已写源码`、`已运行测试`和`已满足需求`不是同一状态。本表的集成测试名称指待执行脚本。

| 基线需求/用例 | 模型/服务/入口 | 对应测试或下一门槛 | 当前状态 |
|---|---|---|---|
| FR-01 / UC-01 患者档案 | patients.models / create_patient / patient_create | 实际建档、跨店复用、身份查重 | 部分源码；C/R入口，完整编辑未做 |
| FR-02 过敏 | PatientAllergy / validate_allergies / update_allergies | checks.DataRulesTests；数据库关联与并发回归待补 | 纯规则已测；编辑页面/接诊复核未做 |
| FR-03 / UC-02 基础资料 | registry.models / seed_demo | 迁移、初始化、停用关系测试 | 模型/种子；完整维护未做 |
| FR-04 / UC-03 / UC-14 | create_slot / create_appointment / ExclusionConstraint | tests.BusinessIntegrationTests；2项DatabaseConcurrencyTests | 源码候选，尚未执行真实DB测试 |
| FR-05 / UC-04/05 | change_appointment / Visit状态约束 | 状态纯规则已测；实际服务回归待执行 | 源码候选 |
| FR-06 治疗意向 | VisitRequest / form字段 / reschedule复制 | 原子创建/复制，不进入治疗收费 | 源码候选 |
| FR-07 / UC-06 实际治疗 | care.TreatmentRecord及版本结构 | JSONschema、确认事实、历史保护及真实编辑竞争 | 仅结构/护栏，未开放 |
| FR-08 / UC-07/11/13 结算 | Invoice/Version/复合FK/保护SQL | 首次开单、零治疗、重试与并发 | 仅结构/护栏，未开放 |
| FR-09/10 / UC-08 | finance.Quarter / DentistQuarterCost | 全部成本完整性、无收入人员、当前版本汇总 | 仅结构，未开放 |
| FR-11 / UC-09 经营分析 | 只写quarter_bounds纯函数 | 取消率等指标实现留下一阶段 | 未实现；概览计数不是经营报表 |
| FR-12 / UC-10 | accounts.policies / selectors / 后端重查 | direct URL / stale grant / same binding / CSRF | 源码候选，真实授权测试未执行 |
| FR-13 / UC-12 | AuditEvent / emit / 保护SQL / CorrectionRequest | 审计回滚与DML保护待执行；完整更正未实现 | 部分源码 |
| FR-14 公网 | Compose本地环境 / 发布阻断 | TLS、节流、权限、备份恢复、依赖锁 | 未上线 |

下一增量之前先运行 `scripts/integration_gate.py`。未运行的测试没有结果；测试文件数量或断言数量不代表覆盖了全部需求。
