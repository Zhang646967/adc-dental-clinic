**C1-WX 当前本地交付：** [账号及本人申请](C1WX_ACCOUNT_CONTRACT.md) · [准确CI、跨端、恢复与更新](evidence_c1wx/README.md) · [私有本地试用](C1WX_LOCAL_GUIDE.md)。

**C0.4 当前本地交付：** [找店与登录合同](C04_PATIENT_DISCOVERY_CONTRACT.md) · [准确CI、跨端、恢复及更新](evidence_c04/README.md) · [本地使用](C04_LOCAL_GUIDE.md)。

**C2.2–C2.3 当前交付：** [连续方案与实际执行](C22_CONTINUITY_CONTRACT.md) · [复诊与加工就绪](C23_RECALL_LAB_CONTRACT.md) · [准确版本、容量、恢复与本机交付](evidence_c23/release.json)。

**当前 C1.2：** [专业权限与限定转诊](C12_AUTHORITY_CONTRACT.md) · [本机交付证据](evidence_c12/release.json) · [C1–C2执行进度](C1_C2_PROGRESS.md)。

# 项目文档分类导航

当前产品方向：[商业V2总计划](COMMERCIAL_V2_MASTER_PLAN.md) → [代码与证据基线](COMMERCIAL_V2_BASELINE.md) → [分批需求及验收](COMMERCIAL_V2_BACKLOG.json)。首发采用单连锁独立部署，完整诊疗替代纳入目标；课程报告与旧执行记录继续作为来源保留。

最新规划（2026-10-24）：[中国患者入口、连锁布局与医保研究](research/CHINA_PATIENT_ACCESS_STUDY_20261024.md) → [C0.4找店、C1-WX身份与C6医保实施安排](PATIENT_DISCOVERY_AND_INSURANCE_PLAN.md) → [C6.1本地合同](C61_LOCAL_INSURANCE_CONTRACT.md)。含八省会二十店合成设计、14项需求验收与[官方来源登记](research/china_patient_access_sources.json)，C0.4已本地交付，C1-WX本地流程已交付，真实微信及C6.1继续实施。

前阶段研究（2026-10-23）：[Open Dental 等六类系统调研](research/DENTAL_PRACTICE_STUDY_20261023.md) → [C1–C2 身份与连续诊疗](COMMERCIAL_V2_NEXT_STAGE.md) → [需求与验收追踪](research/NEXT_STAGE_TRACEABILITY.json)。[来源登记](research/dental_study_sources.json)区分官方手册、厂商声明、调查与法规；[规划模型](research/MODEL_NOTES.md)不替代实际数据库 ER。

当前交付 → 业务与设计 → 运行与验证 → 历史来源。课程报告请从 [PDF](../课程报告/课程报告_张加良_8210241102.pdf)、[Word](../课程报告/课程报告_张加良_8210241102.docx) 或 [报告目录](../课程报告/README.md) 直接进入。

## 业务流程

| 范围 | 文档 |
|---|---|
| 连续诊疗、复诊与加工 | [方案与唯一收费](C22_CONTINUITY_CONTRACT.md)、[责任与具体版本就绪](C23_RECALL_LAB_CONTRACT.md)、[验证](evidence_c23/README.md)、[跨岗位演示](CONTINUING_CARE_DEMO.md) |
| 患者关系与预约代办 | [C1.1业务流程](C11_PATIENT_RELATIONSHIPS.md)、[权限与数据合同](C11_IDENTITY_CONTRACT.md) |
| 微信小程序与教师试用 | [原生工程与本地导入](../clients/wechat/README.md)、[本地／微信／云端交付](COURSE_TEACHER_DELIVERY.md) |
| 业务演示、岗位与跟进 | [演示路线](DEMO_ROUTES_RC1.md)、[业务跟进](BUSINESS_FOLLOW_UP.md) |
| 接诊、治疗、结算与设备衔接 | [完整流程](CARE_FINANCE_EQUIPMENT_WORKFLOWS.md)、[交接规则](FINANCE_EQUIPMENT_HANDOFFS.md) |
| 收退款、资金凭据与逐笔对账 | [财务凭据](FINANCIAL_EVIDENCE_RECONCILIATION.md)、[账内日结](DAILY_RECONCILIATION.md) |
| 设备费用及维护 | [费用更正](EQUIPMENT_COST_AMENDMENTS.md)、[维护工单](MAINTENANCE_WORK_ORDERS.md) |
| 电话接待与统一资源 | [B1.2＋B1.3业务合同](B12_B13_RECEPTION_RESOURCES.md)、[场景追踪](evidence_b12_b13/traceability.md) |
| 取消分析与服务改进 | [B1.1业务合同](B11_APPOINTMENT_IMPROVEMENT.md)、[领域及状态图](diagrams/)、[已执行追踪](evidence_b11/traceability.md) |
| 患者自助改期 | [B1.4业务合同](B14_PATIENT_RESCHEDULING.md)、[执行证据](evidence_b14/README.md) |
| 前台排班与数据库关系 | [B1.3.1实现及后续安排](FRONT_DESK_SCHEDULING_PLAN.md)、[预约业务总计划](APPOINTMENT_BUSINESS_PLAN.md) |
| 预约与排班 | [预约改期](RESCHEDULING_OPTIMIZATION.md)、[出诊维护](SU29_SU30_AVAILABILITY.md)、[前台协调](SU31_FRONT_COORDINATION.md) |
| 接诊控制、任务和通知 | [接诊控制](SU32_SU33_INTAKE_CONTROL.md)、[协调任务](SU34_SU35_SU36_COORDINATION_TASKS.md)、[通知](SU37_SU38_NOTIFICATIONS.md) |
| 基础目录与权限 | [目录规约](SU27_SU28_DIRECTORY.md)、[字段目录](FIELD_CATALOG.md) |

