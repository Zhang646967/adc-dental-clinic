# ADC — Dental Clinic Management

**系统分析与设计课程大作业｜张加良｜信管T2401｜8210241102**

📄 **[课程报告 PDF（推荐阅读）](课程报告/课程报告_张加良_8210241102.pdf)** · **[课程报告 Word](课程报告/课程报告_张加良_8210241102.docx)** · [报告说明](课程报告/README.md)

教师查阅顺序：课程报告 → [业务演示路线](docs/DEMO_ROUTES_RC1.md) → [验收记录](docs/README.md#测试与验收)。报告文件名固定；封面日期及 Git 历史标明版本。

## 仓库分类

| 分类 | 入口 | 内容 |
|---|---|---|
| 课程交付 | [课程报告/](课程报告/) | 当前 PDF 和 Word，便于直接下载 |
| 项目文档 | [docs/](docs/README.md) | 业务流程、系统设计、部署运维、验收和历史导航 |
| 系统源码 | [源码结构](docs/README.md#源码与资源) | 按接诊、财务、设备、排班、通知等业务模块组织 |
| 验证 | [tests/](tests/)、[checks/](checks/) | PostgreSQL/业务回归与源代码规则检查 |
| 部署工具 | [deployment/](deployment/)、[scripts/](scripts/) | 部署配置、备份恢复和操作工具 |
| 开发进展 | [RELEASE_CURRENT.md](RELEASE_CURRENT.md) | 当前实施范围及待完成事项 |

Current development（当前进展）：R2.4.3等价容量与UX2已交付Mac。五店二十账号连续30分钟、9,000请求、1,800合法写入，p95 0.3090秒，零意外失败/重复效果/OOM；预约清单、接诊和财务表单已优化。[验收与交付](docs/evidence_r243/README.md) · [页面与浏览器](docs/evidence_ux2/README.md) · [课程报告](课程报告/README.md) · [下一步](docs/R24_ACCEPTANCE_PLAN.md)。真实24小时、安全及公网仍另验。

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
