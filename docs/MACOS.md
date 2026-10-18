# macOS continuation guide

Logic chain: preserve RC1 → verify PostgreSQL behavior → create a fresh
synthetic demo → continue development on `main`.

Current documentation, 2026-10-18: [R1 delivery and R2 development report](current_report/README.md).
The application remains the verified R1 financial-evidence baseline; R2 is
planned in [the next-stage contract](R2_OPERATIONAL_ASSURANCE_PLAN.md).
The migration instructions and dated evidence below retain their original scope.

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
