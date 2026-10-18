# R2.2 private notification observation 通知进度与监测失效

Durable notice → database-backed heartbeat → due aggregates → private condition
and incident state → independent reader → responsible human response.

R2.2 implements the worker/backlog and observer-failure increment of
[the R2 contract](R2_OPERATIONAL_ASSURANCE_PLAN.md). It adds **no migrations,
application roles, public monitoring endpoints or autonomous business actions**.
The existing `/operations/` business dashboard retains its original purpose.
Clinical, financial, equipment and grant records retain their owning commands.

## Facts and boundaries

The notification command keeps loop observation, last successful committed
DB-backed loop and last nonempty DELIVERED result separately. An idle successful
SELECT is progress; terminal FAILED/NO_RECIPIENTS results are separate from due
work. Heartbeat failure never repeats or rolls back a committed inbox result.
A configured instance has one heartbeat writer; existing unconfigured verification
workers retain their original behavior. Failed optional heartbeat file/lock I/O
does not block notification processing; the missing/stale observation becomes
visible through the reader. A competing active heartbeat writer is rejected.

The collector uses a PostgreSQL REPEATABLE READ, READ ONLY transaction with local
3-second statement and 300-ms lock limits. It queries aggregate states and due
times, never recipients, patients, task identifiers or payloads. Due means
`PENDING AND next_attempt_at <= database_now`; each due time is
`max(occurred_at, next_attempt_at)`. The oldest age is nonnegative. Future retries
remain pending, and are separately displayed on the existing current-clinic
manager page. Sampling does not retry, mark read or dispatch a notice.

An inbox commit is delivery, not human reading, agreement, clinical work or
payment. Acknowledgement assigns private operator responsibility only. Original
manual manager retry and all independent review remain unchanged.

Mind map: observed loop → successful DB loop → actual delivery; pending → due or
future retry; terminal outcomes → explicit review; monitoring → no business write.

## Collector and independent reader

RC and newly prepared G4 candidates include an `operations` service using the
same identified application image. It samples every 30 seconds in a dedicated
process. The worker owns a 0700/0600 heartbeat volume; the collector mounts it
read-only. The collector owns a separate private monitor volume; Web mounts
that read-only solely for a private operator command. No Docker socket or extra
published port is introduced. Read-only instances expect no notification writer,
but can collect read-only observations.

Each record binds schema, explicit instance, source commit, UTC/monotonic clocks
and Linux boot identity. Worker observations also include a process-run ID and
sequence; stale/regressed/foreign observations cannot establish health. An
unidentified source reports UNKNOWN. Reads are bounded to 512 KiB, reject
symlinks, nonregular/public files, duplicate JSON keys, nonfinite values, bad
checksums and unsupported schemas. Checksums detect corruption; they are **not**
proof of authorship against an operator who owns these files.

`operations_status` reads without querying the database or depending on the
collector being alive. Missing, corrupt, stale (>90 seconds), foreign or
clock-inconsistent collector state returns UNKNOWN/exit 3. It recomputes cached
worker/due age; rereading a file does not make the observation fresh.

| Condition | Rule | Recovery |
|---|---|---|
| Database/internal Web | First failed sample UNKNOWN; second CRITICAL | Two new good samples |
| Worker while writable | Stopped/failed phase or success/observation older than 90 seconds is CRITICAL; invalid/missing is UNKNOWN | Two new good samples; empty successful loops count |
| Due backlog | Oldest eligible due age >120 seconds is WARNING | Two samples without overdue eligible work |
| Terminal FAILED | Nonzero aggregate is WARNING; never auto-retry | Existing authorized workflow resolves it, then two good samples |
| Runtime-volume space | WARNING below 20%, CRITICAL below 10% or 1 GiB free | Hysteresis: critical persists through 15%/1.25 GiB; warning through 25%; then two good samples |
| Observer validity | Independent reader returns UNKNOWN for invalid/stale state | Fresh validated observations; no business repair implied |

