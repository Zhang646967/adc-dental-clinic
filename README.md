**系统分析与设计课程大作业｜张加良｜信管T2401｜8210241102**

📄 **[课程报告 PDF（推荐阅读）](课程报告/课程报告_张加良_8210241102.pdf)** · **[课程报告 Word](课程报告/课程报告_张加良_8210241102.docx)** · [报告说明](课程报告/README.md)

教师查阅顺序：课程报告 → [业务演示路线](docs/DEMO_ROUTES_RC1.md) → [验收记录](docs/README.md#测试与验收)。报告文件名固定；封面日期及 Git 历史标明版本。

**C6.1B/C 源码已实现：原账单模拟结算、基金到账分配、差异跟进和撤销。** 1,935项完整PostgreSQL回归通过；同镜像业务、容量、恢复及原系统更新继续按[专项证据](docs/evidence_c61bc/README.md)执行，尚不标记最终交付。[办理指南](docs/C61BC_LOCAL_GUIDE.md) · [业务合同](docs/C61BC_SETTLEMENT_CONTRACT.md)。

**C6.1A 已在本机交付：医保目录、本店安排、收费适配与模拟待遇。** 原件、独立审阅链、明确单位和待遇历史可核对；准确CI、1,106项规则／1,826项PG回归、67项同镜像浏览器及权限、115表加密恢复和原系统保护更新通过。183页报告与22幅实际ER同步。[本地办理](docs/C61A_LOCAL_GUIDE.md) · [业务合同](docs/C61A_PREPARATION_CONTRACT.md) · [交付证据](docs/evidence_c61a/README.md)。后续结算与基金清算已进入C6.1B/C最终验收。

**C1-WX 已在本机交付：患者账号、联络来源、本人建档与独立前台核验。** 网站／小程序沿用原预约、改期、候补与患者切换，暂停可复核恢复原关联。[执行证据](docs/evidence_c1wx/README.md) · [本地试用](docs/C1WX_LOCAL_GUIDE.md)。真实微信及医保联网另行验收。

**C0.4 已在本机交付：访客找店、由近到远与患者／员工登录分流。** 八省会二十家合成门店可浏览，长沙四店可约；主管维护公开资料，患者按需登录后继续原服务。网站与小程序共用预约和患者授权。[交付证据](docs/evidence_c04/README.md) · [本地使用](docs/C04_LOCAL_GUIDE.md)。

**C2.2–C2.3 已在本机验收交付：连续方案、实际治疗与复诊加工协同。** 网站／小程序本人决定、前台后续责任、手工送返与医师验收、唯一原收费已衔接。[业务合同](docs/C23_RECALL_LAB_CONTRACT.md) · [准确版本、容量、恢复与交付](docs/evidence_c23/README.md)。

**C2.1 已在本机验收交付：健康自述与结构化检查记录。** 患者本人健康自述、实际检查、牙位牙面、草稿冲突继续、确认版本与更正，衔接受控转诊和原接诊结算。[业务合同](docs/C21_CLINICAL_CONTRACT.md) · [分项证据与剩余门槛](docs/evidence_c21/README.md)。

**C1.2 已在本机验收交付：专业操作范围与限定跨店转诊。** 主管整理资质、受委任医师独立审核；接收店核对身份、指定医生接收，患者本人可在网站／小程序终止披露。[业务合同](docs/C12_AUTHORITY_CONTRACT.md) · [执行证据](docs/evidence_c12/README.md)。

**C1.1 已交付：患者关系与预约代办。** 前台受理与核验，网站／小程序选择本人或授权患者，共用预约、改期和候补。[办理说明](docs/C11_PATIENT_RELATIONSHIPS.md) · [验证与交付](docs/evidence_c11/README.md)。

**Commercial V2 direction:** an independently deployed platform for a dental
chain, covering patient services, operations and full clinical replacement
including electronic records and prescribing. [Product and release plan](docs/COMMERCIAL_V2_MASTER_PLAN.md)
· [Inspected baseline](docs/COMMERCIAL_V2_BASELINE.md)
· [Acceptance backlog](docs/COMMERCIAL_V2_BACKLOG.json).
The wider clinical V2 program continues; the current local baseline has not been qualified for
production patient care. Historical engineering and academic materials follow.

**2026-10-24 患者入口与中国医保规划：** [定位找店、微信身份与中国口腔连锁调研](docs/research/CHINA_PATIENT_ACCESS_STUDY_20261024.md) → [C0.4访客入口、C1-WX账号绑定与C6医保分批计划](docs/PATIENT_DISCOVERY_AND_INSURANCE_PLAN.md)。默认由近到远，已准备含长沙的八省会二十店合成场景；真实微信和医保接入单独验收。C0.4准确CI、同镜像浏览器、独立恢复、本机保护更新与报告已通过；C1-WX及C6.1A本地流程已交付；C6.1B/C本地资金流程已实现并继续最终验收，真实联网另行验收。

**2026-10-23 商业化调研与下一阶段：** [六类成熟牙科系统与诊所业务差距](docs/research/DENTAL_PRACTICE_STUDY_20261023.md) → [C1–C2 患者身份与连续诊疗计划](docs/COMMERCIAL_V2_NEXT_STAGE.md)。附 34 项外部来源、16 项需求追踪、24 个待执行验收场景及两幅明确标注为规划的领域关系图。当前实际 ER 与已执行验收保持独立。

**C0.3患者服务验证：** [网站／小程序与交付记录](docs/C03_RELEASE_ACCEPTANCE.md) · [执行证据](docs/evidence_c03/README.md)。已完成1,095项规则、1,474项数据库回归及五店187项跨端检查，修复接诊路径冲突，新增公开页面大字模式，ER与正式报告同步。准确应用提交CI、加密恢复及本机更新已通过，原业务与私有配置保留。

**历史系统入口与本人核验：** [打开本地入口](START_HERE.html)连接运行中的本机系统，提供六条完整业务核验路线及个人记录下载。[B1.6实施与执行边界](docs/B16_ENTRY_AND_VERIFICATION.md)区分新入口源码、自动检查和原运行实例；当前入口更新状态以C6.1A交付记录为准。

**新增患者服务中心与小程序候补衔接。** [页面与业务说明](docs/B153_PATIENT_SERVICE_CENTRE.md) · [执行证据](docs/evidence_b153/README.md)。

**课程交付：原生微信小程序与教师云端演示。** [小程序工程与本地导入](clients/wechat/README.md)支持课程患者登录、预约、普通／邀约改期、候补登记、邀约处置、取消及历史，复用网站预约数据。[交付安排](docs/COURSE_TEACHER_DELIVERY.md)区分本地联调、微信体验版与云端验收：小程序账号尚未注册，服务器尚未购买，暂不宣称微信或云端已上线。

**B1.4已实现：患者自助改期及候补替换。** 本人核对原新安排后明确确认，失败保留原约，重复提交返回唯一结果；与前台排班、资源、候补及真正取消的原因跟进衔接。[业务说明](docs/B14_PATIENT_RESCHEDULING.md) · [执行证据](docs/evidence_b14/README.md)。[数据库ER与完整目录](docs/database/README.md)同步115表、318条外键、83项触发器，二十二幅ER纳入课程报告；前台继续负责日常排班。

## 仓库分类

| 分类 | 入口 | 内容 |
|---|---|---|
| 课程交付 | [课程报告/](课程报告/) | 当前 PDF 和 Word，便于直接下载 |
| 项目文档 | [docs/](docs/README.md) | 业务流程、系统设计、部署运维、验收和历史导航 |
| 系统源码 | [源码结构](docs/README.md#源码与资源) | 按接诊、财务、设备、排班、通知等业务模块组织 |
| 验证 | [tests/](tests/)、[checks/](checks/) | PostgreSQL/业务回归与源代码规则检查 |
| 部署工具 | [deployment/](deployment/)、[scripts/](scripts/) | 部署配置、备份恢复和操作工具 |
| 开发进展 | [RELEASE_CURRENT.md](RELEASE_CURRENT.md) | 当前实施范围及待完成事项 |

**B1.2＋B1.3 已实现：电话接待与统一诊疗资源协同。** 前台办理咨询、建档、联系待办、患者同意与唯一成约；电话、网站、改期和候补共同核对服务时长、科室、医师、椅位及必要设备。维修保留原约，支持明确的兼容替换和到诊资源复核。[业务说明](docs/B12_B13_RECEPTION_RESOURCES.md) · [验收记录](docs/evidence_b12_b13/README.md) · [后续开发](docs/APPOINTMENT_BUSINESS_PLAN.md)。

正式报告共183页，包含90项业务用例及1项共享核验、109张表和55幅图。小程序的32项真实接口／并发、五店客户端联调及网站结果核对见[早期证据](docs/evidence_b15/README.md)。B1.4历史验收包含1046项规则、1345项PostgreSQL／HTTP／并发，以及五店20患者连续30分钟9000请求、p95 0.453秒；其[容量与恢复范围](docs/evidence_b14/README.md)独立保留，不等同于小程序平台、公网或商业化认证。

A Systems Analysis and Design（系统分析与设计）course project, covering dental
clinic operations from appointments through care records, invoicing, operating
reports, waitlists and accountable coordination. Demonstrations use synthetic
data（合成数据）.

The release candidate（发布候选）is **v1.0.0-rc.1**. Development now continues
on **macOS**, on `main`. Tag `v1.0.0-rc.1` preserves the supplied archive, which
contained no Git history or database backup.

## Run on macOS

Install and start Docker Desktop with its local Linux engine. Host Python,
PostgreSQL and Node.js are not needed for the application.

```sh
./RC_MACOS.sh verify
./RC_MACOS.sh prepare
./RC_MACOS.sh new-demo --synthetic-empty-only
./RC_MACOS.sh start
```

`start` builds the current source before stopping the previous runtime, then
prepares the schema and starts the updated services. Demo accounts and data are
retained. The worker supports graceful shutdown（平稳停止）and tested recovery
after termination; see [the process acceptance record](docs/WORKER_PROCESS_ACCEPTANCE.md).

Open **http://127.0.0.1:18000**. Read your generated login credentials locally
from `.rc/private/demo-credentials.txt`. Initialization runs once; normal startup
does not reset accounts or seed data again.

```sh
./RC_MACOS.sh status
./RC_MACOS.sh operations
./RC_MACOS.sh stop
./RC_MACOS.sh start
```

The database is private to Docker. Only the local gateway is exposed, on
loopback（回环地址）. The Web server, notification worker and private operations collector start after
schema preparation. See [the Mac guide](docs/MACOS.md) for troubleshooting and backup
import into a separate empty instance.

## Architecture and behavior

- Django 5.2, Python 3.13, PostgreSQL 17, Gunicorn and Nginx.
- A modular monolith（模块化单体）with seven role workspaces and clinic scope.
- Server-generated request references, safe error pages, allowlisted operational
  logs and measured size rotation; [R2.1 operator guide](docs/R21_SAFE_DIAGNOSTICS.md).
- Separate notification progress, eligible-backlog counts, private incident history and
  independent observation-failure detection; [R2.2 operator guide](docs/R22_OPERATIONS_OBSERVATION.md).
- Clinic payment-channel accounts, versioned cash evidence, private CSV statements
  and independently reviewed one-to-one matching. See
  [the R1 financial evidence contract](docs/FINANCIAL_EVIDENCE_RECONCILIATION.md).
- Care completeness（接诊完整性）, editable own-care drafts, independently reviewed
  receipt/refund requests, current receivables and clinic equipment lifecycle
  management. See [the detailed workflows and role boundaries](docs/CARE_FINANCE_EQUIPMENT_WORKFLOWS.md).
- Role-specific business follow-up（业务跟进）for overdue appointments, unclosed
  care, coordination, patient offers and quarterly financial completeness; see
  [the business improvement record](docs/BUSINESS_FOLLOW_UP.md).
- Explicit appointment confirmation; waitlist suggestions never create bookings.
- Guided rescheduling（预约改期）finds replacement intervals, compares original/new
  arrangements and requires final confirmation. Conflicts preserve the original;
  repeated confirmation returns the existing successor. See
  [the rescheduling workflow and local acceptance](docs/RESCHEDULING_OPTIMIZATION.md).
- Versioned care records and invoices, independent correction review, and clear
  distinctions between billed revenue, cash and missing cost data.
- Availability maintenance, intake control, coordination tasks, audited notices
  and a separate notification worker.
- Guided operations and accessible interfaces; external AI is disabled in tests
  and the demo uses local rule mode.

## Validation and project records

`./RC_MACOS.sh verify` uses a new temporary PostgreSQL database and writes
results under `evidence/verification/`. Latest host-tool regression: [R2.3 independent recovery](docs/evidence_r23/README.md), 1,016 source/rule checks, 1,152 real PostgreSQL/HTTP/concurrency tests and 24 real-age/PG restore success/refusal checks. Full-table restore compared 51 tables and 29,144 rows in 15.868 seconds including startup; transport was locally simulated.

Earlier service/browser execution:
[R2.2 progress/backlog/observer acceptance](docs/evidence_r22/README.md): 978 source checks,
1,145 PostgreSQL/HTTP/concurrency tests, 869 isolated Chrome assertions and 32 runtime fault checks. Previous acceptance is
[R1 financial evidence, 2026-10-15](docs/evidence_financial_evidence/README.md):
908 source checks, 1,106 PostgreSQL/HTTP/concurrency tests, 2,423 isolated browser
assertions and a five-clinic/twenty-account/thirty-minute local workload.
[The current report](docs/report-source/) separates these executed results from
the planned R2 work. Earlier [Mac migration](docs/evidence_macos/) and
[G4 PostgreSQL](docs/evidence_g4/http2-postgresql-gate.json) records retain their
historical scope.

Database regression, browser interaction, backup recovery and public deployment
are separate checks. A public **source repository** does not make the local
application a public deployment. This course demonstrator is still an RC.

G3's two browser business routes（业务验收）and worker recovery have passed on
the Mac synthetic environment. See [the browser acceptance record](docs/G3_BROWSER_ACCEPTANCE.md)
for financial oracles, permission refusals, lost responses and 320/390 CSS-pixel
Chrome checks. G4 is PARTIAL: the temporary read-only Mac demonstration passed
bounded public checks. The next target is the writable course deployment on an
independent Hong Kong server, with a fixed free hostname and verified Mac backups.
See [the course deployment and recovery guide](docs/COURSE_ONLINE.md).
The server has not been purchased; cloud write/reboot/off-host/24-hour acceptance
remains NOT_RUN. Original Windows backup recovery remains unresolved.

- [Release scope and history](RELEASE_CURRENT.md)
- [Two business demonstration routes](docs/DEMO_ROUTES_RC1.md)
- [Current development report: Word, PDF and Markdown](docs/report-source/)
- [R2 operational assurance requirements and acceptance](docs/R2_OPERATIONAL_ASSURANCE_PLAN.md)
- [ASVS 5.0.0 security gap register](docs/SECURITY_ASVS_GAP_REGISTER.md)
- [Historical R5/RC1 course report and UML models](docs/release_report/)
- [Historical Windows instructions](docs/history/README_RC1_WINDOWS.md)
- [Production configuration candidates](deployment/README.md)
- [G4 deployment preparation and required server/domain details](deployment/g4/README.md)

Keep `.env`, `.rc/`, credentials, database dumps and migration bundles private.
The ignored `evidence/` directory contains local run output; packaged historical
synthetic evidence remains tracked to preserve the RC1 archive.

Finance/equipment refinement: pending and projected receipt/refund balances,
source-event fee reconciliation, and explicit maintenance-to-scheduling handoffs
are described in [the workflow guide](docs/FINANCE_EQUIPMENT_HANDOFFS.md).

## Daily reconciliation — 2026-10-15

Clinic managers can prepare four-category daily cash reconciliations with explicit
evidence and discrepancy responsibility. Independent finance review requires equal
gross amounts, no pending cash and current facts. Rejected or reviewed days reopen
as retained new versions; late facts never silently rewrite earlier approvals.
Two additive migrations preserve all previous 23 migrations. See
[Daily reconciliation](docs/DAILY_RECONCILIATION.md) and its executed evidence.
R1 subsequently added payment-channel accounts, evidence and exact statement
matching; internal daily handover remains separate from channel settlement.
Sealed accounting periods, independent cloud deployment and commercial-scale
acceptance remain outstanding work.

## Maintenance responsibility — 2026-10-15

Clinic managers can assign stopped-equipment work orders, follow deadlines, submit
repair evidence and obtain another manager's acceptance. Every action is retained.
Acceptance creates one exact service event; fee posting and scheduling changes
remain explicit separate workflows. Cancelled managed cases cannot bypass review
through the legacy status command. Three additive migrations preserve the prior 25.
See [Maintenance work orders](docs/MAINTENANCE_WORK_ORDERS.md) for role boundaries,
legacy declaration scope, verification and remaining commercial requirements.

Maintenance local acceptance: 884 source / 1,042 PostgreSQL-HTTP-concurrency / 704 browser / 89 independent database assertions. All 45 model and association fingerprints match after an encrypted empty-target restore. See [maintenance evidence](docs/evidence_maintenance/acceptance.json). Cloud/commercial acceptance remains incomplete.

## Next stage — 2026-10-18

R2.1 safe request correlation/logging and R2.2 worker/backlog/observer monitoring
are delivered. R2.3 tools record original creation/download points and independently verified restore receipts, with shared-snapshot full-table facts and historical observation recovery. R2.4 capacity/24-hour/security acceptance remains next. See [the R2.3 contract](docs/R23_RECOVERY_FRESHNESS.md).
[The detailed plan](docs/R2_OPERATIONAL_ASSURANCE_PLAN.md) defines ownership,
failure response and R2-A01–A12. Executed increments remain separate from pending full-R2
observation and service targets, with local and cloud acceptance kept separate.
R3 treatment continuity, R4 resource coordination and R5 measured
twenty-clinic expansion follow in that order.

R2.1 application delivery: [protected Mac record](docs/evidence_r21/delivery.json)
and [updated current report](docs/report-source/README.md). Application commit
`ccdcdcd` passed exact-version CI; 48 durable fingerprints and 70 private files
remain unchanged, with 410 Mac browser assertions.
