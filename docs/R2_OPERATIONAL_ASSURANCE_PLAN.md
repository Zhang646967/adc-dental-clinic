# R2 operational assurance plan 运行保障开发计划

R1 evidence → observable failures → responsible response → verified recovery →
independent hosting. Planning baseline: **2026-10-18**, application commit
`6a06f356a0c4697f5b8afe2736ed62d427512806`. **R2 is IN_PROGRESS. R2.1 request
tracing and safe operational logging are implemented and locally verified** in
[the R2.1 contract](R21_SAFE_DIAGNOSTICS.md) and [executed evidence](evidence_r21/README.md).
Application `ccdcdcd` passed exact-commit CI and [protected Mac delivery](evidence_r21/delivery.json).
R2.2 worker/backlog/observer conditions are also implemented and [delivered on Mac](evidence_r22/README.md)
at `02a9dbc`; the next coding batch is R2.3 recovery freshness.
Remaining full-R2 observation/security and cloud gates are pending.

The target remains one dental chain with approximately 5–20 clinics. The next
release should make failed reception, treatment, settlement, notification and
financial-reconciliation work diagnosable and recoverable. Keep Django,
PostgreSQL and the existing worker as a modular monolith. An operator must be
able to explain what failed and which tested version/data copy can restore it,
without exposing patient or financial evidence in operational logs.

## 1 Verified baseline and remaining business problems

R1 delivered clinic payment accounts, reviewed cash evidence, private CSV imports,
exact one-to-one matches and separate internal handover/channel statuses.
[R1 executed acceptance](evidence_financial_evidence/README.md) records 908 source
checks, 1,106 PostgreSQL/HTTP/concurrency tests and 2,423 browser assertions.
The five-clinic, twenty-account, thirty-minute local run completed 9,000 requests
with zero unexpected failures, p95 0.337 seconds and no duplicate business effects,
OOM, restart or deadlock. Encrypted recovery matched 50 models/associations in a
separate empty database. These are **2026-10-15 observations**, not new R2 tests or
a twenty-clinic/public-host capacity claim.

| R1 source boundary at planning | Existing R1 behavior | Business problem for R2 |
|---|---|---|
| `adc_core/views.py:health` | Checks database connectivity; returns status and application version | A healthy web check does not prove worker progress or backup usability |
| `config/settings/production.py` | Minimal WARNING-level console logging | A failed settlement request lacks a consistent safe correlation record |
| `notifications/management/commands/dispatch_notifications.py` | Aggregate outcomes, bounded retries and graceful stop | No persistent heartbeat or due-backlog freshness signal |
| `scripts/g4_course_observe.py` | Explicit-target bounded resource/HTTPS observation | No continuous incident state or tested alert lifecycle |
| `scripts/g4_course.py` and `scripts/g4_remote.py` | Encrypted backups, checked downloads, separate-target restore | Creation, verified download and verified restoration need separate freshness states |
| Existing business authorization/audit | Current role/clinic, independent review and retained changes | Operational diagnosis must preserve those boundaries |

