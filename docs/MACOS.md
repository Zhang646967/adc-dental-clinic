# 当前本机运行版本 2026-10-21

B1.5.1受控患者接口已随准确提交CI通过的镜像更新，原生工程位于 `clients/wechat/`，使用现有课程患者账号连接 `http://127.0.0.1:18000`。七角色网站、资源目录、未来时段及患者预览已核对。原数据库卷、66组原业务记录、70份私密配置和RC标签保留；无新增表或迁移。

官方离线WXML／WXSS编译发现并修复了一处客户端选择器兼容问题。原生客户端随最终源码同步；后端业务代码与已验证镜像保持一致。开发者工具界面预览、手机微信、体验版及独立云端尚未验收。账号与试用说明留在 `.course-private/b15-20261021/`，公开仓库不包含密码。

[本阶段交付证据](evidence_b15/delivery.json)及[教师试用顺序](COURSE_TEACHER_DELIVERY.md)说明当前范围。以下为以前运行记录，按原版本阅读。

# macOS continuation guide

Logic chain: preserve RC1 → verify PostgreSQL behavior → create a fresh
synthetic demo → continue development on `main`.

Historical documentation, 2026-10-18: [当前课程格式报告](../课程报告/README.md).
The application is now R2.2 progress/backlog observation at `02a9dbc`, retaining R1 financial
evidence. [Mac application delivery](evidence_r22/delivery.json) verifies original data and
configuration. R2.3 independent recovery tools are delivered separately; [R2.4.1 host events](R241_HOST_EVENTS.md) are now delivered; R2.4.2 dependency exercises and UX1 are [delivered](evidence_r242/README.md); equivalent capacity and true 24h/security are next.
The migration instructions and dated evidence below retain their original scope.

## Current B1.4 course update

Patient-owned replacement preserves the original until atomic confirmation; own retained offers, resource claims, reception and cancellation history remain linked. Front desk keeps daily scheduling. All39 migrations are unchanged. Application `428070b` passed exact-commit CI and is installed; [execution and delivery](evidence_b14/README.md) distinguishes the measured workload, exact image and protected local update. Preserve the original instance, database volume, private configuration and RC tag; use the verified encrypted backup before updating.

## Source baseline

Migration was resumed on **2026-10-12**. The supplied
`ADC_engineering_v1.0rc1.zip` has SHA-256:

```text
2c53e25fefbbb512826e67ff02c4553e219c819d7bf8b820c5852a179e2a4292
```

All 1,326 entries in its checksum list matched. The archive contained 1,327
files, including that checksum list, and no `.git` directory. Tag
`v1.0.0-rc.1` is the initial import; subsequent fixes and host support are on
`main`. Historical documents may say Mac migration was paused or real
PostgreSQL tests were not run; those statements describe the original delivery.

The Windows host has been reset. No source-only ZIP can recover its database,
account passwords, settings or unarchived local changes. The current Mac
instance uses newly generated synthetic demo data.

## First run

1. Start Docker Desktop. Its CLI is also located at
   `/Applications/Docker.app/Contents/Resources/bin/docker`; the launcher finds
   this path if `docker` is not on your shell path.
2. In this project directory, run `./RC_MACOS.sh verify`. Preserve the gate JSON,
   logs and cleanup result under `evidence/verification/`.
3. Run `./RC_MACOS.sh prepare` once. This generates a random instance name and
   new secrets under `.rc/`; it refuses an existing configuration.
4. Run `./RC_MACOS.sh new-demo --synthetic-empty-only` once. This refuses an
   existing RC data volume and creates the schema before seeding demo accounts.
5. Run `./RC_MACOS.sh start`, then open http://127.0.0.1:18000. Credentials are
   in `.rc/private/demo-credentials.txt`, readable only by your local account.

Daily commands are `start`, `stop` and `status`. `stop` retains the database
volume. If setup fails after a volume was created, diagnose that instance;
do not repeatedly seed it or delete its volume to hide the error.

After a source update, `start` builds the current checkout before stopping the
previous Web server and worker. If the build fails, the previous runtime is not
stopped. After a successful build, schema preparation runs before the updated
services start. This refreshes the code without reseeding accounts or replacing
the private configuration or data volume.

The notification worker handles normal termination and Ctrl+C at an event
boundary. It finishes or rolls back the current event, admits no further event,
and exits cleanly. Its idle wait responds to a stop request without increasing
the database polling frequency. Compose allows a 30-second stop grace period.
An abrupt termination before commit is recoverable on restart; a lost receipt
after commit is handled by reading stored state, rather than replaying delivery.
See [worker process acceptance](WORKER_PROCESS_ACCEPTANCE.md).
The two bounded G3 browser routes have also passed; see
[browser business acceptance](G3_BROWSER_ACCEPTANCE.md) for the actual results,
repairs, and responsive/keyboard scope.

## Isolation and runtime

The launcher pins an inspected local Docker context（本地上下文）and rejects
remote Docker endpoints. It clears ambient Compose and RC settings, specifies
this project's Compose file and instance name, and never sources `.env`.

