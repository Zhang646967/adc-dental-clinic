# Multi-clinic capacity and scope verification 多诊所容量与权限隔离

Business scope → representative history → measured traffic → independent facts
→ recovery → exact-version delivery. This increment tests **one clinic chain**
with five clinics. It does not introduce separate customer tenants or expand any
role's business authority. Synthetic course data and disabled external AI remain
required. Requirements, implementation choices and executed evidence are separate,
following the uploaded requirements/design note and the commercial roadmap.

## Business problem and changes 业务问题与修改

A returning patient can have many historical visits. The old patient-directory
query joined those visits and then removed duplicates. The new query uses
membership in authorized visit-patient sets, retaining origin-clinic access,
legitimate cross-clinic associations and the assigned dentist's patient scope.
It re-reads current grants and the current dentist-account relationship. No
permission is inferred from a visible menu or cached across requests.

A 20-row daily-close page previously queried current cash facts separately for
each row. It now aggregates the **exact authorized clinic/date pairs** in one
bounded query, within the existing repeatable-read snapshot. Empty days still
have explicit zero facts. Receipt, refund, equipment expense and expense reversal
remain separate gross amounts; pending items and revision cursors still affect
staleness. The detail and write commands retain their existing lock protocol.

No new migration, index, business API or table is introduced. All 28 existing
migrations and the original RC tag remain unchanged. An initially evaluated
correlated-existence query was slower for the front desk; retained comparative
measurements led to the final set-membership query.

## Validation model 验证模型

- Five clinics; ten added dentists; 10,004 synthetic patients; 10,505 visits at
  baseline, including 10,000 generated historical no-shows, 500 completed billed
  visits and five editable arrivals. Historical no-shows are fixture data, not
  claims that complete workflows were executed for 10,000 visits.
- Five hundred 100.00 CNY invoices and independently posted receipts; 150 assets;
  five open maintenance orders; 110 independently reviewed daily-close versions.
  These facts are prepared through the existing business commands.
- Twenty distinct measured accounts: five front desk, five assigned dentist,
  five clinic manager, three finance and two headquarters. Patient and technical
  roles are checked separately in the real-browser permission matrix.
- Thirty minutes at five requests per second on average. Twenty users issue a
  simultaneous wave every four seconds. Each wave has 16 reads and four valid
  writes. This is a deliberately bursty arrival model, not a claim of constant
  20-request concurrency or the maximum supported user count.
- Writes alternate across clinic-scoped patient creation and assigned-doctor
  clinical-note saves. Booking, billing, cash review and equipment mutations have
  separate functional/concurrency tests; their entire capacity is not inferred
  from this write mix. A submitted note remains a draft and never creates a bill.
- Web/database/worker/gateway caps total two CPU cores and 1,728 MiB of memory.
  Docker Desktop shares the Mac host; caps do not reproduce an independent 2 GB
  cloud host, its operating-system overhead, public latency or failover.
- HTTP success is insufficient: unique creations, per-clinic placement, exact
  note versions, unchanged historical business facts and independently computed
  financial totals must also match. Resource samples, restarts/OOM and PostgreSQL
  deadlock counters accompany the HTTP results.

The positive-load gate requires no unexpected HTTP failures, dropped arrivals,
duplicate creations or OOM/restarts, and p95 completion within five seconds,
including queue time. Wall-clock and monotonic durations must agree within two
seconds, and the largest offered-request gap must be at most five seconds. This
prevents macOS sleep from producing a false continuous-window pass. Use temporary
idle-sleep prevention for the test; it ends with the test process. Negative
permission probes are reported separately. The
browser probes also run during the load; their additional traffic is identified
separately from the 9,000 scheduled requests.

## Permission contract 权限边界

| Actor | Allowed scope | Required rejection |
|---|---|---|
| Front desk | Current clinic's origin/associated patients, visits and invoice cash requests | Other clinic's unrelated patient, visit, invoice, source or substituted clinic field |
| Dentist | Personally assigned visits and associated patients, including legitimate cross-clinic assignments | Another dentist's care, note mutation or unassociated patient |
| Clinic manager | Current clinic's assets, maintenance, expenses and daily handover | Foreign object IDs and foreign maintenance actions; clinical details |
| Finance | Existing chain-wide financial and equipment responsibilities | Clinical directory, clinical notes and manager-only maintenance writes; own submission review |
| Headquarters | Existing chain-wide operational/financial summaries and equipment reads | Clinical directory, invoice detail and business mutations |
| Patient | Bound patient's portal facts | Another patient's invoice/visit or staff workflows |
| System administrator | Explicit technical account governance | Business data through technical privilege alone |

