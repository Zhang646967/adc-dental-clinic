# Commercial development roadmap 商用化开发路线

Business integrity → accountable daily operations → independent infrastructure
→ measured scale → controlled commercial pilot. The present system is a synthetic
course demonstrator with useful business controls. This roadmap advances the same
codebase without treating a new feature or version number as commercial approval.

The user's 2026-10-14 direction supersedes the historical RC feature freeze for new
work on `main`; the original RC tag and historical acceptance records remain intact.
Requirements, design choices and executed evidence stay distinct, following the
uploaded requirements/design note. The agreed target is one dental chain with
approximately 5–20 clinics. Data volume, support model and service commitments
still require validation before commercial sizing; the rows below are ordered
engineering stages. The [current report](current_report/README.md) records the
delivered R1 baseline and the next [R2 plan](R2_OPERATIONAL_ASSURANCE_PLAN.md).

## Delivery stages 交付阶段

| Stage | Concrete business problem | Work and completion gate | Current state |
|---|---|---|---|
| 1 Financial source integrity | Missing/incorrect equipment costs cannot be resolved without falsifying history | Independently reviewed supplementation, cash reversal prerequisites, immutable original and source linkage; PG/concurrency, browser and independent restore | Delivered previously; retained evidence linked below |
| 2 Daily finance operations | Staff cannot hand over a reconciled day or explain differences by payment method | Receipt evidence/payment channels, cutoff/timezone, preparer/reviewer responsibilities, daily-close versions, discrepancies and explicit reopening; retain bill/cash separation | R1 accounts/evidence/private statement matching delivered with independent review; unsupported allocations and sealed periods remain future work |
| 3 Maintenance responsibility | Device dates/state alone do not allocate ownership or document a maintenance case | Owner/deadline, repair evidence, independent clinic-manager acceptance, retained history and exact service-event/fee linkage; explicit scheduling coordination | Locally verified and delivered with retained evidence; external vendors, parts and mandatory enrolment remain planned |
| 4 Independent operation | Mac sleep/disconnection prevents reliable service and off-site backup download | R2 safe diagnosis, worker/backup observation and fault exercises; then separate HTTPS host, reboot/recovery and actual access tests | R2.1 diagnosis/logging locally verified; R2.2 and full R2 acceptance pending. Server not purchased; cloud NOT_RUN |
| 5 Scale and isolation | Local course samples cannot establish large-clinic/chain capacity | Define representative histories; measure queries, indexes, locks, mixed valid writes, resources and recovery; test every scope under load | R1 five-clinic/twenty-account/30-minute local baseline passed; twenty-clinic expansion and commercial sizing remain future gates |
| 6 Controlled commercial pilot | Actual operational use has different identity, funds, privacy and support obligations | Confirm product and customer boundaries; establish access review, audit retention/export, incident ownership, release/rollback and applicable professional review; integrate external systems only with separately tested contracts | Not approved for real patient or payment data |

Stage 2 now has an explicit [daily-close contract](DAILY_RECONCILIATION.md): four
approved gross amounts, occurrence date in Asia/Shanghai, preparer responsibility,
independent review and retained reopening. Late facts trigger a changed-snapshot
warning. R1 adds [payment-channel evidence and exact statement matching](FINANCIAL_EVIDENCE_RECONCILIATION.md),
preserving internal handover as a separate status. Real channel APIs, split/combined
settlements and sealed periods remain future contracts.
Stage 3 now defines [maintenance responsibility](MAINTENANCE_WORK_ORDERS.md), repair
evidence and independent acceptance; fee posting and scheduling changes keep their
own explicit commands. Existing simple declarations remain distinct from managed
repair cases.

The current database represents one clinic chain. Clinic scope is not independent
customer/tenant isolation. Selling a multi-tenant service requires a separate
isolation model, migrations, complete authorization review and cross-tenant tests.
There is no measured justification yet for splitting this transactional application
into services. Preserve aggregate locks and evidence while measuring bottlenecks.

Mind map:

- Business → source truth → daily reconciliation → exceptions → accountable handover.
- Devices → work orders → actual repair → fee evidence → explicit scheduling decisions.
- Identity → seven active roles → clinic boundaries → access review → separate tenant design.
- Operations → independent host → HTTPS → worker/restart → monitoring → incident owner.
- Recovery → encrypted source/config backups → verified off-host download → empty-target restore.
- Scale → representative workload/data → latency/errors/duplicates/locks → resource headroom.
- Pilot → agreed product boundary → professional review → customer acceptance → controlled release.

## Evidence and release limits 验证与上线边界

For every increment, retain original migrations/history, run source and real
PostgreSQL/HTTP/concurrency checks, exercise changed user workflows in a real
browser, independently verify money/source facts, and rehearse encrypted recovery
before updating the Mac. Record the exact tested commit and obtain passing GitHub
CI. A failed attempt is retained and described separately from its corrected run.

The agreed cloud-course gate remains the existing 10-user, 30-minute, five-request/
second, 80% read/20% valid write scenario, with no unexpected failures/duplicates/
OOM and p95 below five seconds, plus the other cloud/recovery requirements in
[Course online release](COURSE_ONLINE.md). Passing that gate would support the
course scenario only. Commercial load targets must follow the agreed usage model.

Synthetic accounts/data and disabled external AI remain the execution boundary.
There is no external payment/bank, tax-invoice, procurement/payable, depreciation
or commercial service-level claim. The off-host recovery point remains the last
verified Mac download; a sleeping Mac does not provide continuous off-site backup.
Original Windows-data recovery remains unresolved. Purchase, public release and
real-data onboarding are separate decisions and have not occurred.

Current application increment: [R1 payment evidence](FINANCIAL_EVIDENCE_RECONCILIATION.md).
Current local execution: [R1 acceptance](evidence_financial_evidence/README.md),
2026-10-15 at `6a06f35`. Current operational increment: [R2.1 safe diagnosis](R21_SAFE_DIAGNOSTICS.md),
locally verified 2026-10-18; next is R2.2 observation.
Earlier [equipment supplementation](EQUIPMENT_COST_AMENDMENTS.md) and
`evidence_commercial_foundation/acceptance.json` retain their historical scope.
Historical care/finance/equipment and G3/G4 results retain their original scope.

Daily-operation increment: [Daily reconciliation and handover](DAILY_RECONCILIATION.md).

Maintenance increment: [Work orders and acceptance](MAINTENANCE_WORK_ORDERS.md).

Multi-clinic increment: [Capacity and permission scope](MULTICLINIC_CAPACITY.md).

The agreed next sequence and reference capabilities are in
[Mature systems study](MATURE_SYSTEM_STUDY.md). R1 implements
[payment evidence and transaction reconciliation](FINANCIAL_EVIDENCE_RECONCILIATION.md),
retaining independent posting review, synthetic CSV input and separate internal
daily handover versus channel matching. R2 now has a detailed implementation plan
and [versioned security gap register](SECURITY_ASVS_GAP_REGISTER.md); R2.1 now has [safe diagnosis and executed evidence](R21_SAFE_DIAGNOSTICS.md).
R2.2 and complete R2 acceptance remain pending. R3–R5 remain the ordered roadmap.