`verify` delegates to the existing isolated verification launcher, using a
temporary PostgreSQL database with no host database port or persistent volume.
Normal startup uses `compose.rc.yaml`: DB health → schema/collectstatic/check →
Web and notification worker → loopback Nginx gateway. Only synthetic local
course use is configured.

The gateway also joins a separate bridge whose default host binding is
`127.0.0.1`. A gateway connected only to the internal network did not publish
its requested port on the actual Docker engine. Database, Web, schema and worker
remain exclusively on the internal network. This follows Docker's documented
[frontend/internal-backend networking pattern](https://docs.docker.com/engine/network/).

The first real Mac check exposed an RC1 Django startup error: `EmailField`
forces `strip=True`, so passing `strip=False` raised `TypeError`. The corrected
contact field retains an email input widget and Django's email validator,
without silently trimming input before validation. Regression tests cover valid,
blank, malformed and surrounding-whitespace email input. Existing models and
all 16 application migrations are preserved.

## Development and GitHub

The public repository is named `adc-dental-clinic`. Keep changes on `main`,
preserve the RC1 tag, and rerun isolated validation after application changes.
`.gitattributes` already defines LF for Unix scripts and CRLF for Windows CMD
files. The Windows launcher and archived reports remain available.

Do not commit `.rc`, `.env`, account handover files, backups or real patient
records. Local run evidence is ignored; a concise sanitized validation record
belongs under `docs/evidence_macos/`.

## If a trusted backup is found later

Use a separate clean checkout and a new `prepare` configuration. Place your
own trusted synthetic PostgreSQL custom archive at `.rc/private/source.dump`,
then explicitly run:

```sh
./RC_MACOS.sh import-copy --trusted-synthetic-copy
```

The import restores only into a new empty RC database. It compares the bounded
legacy summaries before and after schema migration and does not seed or reset
accounts. This path has not been exercised with a Windows backup during this
migration, because none was supplied. Independent recovery remains open; G3
browser acceptance is separately recorded and does not imply backup recovery.

## Private operational status — R2.2

Run `./RC_MACOS.sh operations` from this instance. Codes are HEALTHY 0, WARNING 1,
CRITICAL 2 and UNKNOWN 3; inspect individual conditions. A business health check
does not prove worker or backup health. The collector starts with normal Mac startup.
See [the private command/reset guide](R22_OPERATIONS_OBSERVATION.md).

The current report companion is synchronized without rebuilding the accepted
application. A later rebuild changes its source identity: stop the collector and
follow the explicit archive/reset procedure, then require fresh samples. Preserve
known faults; do not copy old observations as current health. Operations files have
a separate encrypted delivery snapshot and are not included automatically in the
existing database-only daily backup. All backup keys/credentials stay private.


R2.3 host backup/restore tools are delivered separately from the R2.2 business image. See [recovery-point states and commands](R23_RECOVERY_FRESHNESS.md) and [delivery evidence](evidence_r23/restore_delivery.json). No independent course-backup receipt is fabricated for the RC demo: missing facts remain UNKNOWN. The existing six service conditions keep their original meaning.


## R2.4.1 private host events

[The host runbook](R241_HOST_EVENTS.md) covers explicit-target collection, independent status, acknowledgement, finite action records and verified closure. The existing Mac host collector is started explicitly; it does not install a new launchd job or publish a monitoring endpoint. Sleep/disconnection and process expiry remain visible gaps. The five existing container identities are retained; Web, notification worker and application observer keep the accepted R2.2 application image. [Executed scope and delivery](evidence_r241/README.md).


## R2.4.2 application and interface update

At the R2.4.2 delivery, application `1977b4b` passes [exact CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39184693082). The protected update rebuilt web/worker/observer and recreated the gateway to load its changed bind-mounted configuration; the original database container/volume and all 70 private configurations remain. Previous host and application observations are encrypted and retained, then new-source observations start UNKNOWN and require fresh success. The new host target is started explicitly; no new scheduled job is installed. [Executed delivery](evidence_r242/delivery.json) · [dependency runbook](R242_DEPENDENCY_DRILLS.md) · [UX1](evidence_ux1/README.md).

For future source changes, preserve old observations and stop the old collector before the explicit `operations_reset --confirm-reset-observations` transition described in the runbook. A normal same-source restart does not justify erasing observation history. Dynamic Docker DNS allows the gateway to recover after an application address change without a gateway reload.


## R2.4.3 equivalent capacity and UX2 delivery

Application `6ac06cb1d49850a7b905c63816b4ee005f8e88bd` passes [exact CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39192905333) and is now the identified arm64 Mac image. New native worklist/form assets are served. Before/after encrypted backups were checked; all48 durable business fingerprints,70 private configurations, original database container/volume and RC tag were preserved. Previous source observations were archived with verified encryption, and the new source starts a fresh observation identity. No load, fault or synthetic business writes target this original instance. [Delivery](evidence_r243/delivery.json) · [capacity scope](evidence_r243/README.md) · [UX2](evidence_ux2/README.md).

Application and documentation revisions remain distinct; report-only fast-forward does not restart the accepted image. R2.4.4 true24h/security and R2.5 cloud still await their own evidence.