Role or clinic switching invalidates old signed forms. Revoked grants must take
effect on subsequent requests and at locked write confirmation. One account
cannot combine roles to independently approve its own submission. Legitimate
shared-patient lookup and cross-clinic dentist assignments remain intentional
positive cases, not isolation defects.

## Reproduction and evidence 复现与证据

Use a **new independent synthetic RC checkout**, a fresh project identity and a
loopback port from 18040–18999. Never reuse the live Mac `.rc`, `.env`, database
volume, credentials or the read-only G4 project. The load launcher explicitly
refuses ports 18000 and 18020, remote Docker, mismatched project identities and
unmarked containers.

Prepare with `scripts/rc_config.py prepare --port 18050`, initialize using
`RC_MACOS.sh new-demo --synthetic-empty-only`, and start its matching source image.
In an owner-only Compose override, mark **both web and worker** with
`ADC_CAPACITY_REHEARSAL=<that exact project>` and assign the documented resource
caps. Stop the rehearsal gateway/web/worker before restarting with the override
so the gateway resolves the recreated web container. The database volume remains.
The marker must also match `ADC_RC_INSTANCE`; external AI must remain disabled.

Run `scripts/multiclinic_seed.py --project <project> --synthetic-empty-only` inside
that pinned web container. Capture stdout into a permission-0600 private file:
it is **NDJSON containing generated credentials**. Preserve partial failures;
never reset/reseed a partly prepared database. The last line is the complete
manifest; save it privately as `.rc/private/capacity-actors.json`. The seeder
refuses any existing visits, invoices, cash or equipment and requires the exact
initial synthetic demo footprint.

From the tested source checkout, first use a short preflight and then:

```sh
python3 scripts/multiclinic_load.py \
  --root /absolute/path/to/independent-rehearsal \
  --project adc_rc1_<explicit-project-id> --port 18050 \
  --name capacity-30m --seconds 1800 --rps 5 --arrival-mode waves
```

Use a fresh output name; results are never overwritten. Normal HTTP login,
CSRF, signed clinic/workspace selection and existing commands are mandatory.
There are no automatic retries. Retain private samples and actor credentials
locally; publish only sanitized summaries, source hashes and assertions. Record
resource/DB counters before and after and sample memory during the run. Compare
the database with the expected successful writes before conducting additional
business scenarios. Restore an encrypted backup into a separately created empty
PostgreSQL 17 target and compare every model/association fingerprint.

Executed results are recorded in
[`evidence_multiclinic/acceptance.json`](evidence_multiclinic/acceptance.json).
Historical evidence remains in its original directories. Regression tests cover
authorized-set equivalence, grant/role changes, cross-clinic writes, exact
clinic/date aggregation, staleness and constant query count as a page grows from
one row to twenty. Query instrumentation is a local ORM/read-path measurement;
it is separate from real HTTP latency.

## Delivery boundaries and next stage 交付边界

After local acceptance, synchronize the tested source to GitHub, require passing
CI for that exact commit, then back up and update the Mac. Compare the existing
Mac's business data and private configuration before/after; verify its runtime
source and all seven roles and retain an encrypted final backup.

Independent cloud deployment remains NOT_RUN because the server is not purchased.
Public HTTPS, mainland access, Mac-offline service and 24-hour observation still
need their actual environment. Commercial maximum capacity, customer tenant
isolation, realistic clinical concurrency and real patient/payment onboarding
remain unapproved. Original Windows-data recovery remains unresolved.

Mind map:

- Scope → one chain → five clinics → one active role → current clinic/assigned doctor.
- Data → historical fixture → command-created money/device facts → private credentials.
- Capacity → bounded resources → twenty distinct users → timed waves → latency/errors.
- Correctness → CSRF/context → revoked grants → duplicate replay → exact database facts.
- Optimization → measured before/after → identical visibility → bounded batch queries.
- Recovery → encrypted backup → empty PG17 → all fingerprints → retained source volume.
- Release → complete regressions → exact GitHub CI → Mac backup/update → cloud gates remain.