Overall status is the highest numeric condition code: HEALTHY 0, WARNING 1,
CRITICAL 2, UNKNOWN 3. Thus a known critical dependency and an unobservable queue
can produce overall UNKNOWN; the separate dependency condition and incident
remain visible. An entirely invalid/stale observation returns only a safe
UNKNOWN result, never stale aggregates presented as current.

Mind map: fresh identity + bounded sample → six separate conditions → overall
code; observer cannot prove its own continued availability → independent reader.

## Incident state and private operation

One active incident exists per condition. Unchanged samples do not add lifecycle
entries. Opening, severity change, explicit acknowledgement and recovery are
retained; acknowledgement does not change the condition, refresh its sample or
reset recovery counters. Replaying a sample cannot count toward recovery.

The state file is replaced atomically after a checked write/fsync. It retains
at most 128 incidents, pruning recovered incidents only, and at most 16 changes
per incident (opening retained, pruned counts explicit). This is bounded private
technical history, **not** immutable financial audit. Explicit observation reset
retains up to three prior bounded files and starts UNKNOWN. After source/read-only
identity changes, reset is an explicit maintenance action; a foreign observation
is never silently accepted.

For the existing Mac use `./RC_MACOS.sh operations`. For a reviewed writable G4
candidate use `scripts/g4_course.py ... operations-status`. These commands return
the condition code, including nonzero WARNING/CRITICAL/UNKNOWN; they do not deploy.
With explicit private Compose access, on the `operations` service:

```text
python manage.py operations_status
python manage.py operations_ack <incident-id> --operator-code course_operator
```

Use a private maintenance code, not contact/patient details. Stop the collector
before an explicit source transition or damaged-observation reset; run a one-off
`operations` container using the reviewed image and the same operational volumes:

```text
python manage.py operations_reset --confirm-reset-observations
```

Restart the collector and require new valid samples. Preserve prior archives and
investigate the cause. No command above changes business data or erases financial
audit. Do not reset simply to hide a known unresolved fault.

## Failure response and release scope

- Worker stale: inspect the private process/result codes and database readiness;
  restart only the identified service. Check retained outbox/inbox facts; never
  replay a task or financial command to repair a notification.
- Overdue or terminal failure: distinguish scheduled backoff and eligible work;
  use the original current-clinic manager workflow when manual retry is allowed.
- Database/Web unavailable: report the dependency condition; do not replace an
  unknown backlog by zero or infer that an interrupted money request failed.
- Observer missing/corrupt/foreign: the independent reader reports UNKNOWN. Keep
  private evidence; correct the configured identity or explicitly reset only
  after investigation. Continuous external alerting is not installed.
- Space pressure: free/extend the identified runtime storage through controlled
  maintenance. Tests simulate low space; no real Mac-disk filling is performed.

Runtime space measures the Docker Linux filesystem containing the monitor
volume, not all Mac disks. Continuous host-side Docker OOM/restart collection,
external escalation, backup-freshness receipts, strict time-based log expiry,
protected independent log collection, 30-minute equivalent capacity repetition
and 24-hour observation remain later R2 work. Operational volumes persist across
service recreation and are protected separately during release; they are not
silently claimed to be part of the existing database-only daily backup. R2.3
will complete the separate creation/download/restore-freshness contract.

[Executed R2.2 evidence](evidence_r22/README.md) distinguishes rules, real PostgreSQL,
process failures, browser scope and protected Mac delivery. Existing R1 capacity
and R2.1 acceptance retain their original dates. Cloud acceptance and original
Windows-data recovery remain pending.

Mind map: fault → bounded private evidence → named responsibility → original
business operation when needed → two fresh good samples → retained recovery;
full R2, external hosting and commercial readiness → separate gates.

Primary mechanisms: [PostgreSQL read-only transactions](https://www.postgresql.org/docs/17/sql-set-transaction.html),
[Django Greatest](https://docs.djangoproject.com/en/5.2/ref/models/database-functions/#greatest),
[Python atomic file operations](https://docs.python.org/3.13/library/os.html#os.replace).
