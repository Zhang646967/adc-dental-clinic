# Worker process acceptance — 2026-10-13

Logic chain: durable task event → stopped worker retains pending work → restart
delivers once → normal termination respects the transaction boundary → an abrupt
termination before commit rolls back → recovery reads the stored outcome.

## Result and implementation

This increment advances the worker portion of G3（运行验收）on macOS. It adds
process-level regression to the existing service, PostgreSQL and concurrency
checks. It does not change business permissions, notification recipients, retry
policy, schema or models.

The watch command now handles SIGTERM and SIGINT by setting a stop flag. The
handler does not acquire a lock, access the database or write logs. The dispatcher
checks that flag before admitting another event and lets the current event's
atomic transaction finish. Idle waiting checks the flag in short sleep slices;
the configured database polling interval is unchanged. Original signal handlers
are restored when the command exits. Compose grants the worker 30 seconds before
forced termination.

Mac startup also builds the current checkout before stopping the previous
runtime. A build failure leaves that runtime running. A successful build is
followed by the existing schema-first startup sequence; there is no new seed,
credential reset, volume removal or automatic notification/task action.

## Real process checks

`tests/test_worker_process.py` runs the actual `scripts/rc_worker.py` entry point
in separate Python processes connected to Django's isolated PostgreSQL test
database. There is no mocked ORM, SQLite substitution or fake signal callback.

| Check | Observed contract |
|---|---|
| Idle termination | SIGTERM returns a clean exit after the worker started |
| Stop, create another event, restart | New pending work is delivered; the old delivery is not replayed |
| SIGTERM during insertion | Current event commits; the next queued event remains unattempted |
| SIGINT during insertion | Ctrl+C follows the same event boundary |
| SIGKILL before commit | Uncommitted delivery rolls back; restart delivers the pending event once |
| Stop before a batch | The pending event retains zero attempts and no inbox rows |
| Read-only wrapper | Exits before Django setup or any database connection |
| Non-course wrapper | Rejects startup before Django setup |

The transaction interruption tests install a temporary **BEFORE INSERT** barrier
only in the disposable test database. A real PostgreSQL advisory lock proves the
child is blocked before COMMIT has been sent. Tests then deliver the signal and
release that lock. They inspect committed outbox/inbox rows and verify that the
worker did not change the task itself. The barrier is removed during cleanup.

This distinction matters: termination after a database commit can lose the
process's receipt without rolling back the committed data. Recovery therefore
checks stored state. These tests do not promise external exactly-once delivery,
human acknowledgement, or rollback of every possible crash timing.

The startup contract test also makes the build fail and checks that no stop,
schema or service-start operation follows that failure.

## Evidence and remaining work

The current machine-readable record is `RC_ACCEPTANCE_RECORD.json`. Detailed
gate evidence for this increment is under `docs/evidence_worker/`; raw local
logs remain in the ignored verification directory. G3 remains partial until
the seven-role browser routes, the two business chains, and accessibility and
stale/cross-clinic/readonly cases have actual browser evidence. No Windows
backup was supplied, and public deployment is a separate G4 gate.

Implementation references:
[Python signal handling](https://docs.python.org/3/library/signal.html),
[Compose stop grace period](https://docs.docker.com/reference/compose-file/services/#stop_grace_period).
These document the mechanisms; the repository's executed tests supply the ADC
results.