## 系统分析与设计

- [当前报告正文](report-source/REPORT.md)；[模型与用例的冻结来源](release_report/README.md)。
- [当前数据库ER与字段目录](database/README.md)、[296条实际外键](database/RELATIONSHIPS.md)、[领域与状态图](diagrams/)。
- [需求追踪](TRACEABILITY.md)、[历史v0.3物理设计](PHYSICAL_DESIGN.md)、[SQL 参考](sql/)。
- [页面美观与实用性调研](UI_UX_STUDY.md)、[首批界面与浏览器验证](evidence_ux1/README.md)。
- [2026-10-23 成熟系统与诊所业务调研](research/DENTAL_PRACTICE_STUDY_20261023.md)、[下一阶段实施计划](COMMERCIAL_V2_NEXT_STAGE.md)；[历史成熟系统学习](MATURE_SYSTEM_STUDY.md)、[历史后续方向](COMMERCIAL_DEVELOPMENT.md)。
- [AI 接口与边界](AI_INTERFACE.md)、[版本范围](V1_SCOPE_AND_REMAINING.md)。

## 部署与运行保障

- [Mac 使用与数据保护](MACOS.md)、[课程上线与备份恢复](COURSE_ONLINE.md)、[部署配置](../deployment/README.md)。
- [R2 阶段规划](R2_OPERATIONAL_ASSURANCE_PLAN.md)、[R2.1 请求编号和安全日志](R21_SAFE_DIAGNOSTICS.md)、[R2.2 通知与监测](R22_OPERATIONS_OBSERVATION.md)、[R2.3 恢复点新鲜度](R23_RECOVERY_FRESHNESS.md)、[R2.4 本地验收计划](R24_ACCEPTANCE_PLAN.md)。
- [R2.4.1 主机事件与故障处置](R241_HOST_EVENTS.md)、[R2.4.2 业务依赖演练与处置手册](R242_DEPENDENCY_DRILLS.md)。
- [安全差距登记](SECURITY_ASVS_GAP_REGISTER.md)、[通知进程运维](WORKER_PROCESS_ACCEPTANCE.md)。

## 测试与验收

当前[C1-WX账号与本人核验](evidence_c1wx/README.md)；历史[C2.2–C2.3连续诊疗与加工](evidence_c23/README.md)；历史[C1.1患者关系与预约代办](evidence_c11/README.md)；历史[C0.3患者渠道验证与交付](evidence_c03/README.md)；历史[B1.5.3页面与候补衔接](evidence_b153/README.md)；[B1.5.1原生小程序本地联调](evidence_b15/README.md)；[B1.4患者改期、容量与恢复](evidence_b14/README.md)及此前各阶段按原范围保留。微信开发者工具、真机、体验版和云端仍待独立验收。

| 验证范围 | 实际记录 |
|---|---|
| B1.2＋B1.3 电话、资源与维修协调 | [执行证据](evidence_b12_b13/README.md)、[场景追踪](evidence_b12_b13/traceability.md)、[容量边界](evidence_b12_b13/capacity.json)、[本机交付](evidence_b12_b13/delivery.json) |
| B1.1 取消分析、原因跟进与措施复核 | [执行证据](evidence_b11/README.md)、[需求追踪](evidence_b11/traceability.md)、[恢复范围](evidence_b11/recovery.md) |
| R2.4.3 等价容量与UX2 | [执行证据](evidence_r243/README.md)、[需求追踪](evidence_r243/requirement_trace.json)、[页面与浏览器](evidence_ux2/README.md)、[Mac交付](evidence_r243/delivery.json) |
| R2.4.2 依赖恢复及UX1界面 | [执行证据](evidence_r242/README.md)、[需求追踪](evidence_r242/requirement_trace.json)、[界面验证](evidence_ux1/README.md)、[Mac交付](evidence_r242/delivery.json) |
| R2.4.1 主机事件与故障处置 | [执行证据](evidence_r241/README.md)、[需求追踪](evidence_r241/requirement_trace.json)、[Mac 交付](evidence_r241/delivery.json) |
| R2.3 备份与独立恢复工具 | [记录与范围](evidence_r23/README.md) |
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
| 患者、排班、治疗与协调 | [reception](../reception/)、[patients](../patients/)、[scheduling](../scheduling/)、[care](../care/)、[clinical](../clinical/)、[coordination](../coordination/) |
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
