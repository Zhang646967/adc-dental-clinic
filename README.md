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
- Explicit appointment confirmation; waitlist suggestions never create bookings.
- Versioned care records and invoices, independent correction review, and clear
  distinctions between billed revenue, cash and missing cost data.
- Availability maintenance, intake control, coordination tasks, audited notices
  and a separate notification worker.
- Guided operations and accessible interfaces; external AI is disabled in tests
  and the demo uses local rule mode.

## Validation and project records

`./RC_MACOS.sh verify` uses a new temporary PostgreSQL database and writes
results under `evidence/verification/`. Current Mac validation is summarized in
[docs/evidence_macos](docs/evidence_macos/) and the latest
[G3 PostgreSQL gate](docs/evidence_g3/postgresql-gate.json).

Database regression, browser interaction, backup recovery and public deployment
are separate checks. A public **source repository** does not make the local
application a public deployment. This course demonstrator is still an RC.

G3's two browser business routes（业务验收）and worker recovery have passed on
the Mac synthetic environment. See [the browser acceptance record](docs/G3_BROWSER_ACCEPTANCE.md)
for financial oracles, permission refusals, lost responses and 320/390 CSS-pixel
Chrome checks. Original Windows backup recovery and public deployment remain open.

- [Release scope and history](RELEASE_CURRENT.md)
- [Two business demonstration routes](docs/DEMO_ROUTES_RC1.md)
- [R5 course report and UML models](docs/release_report/)
- [Historical Windows instructions](docs/history/README_RC1_WINDOWS.md)
- [Production configuration candidates](deployment/README.md)
- [G4 deployment preparation and required server/domain details](deployment/g4/README.md)

Keep `.env`, `.rc/`, credentials, database dumps and migration bundles private.
The ignored `evidence/` directory contains local run output; packaged historical
synthetic evidence remains tracked to preserve the RC1 archive.