The uploaded requirements note requires testable observable behavior (note 3,
physical page 5). The design note motivates separation, simplicity and restricted
visibility (note 5, pages 4–5), and operations with information hiding (page 8).
Here, the business modules own money/care state; the operational module owns
diagnostic metadata and condition reporting. Google SRE recommends monitoring
that supports decisions and testing the alert path, not merely collecting data.
[Monitoring](https://sre.google/workbook/monitoring/)

Mind map: business failure → observable symptom → private evidence → named response
→ preserved business rules → measurable recovery.

## 2 Scope and ownership

R2 will add request correlation, safe structured logs, worker/backlog observation,
backup/download/restore receipts, bounded condition evaluation, incident runbooks
and a versioned security gap assessment. Start with private operator commands and
files; no public metrics endpoint or new business REST API is planned. The first
increment requires no business schema migration. Reuse existing atomic business
commands and audit; do not let the monitor change appointments, evidence, money,
grants, notification recipients or approval decisions.

| Responsibility | Owner in the operating process | Permitted information/action |
|---|---|---|
| Diagnose infrastructure and collect evidence | Designated platform operator with private host access | Safe technical metadata; explicit target identity; controlled restart/recovery |
| Coordinate interrupted reception or schedule work | Current-clinic manager/front desk under existing grants | Original authorized workflow; no automatic reassignment |
| Verify receipts, refunds and restored financial facts | Different authorized finance reviewer | Existing financial read/review commands; no balancing entry created by an alert |
| Govern accounts | SYSADMIN in its current workspace | Existing account functions; technical role gains no clinical access |
| Accept release scope | Project owner and course reviewers | Local/cloud gates and recorded limitations |

The platform operator is an operating responsibility, not a new application role.
Private host access and SYSADMIN business permissions are distinct. Actual people
and handover contacts must be assigned before unattended public operation.
No automated email/chat escalation or new recurring desktop task is installed by
this plan.

Mind map: operator → technical diagnosis; clinic staff → workflow recovery;
finance → independent money check; SYSADMIN → account governance; owner → scope.

## 3 Request and logging contract

**R2-01 Request correlation.** Generate an opaque server request ID at request
entry, return it in `X-Request-ID`, and attach it to the corresponding completion
or safe failure event. A client-supplied correlation header cannot select, inject
or overwrite the server ID. A support reference grants no access to a record.
Concurrent requests and exceptions must not inherit another request's context.

**R2-02 Log minimization.** Use a versioned JSON allowlist: UTC time, severity,
service, reviewed application commit, event code, request ID, route name, method,
status, duration and narrowly justified role/clinic metadata. A role/clinic may be
recorded only after the current workspace is validated. Do not log usernames,
patient/staff names, submitted URLs/query strings, raw object paths, request
bodies, CSV bytes/references, treatment notes, passwords, cookies, authorization
headers, proposal/workspace tokens, database connection strings, SQL parameters
or unrestricted exception messages/locals. Use bounded reason/exception codes.
The R2-01/02 event vocabulary must cover successful/failed authentication and
authorization denial without persisting entered login names.

Operational logs explain technical outcomes; immutable business audit remains
the authoritative history of business changes. A logging failure cannot turn a
denial into permission or change a successful transaction's result. A required
business-audit failure must continue to roll back its business command. Generic
failure pages may show the request ID, never internal details. Verify framework,
Gunicorn, gateway and command error paths, not just the new formatter.
[Django logging](https://docs.djangoproject.com/en/5.2/howto/logging/)

**R2-03 Bounded storage.** R2.1 implements Docker `local` size rotation with
10 MiB × 3 files per captured service; database and credential-bootstrap native
capture are disabled. The earlier seven-day maximum was a proposed default;
the native driver has size controls rather than time expiry. R2.1 does not claim
seven-day deletion. A stricter time-retention/export contract remains follow-up
work. Report truncation rather than promise a complete history. Financial audit,
cash evidence, statements and seven/thirty-day encrypted backup retention keep
their existing rules. The R2.1 inventory documents each destination and reduced
native forensic detail. Independent protected collection remains a separate gap.
[Docker log configuration](https://docs.docker.com/engine/logging/configure/)

Mind map: server ID → allowlisted event → safe error → bounded private storage;
business audit → atomic facts and retained history.

## 4 Worker and operational observation contract

**R2-04 Worker progress.** Record loop observation time and last successful
database-backed loop separately from last nonempty delivery. An idle, healthy
worker with no due events must not be reported as stalled because its last
delivery is old. A loop that repeatedly cannot access the database is unhealthy.
Store heartbeat output atomically in private runtime storage with an explicit
instance/source identity; malformed, future-dated or foreign-instance files
cannot establish health.

**R2-05 Due backlog.** Derive aggregate due work from the existing
`NotificationOutbox`: `state=PENDING` and `next_attempt_at <= now`. Define each
row's due time as `max(occurred_at, next_attempt_at)` and oldest due age as
`now - min(due_time)`, bounded below by zero. Future scheduled retries are not due;
DELIVERED, NO_RECIPIENTS and FAILED are separate outcomes. An inbox-row commit is
delivery, not a human read or business agreement. Reuse the due index and do not
read/export recipients or task/patient details for monitoring.

**R2-06 Condition evaluation.** Collect bounded read-only samples every 30 seconds.
Use `HEALTHY`, `WARNING`, `CRITICAL` and `UNKNOWN`; exit codes are
0/1/2/3 respectively (implemented in R2.2). Missing, stale, corrupt or misidentified observations are
UNKNOWN, never healthy. Acknowledgement records who took responsibility but
does not clear an active condition. Deduplicate by target and condition; record
opening, acknowledgement, change and recovery once, without a new notice on every
unchanged sample. Store output under a private 0700 directory and 0600 files.
Do not expose raw diagnostics through `/health/` or business pages.

| Condition or remaining trigger | R2.2 default / remaining plan | Clear/interpretation |
|---|---|---|
| Failed web/database readiness | Two consecutive 30-second samples | Two successful samples; readiness is narrower than complete business correctness |
| Worker loop success stale | Older than 90 seconds while writable worker is required | Two current successful loop observations; read-only worker absence is expected |
| Oldest due notification | Older than 120 seconds | No overdue eligible work for two samples; future retry remains pending |
| Container restart or OOM (PENDING host-side collection) | Planned: any new event | R2.2 inspects engine state during tests only; continuous collection remains R2.4 |
| Monitor sample stale | Older than 90 seconds | Fresh valid sample; no observation is not proof of availability |
| Storage pressure | Warn below 20%; critical below 10% free or 1 GiB free | Recovery above 25% (warning) or 15% and 1.25 GiB (critical); measured volume capacity; no full-disk injection on the Mac |
| Clock/source inconsistency | Foreign identity, invalid stored checksum, or future time beyond 5 minutes | UNKNOWN until corrected and revalidated |

These are initial engineering thresholds to test under the current workload,
not measured customer service commitments. CPU/memory utilization is diagnostic;
do not page on a short CPU spike without a user-visible or exhaustion condition.

Mind map: heartbeat + due queue + readiness + resources + observer freshness →
condition → acknowledgement → sustained recovery, with no business mutation.

## 5 Backup and recovery contract

**R2-07 Separate backup facts.** Report server creation, latest verified Mac
download and latest independent restore independently. Preserve the source
creation timestamp when copying a backup; downloading or checking it again does
not make its recovery point newer. Verification requires archive digest,
provenance, authenticated decryption and internal checks, not just filename/mtime.
The existing current-key check for cached downloads must remain.

Candidate daily thresholds: warn if the latest complete server backup or latest
verified off-host recovery point is older than 26 hours. Show the actual age and
state for each. Mac sleep/disconnection can leave the off-host point stale, and
cannot produce continuous protection. A stale server observation becomes UNKNOWN.
For this course release, perform an independent restore after each deployment
and at least weekly during use; warn when its last accepted source point is over
eight days old. A restore record must bind the restored backup digest and source
commit/image; a successful older restore does not prove a newly downloaded copy.

**R2-08 Recovery invariants.** Retain seven daily server copies and thirty daily
Mac copies using the existing UTC-day policy. Never prune valid old points in
response to a corrupt/incomplete new file. Keep the decryption key on the Mac;
only the public recipient belongs on the server. Recovery requires a distinct
empty database/project with matching application/schema provenance; never
restore over the running Mac or reseed an accepted dataset.

Compare every original business/association row, account, grant, money fact,
evidence version, CSV byte digest, normalized statement and match history.
Binary fields need deterministic content hashes, not memory-address strings.
Record the actual recovered point, source/target identities, elapsed restore
time and differences. Target: within thirty minutes after the replacement
environment is ready. The 2.556-second R1 local restore interval is historical
evidence, not a recovery-time promise for a cloud replacement.

Mind map: created point → downloaded and decrypted point → independently restored
point → actual RPO and measured RTO → retained originals and explicit release.

## 6 Objectives and acceptance measurement

Use a proposed seven-day rolling technical availability objective of 99.5% for
authenticated dynamic requests, excluding static/health traffic. Count server
5xx, gateway timeouts and observed transport failures as unavailable; record
4xx/409/429 separately. This technical ratio does not establish business success:
an unexpected 403 for an authorized workflow fails functional acceptance even
if it is outside the 5xx denominator. No traffic/sample means UNKNOWN, not 100%.
Route names have bounded cardinality; request IDs, patients, references and object
IDs must never become metric labels.

The local regression gate remains zero unexpected statuses, duplicate effects,
unauthorized reads or lost financial facts. Repeat the five-clinic/twenty-account
thirty-minute workload with 80% reads/20% valid writes, bounded CSV/review activity,
normal-request p95 within five seconds, and no OOM/restarts/deadlocks. Record the
logging/monitoring overhead against R1 under equivalent service limits; use an
initial investigation trigger of >10% p95 or >64 MiB web-memory increase, not an
unconditional performance promise. Reproduce before changing a threshold.

| Acceptance ID | Isolated scenario | Required observation |
|---|---|---|
| R2-A01 | Parallel requests, forged request header and exception | Distinct server IDs; no crossed context; safe generic failure |
| R2-A02 | Marker secrets in login, clinical text, CSV, URL/query and failure paths | No marker in any operational sink; bounded encoded events; audit invariant preserved |
| R2-A03 | Idle worker, graceful stop, forced stop before/after commit and restart | Idle stays healthy; stop detected within 120 seconds (90-second freshness plus sampling); no duplicate inbox rows or business actions |
| R2-A04 | Future retry, overdue due row and terminal outcomes | Correct due-age classification and recovery; no false failure for scheduled backoff |
| R2-A05 | Database unavailable; collector stopped/corrupt/foreign sample | Safe 503/condition code; stale/UNKNOWN state; no false healthy result |
| R2-A06 | Simulated low space and rapid log rotation | Bounded storage, actionable incident and recovery; real host disk remains intact |
| R2-A07 | New/cached corrupt backup, wrong key, stale copy and failed download | No newer recovery point or pruning; error visible; previous valid archive retained |
| R2-A08 | Encrypted R1-rich backup to separate empty target | Full content fingerprints, roles and money match; no source mutation; measured RTO |
| R2-A09 | Acknowledged, repeating and recovered fault | One incident lifecycle; acknowledgement does not clear condition; no periodic duplicate alert |
| R2-A10 | Existing seven roles and five-clinic negative probes | Operational features add no patient/invoice/CSV or cross-clinic access |
| R2-A11 | Equivalent mixed load and twenty-four-hour local observation | Complete timing/resource evidence; no hidden observation gap or unresolved critical condition |
| R2-A12 | Exact-commit CI and protected Mac delivery | Passing relevant/full regression, original data/config/tag preserved and verified backups |

All destructive failure injection belongs to an explicitly identified disposable
rehearsal with its own volumes. Preserve failed attempts. No acceptance checkbox
is passed merely because this plan or a test definition exists.

Mind map: outcome definition → normal/adverse cases → independent observations →
functional truth + service indicators → bounded local acceptance.

## 7 Development order and first implementation contract

| Increment | Deliverable | Completion gate | Dependency |
|---|---|---|---|
| R2.1 Safe diagnosis | Request context, JSON event vocabulary, error reference and logging inventory/size rotation | R2-A01/A02/A10 and local runtime/restore evidence passed; exact-commit CI and protected Mac delivery recorded separately | Implemented; see R2.1 evidence |
| R2.2 Worker and condition monitor | Private heartbeat/status collector, due-age calculation and incident state | R2-A03/A04/A05/A09 and low-space portion of A06 passed; [executed evidence](evidence_r22/README.md) | Implemented and delivered; no server required |
| R2.3 Recovery freshness | Separate creation/download/restore receipts and empty-target comparison | R2-A07/A08; current key and original UTC retention rules | R2.2; local simulation first |
| R2.4 Local release | Security gap assessment, fault runbooks, browser/load and 24-hour observation | R2-A10/A11/A12; exact-commit CI and Mac preservation | Earlier increments |
| R2.5 Cloud release | Apply tested version to independent HTTPS host and repeat public gates | Mainland access, Mac offline, reboot/worker, renewal, backups, restore and 24-hour observation | Private server/DNS inputs |

The **next coding batch is R2.3** after protected R2.2 delivery.
R2.1 request/logging and R2.2 progress/backlog/incident contracts are delivered;
their exact controls and evidence remain in their linked contracts. Backup
freshness, external alert delivery and the full R2 observation window remain open.

R2.3 should give each verified creation, download and independent restore its own
private versioned receipt, bound to instance, application version, archive digest
and original backup time. Download time must not replace the recovery point.
Cached/stale/corrupt copies, wrong keys and interrupted downloads cannot advance
freshness or prune the last valid backup. Preserve existing UTC retention and
server/Mac seven/thirty daily-copy rules. Keep keys and configuration payloads
private; use the already-defined R2-A07/A08 isolated adverse and empty-target tests.
No business schema, account grant, external AI or external notification is added
by this recovery increment.

Before runtime changes, back up the existing Mac, require exact-commit CI,
stop old writers where required, and compare original data/configuration after
updating. App changes require controlled build/restart; report-only commits do
not restart services. A changed operational source identity needs the explicit
archive/reset procedure, preserving known incidents and requiring fresh samples.

After R2, preserve the agreed order: **R3 treatment continuity** (versioned plans,
acceptance, actual completion and follow-up), **R4 resource coordination**
(preventive maintenance and chair/room/equipment scheduling), then **R5 measured
twenty-clinic expansion**. Each needs a separate detailed business contract.

Mind map: safe logs → worker/observer → recovery freshness → local fault acceptance
→ independent host → longitudinal care → resources → measured expansion.

## 8 Security assessment and external inputs

The [ASVS gap register](SECURITY_ASVS_GAP_REGISTER.md) pins OWASP ASVS 5.0.0.
Existing authorization tests are supporting evidence, not an ASVS pass. R2
closes its stated logging/operational gaps and records remaining authentication,
session, sensitive-read and log-protection work; no compliance certification or
real-patient commercial release follows automatically.
[Official ASVS](https://owasp.org/projects/asvs)

Cloud deployment still needs the public IPv4, SSH username, local private-key
path, independently verified SSH fingerprint and owned hostname. Keep these,
passwords and DNS tokens private. No server purchase or domain registration is
performed in this increment. Original Windows-data recovery remains unresolved.

Mind map: versioned security requirements → existing evidence → explicit gaps →
new tests; server credentials → private preparation → actual cloud acceptance.

R2.2 implementation details and explicit reset after source transitions are in
[the operations contract](R22_OPERATIONS_OBSERVATION.md). Exit 3 (incomplete/unknown)
can coexist with a known critical condition; inspect each condition, not only the
overall code. Private status uses no database query and never controls business work.
