Current development（当前进展）：R2.1 request tracing and safe logs locally verified; R2 operational assurance in progress. [R2.1 contract and evidence](docs/R21_SAFE_DIAGNOSTICS.md) · [Current Word/PDF report](docs/current_report/) · [R2 plan](docs/R2_OPERATIONAL_ASSURANCE_PLAN.md). Synthetic course scope; cloud and commercial-scale acceptance remain incomplete.

# ADC — Dental Clinic Management

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
./RC_MACOS.sh stop
./RC_MACOS.sh start
```

The database is private to Docker. Only the local gateway is exposed, on
loopback（回环地址）. The Web server and notification worker start after schema
preparation. See [the Mac guide](docs/MACOS.md) for troubleshooting and backup
import into a separate empty instance.

## Architecture and behavior

- Django 5.2, Python 3.13, PostgreSQL 17, Gunicorn and Nginx.
- A modular monolith（模块化单体）with seven role workspaces and clinic scope.
- Server-generated request references, safe error pages, allowlisted operational
  logs and measured size rotation; [R2.1 operator guide](docs/R21_SAFE_DIAGNOSTICS.md).
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
results under `evidence/verification/`. Latest local execution:
[R2.1 diagnosis and logging](docs/evidence_r21/README.md). Previous acceptance is
[R1 financial evidence, 2026-10-15](docs/evidence_financial_evidence/README.md):
908 source checks, 1,106 PostgreSQL/HTTP/concurrency tests, 2,423 isolated browser
assertions and a five-clinic/twenty-account/thirty-minute local workload.
[The current report](docs/current_report/) separates these executed results from
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
- [Current development report: Word, PDF and Markdown](docs/current_report/)
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

R2.1 implements safe request correlation and structured operational logs. Next
is R2.2 worker/backlog observation, then separate backup/download/restore freshness.
[The detailed plan](docs/R2_OPERATIONAL_ASSURANCE_PLAN.md) defines ownership,
failure response and R2-A01–A12. R2.1 execution is separate from future R2 monitoring
and service targets, with local and cloud acceptance kept separate.
R3 treatment continuity, R4 resource coordination and R5 measured
twenty-clinic expansion follow in that order.
