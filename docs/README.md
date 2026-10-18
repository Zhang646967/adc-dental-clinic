# 项目文档分类导航

当前交付 → 业务与设计 → 运行与验证 → 历史来源。课程报告请从 [PDF](../课程报告/课程报告_张加良_8210241102.pdf)、[Word](../课程报告/课程报告_张加良_8210241102.docx) 或 [报告目录](../课程报告/README.md) 直接进入。

## 业务流程

| 范围 | 文档 |
|---|---|
| 业务演示、岗位与跟进 | [演示路线](DEMO_ROUTES_RC1.md)、[业务跟进](BUSINESS_FOLLOW_UP.md) |
| 接诊、治疗、结算与设备衔接 | [完整流程](CARE_FINANCE_EQUIPMENT_WORKFLOWS.md)、[交接规则](FINANCE_EQUIPMENT_HANDOFFS.md) |
| 收退款、资金凭据与逐笔对账 | [财务凭据](FINANCIAL_EVIDENCE_RECONCILIATION.md)、[账内日结](DAILY_RECONCILIATION.md) |
| 设备费用及维护 | [费用更正](EQUIPMENT_COST_AMENDMENTS.md)、[维护工单](MAINTENANCE_WORK_ORDERS.md) |
| 预约与排班 | [预约改期](RESCHEDULING_OPTIMIZATION.md)、[出诊维护](SU29_SU30_AVAILABILITY.md)、[前台协调](SU31_FRONT_COORDINATION.md) |
| 接诊控制、任务和通知 | [接诊控制](SU32_SU33_INTAKE_CONTROL.md)、[协调任务](SU34_SU35_SU36_COORDINATION_TASKS.md)、[通知](SU37_SU38_NOTIFICATIONS.md) |
| 基础目录与权限 | [目录规约](SU27_SU28_DIRECTORY.md)、[字段目录](FIELD_CATALOG.md) |

## 系统分析与设计

- [当前报告正文](report-source/REPORT.md)；[模型与用例的冻结来源](release_report/README.md)。
- [需求追踪](TRACEABILITY.md)、[物理设计](PHYSICAL_DESIGN.md)、[SQL 参考](sql/)、[模型图](diagrams/)。
- [成熟系统学习与差距](MATURE_SYSTEM_STUDY.md)、[后续开发方向](COMMERCIAL_DEVELOPMENT.md)。
- [AI 接口与边界](AI_INTERFACE.md)、[版本范围](V1_SCOPE_AND_REMAINING.md)。

## 部署与运行保障

- [Mac 使用与数据保护](MACOS.md)、[课程上线与备份恢复](COURSE_ONLINE.md)、[部署配置](../deployment/README.md)。
- [R2 阶段规划](R2_OPERATIONAL_ASSURANCE_PLAN.md)、[R2.1 请求编号和安全日志](R21_SAFE_DIAGNOSTICS.md)、[R2.2 通知与监测](R22_OPERATIONS_OBSERVATION.md)、[R2.3 恢复点新鲜度](R23_RECOVERY_FRESHNESS.md)。
- [安全差距登记](SECURITY_ASVS_GAP_REGISTER.md)、[通知进程运维](WORKER_PROCESS_ACCEPTANCE.md)。

## 测试与验收

| 验证范围 | 实际记录 |
|---|---|
| R2.3 第一批备份凭据工具 | [记录与范围](evidence_r23/README.md) |
| R2.2 心跳、积压与监测失效 | [证据说明](evidence_r22/README.md)、[需求到测试](evidence_r22/requirement_trace.json)、[Mac 交付](evidence_r22/delivery.json) |
| R2.1 请求追踪与安全日志 | [证据目录](evidence_r21/README.md) |
| R1 财务闭环及加密恢复 | [证据目录](evidence_financial_evidence/README.md) |
| 多诊所隔离与容量 | [历史容量基线](evidence_multiclinic/README.md)、[范围说明](MULTICLINIC_CAPACITY.md) |
| 浏览器业务验收与公网演示 | [G3](G3_BROWSER_ACCEPTANCE.md)、[G4 历史结果](evidence_g4/) |
| 既有系统测试 | [测试报告索引](TEST_REPORT.md)、[RC 验收](evidence_rc1/) |

每次验证按自己的日期、提交与环境解释。历史通过不代表后续版本已重新执行，也不代表云端或商业上线通过。

## 报告源文件

[report-source/](report-source/README.md) 存放可编辑正文、生成器、格式说明、目录映射和验证摘要。正式 Word/PDF 只放在顶层 [课程报告/](../课程报告/)，避免多个“最新版”。历史格式来源和模型保留原路径，以维持原始证据及复现依赖。

## 源码与资源

| 职责 | 目录 |
|---|---|
| 账号、岗位、诊所与基础目录 | [accounts](../accounts/)、[workspaces](../workspaces/)、[registry](../registry/) |
| 患者、排班、治疗与协调 | [patients](../patients/)、[scheduling](../scheduling/)、[care](../care/)、[coordination](../coordination/) |
| 财务与设备 | [finance](../finance/)、[equipment](../equipment/) |
| 通知和业务操作 | [notifications](../notifications/)、[operations](../operations/) |
| 门户、辅助和无障碍引导 | [portal](../portal/)、[assistants](../assistants/)、[guidance](../guidance/) |
| 公共运行能力、配置与界面 | [adc_core](../adc_core/)、[config](../config/)、[templates](../templates/)、[static](../static/) |
| 自动验证、运维脚本和部署 | [tests](../tests/)、[checks](../checks/)、[scripts](../scripts/)、[deployment](../deployment/) |

## 历史材料

- [R5/RC1 冻结报告](release_report/README.md)、[早期 R1.0 提交](submission_R1/README.md)、[v0.7 提交](teacher_submission/README.md)。均不是当前提交版。
- `archive_*`、`history/`、`increments/`：历史设计、版本说明及增量原文。
- `evidence_*`：各阶段验收证据；按目录名称和内部提交号定位，不覆盖历史结果。
- [历史 Windows 指南](history/README_RC1_WINDOWS.md)、[原始迁移校验](original_migration_hashes.json)、[更早版本记录](../history/)。

仓库不收录私有账号指南、密码、密钥或数据库备份；运行时私有目录的用途见部署指南。
