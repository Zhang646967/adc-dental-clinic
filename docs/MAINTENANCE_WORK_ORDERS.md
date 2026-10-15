# Maintenance responsibility and acceptance 设备维护工单

Stop equipment explicitly → assign an accountable manager and deadline → record
repair evidence → another clinic manager accepts → separately reconcile the fee
and any scheduling changes. This increment closes the gap between an equipment
status/date and an accountable, traceable maintenance case.

## Responsibility and workflow 职责与流程

1. A current-clinic **MANAGER** records the existing **送修** action. From that
   equipment's page, select **建立维护工单并分配责任**. Select an active manager
   authorized for this clinic, a deadline and the repair problem. Preview and
   explicitly confirm. One live work order is allowed per equipment asset.
2. Only the assigned manager selects **开始处理**. Any authorized clinic manager
   may explicitly change the owner/deadline with a reason. A reassignment returns
   the work to **待开始**; it does not impersonate the new owner or keep an old
   completion claim. The owner coordinates maintenance; no repair qualification
   or access for outside technicians is implied by their account role.
3. The owner submits the completion fact date, repair/check evidence, known fee or
   unknown fee, optional next service due date, and an explicit acknowledgement
   that scheduling impacts and follow-up were checked. Unknown cost is distinct
   from zero. The equipment remains in maintenance while acceptance is pending.
4. A **different current-clinic MANAGER** reviews the submission and either
   accepts with a reason or returns it for more work. The owner may withdraw a
   pending submission before correcting it. Each submitted fact and every decision
   remain in immutable action history even after the current fields are cleared.
5. Acceptance records one exact SERVICE event and restores the equipment to
   IN_SERVICE in the same audited transaction. The event preserves submitted date,
   fee, next service date and evidence; its recorder is the independent accepting
   manager. Acceptance cannot be repeated to create a second event or undo a later
   equipment change. It is internal operational acceptance, not certification of
   clinical safety, technician competence or regulatory compliance.
6. The accepted event links to the existing fee/source-cost workflows. A manager
   separately requests payment recording; FINANCE independently approves it.
   A posted fee participates in the existing occurrence-date daily reconciliation,
   so an older approved daily snapshot can become stale. No payment is automatic.
7. The existing maintenance-to-scheduling page remains an explicit link. Managers
   select potentially affected slots, inspect their facts, and use the existing
   admission/coordination commands. Work orders do not choose slots, cancel care,
   promise resources or automatically pause/resume booking. The acknowledgement
   records the owner's statement; it is not an automated check of every slot.

Responsibility recovery: an unavailable/revoked owner blocks acceptance. Another
manager can return a pending submission and reassign work. Cancellation requires a
reason and an unsubmitted state; the equipment stays in maintenance. Create a new
work order to continue the same stopped-equipment case, or explicitly retire it.
Once a stopped-equipment event has entered the work-order workflow, cancellation
cannot enable a direct single-person SERVICE action. Both the command and database
consistency checks enforce this rule.

Existing simple equipment declarations remain available for routine in-service
care and previously unmanaged stop events, preserving the course workflow. They
are not presented as independently accepted work orders. Mandatory enrolment of
all maintenance and dedicated technician roles remain separate product decisions.

FINANCE and HQ can read scoped maintenance/fee history; they cannot accept repair
work through this workflow. Front desk, dentist, patient and technical-admin roles
do not gain equipment/work-order access. No new role is introduced.

## Design and traceability 设计与追溯

Following the uploaded course note, observable requirements, design and executed
verification are distinct. These maintenance rules are project business decisions.

| Business requirement | Design | Verification |
|---|---|---|
| A named person owns a stopped-device case | Active clinic manager, date deadline, one live case per asset | Wrong owner/clinic, duplicate case, inactive owner, explicit reassign |
| Submitted repair is independently reviewed | READY state, separate manager acceptance, exact service-event link | Self-review/role switch, returns, withdrawals, unknown/zero fees |
| Failed or repeated commands have one effect | Workspace-signed proposals, operation IDs, ordered user/grant/asset/order locks | Duplicate/concurrent calls, stale source/history, audit rollback |
| Original responsibility and repair facts are retained | Immutable origin plus sequential MaintenanceAction snapshots | SQL rewrite/delete/lineage guards; prior submissions remain readable |
| No bypass through old status commands | Active-case check plus managed-stop acceptance requirement | Stale legacy preview, cancelled-case bypass, deferred SQL consistency |
| Money and scheduling keep their own authority | Existing fee request/review, date-based cash ledger, explicit scheduling link | Exact Decimal money, unchanged slots/visits, late day-close warning |
| Work queues stay usable | 20-row pages, status/owner/overdue filters, joined grant existence | Equal one-row/full-page query counts, invalid filters, seven roles, narrow-screen browser |

Three additive migrations (`equipment.0005`–`equipment.0007`) retain all previous
25 migrations. One current projection and one immutable history table are added.
Acceptance updates the asset, appends its SERVICE event, closes the work order,
appends its action, and writes audit records atomically. Deferred guards require
matching final history and service evidence. Canonical actor/owner user locks
precede workspace/grants, then asset and work-order locks. A database owner can
alter schema/guards; application roles are not a restriction on the DB owner.

Historical action records contain equipment-only evidence and responsibility;
audit summaries contain action IDs/types, not raw statements. GET renders facts
without changing maintenance or cash. Read-only instances reject direct commands.
Old writers must stop before upgrading to the matching code and schema.

Mind map:

- Equipment → explicit stop-use event → one live case → retained source identity.
- Responsibility → active clinic manager → owner → deadline → reassign with reason.
- Work → start → repair facts → cost unknown / zero / positive → schedule statement.
- Review → different manager → return / withdraw / accept → exact SERVICE event.
- Finance → source event → separate expense request → finance review → daily facts.
- Scheduling → explicit impact inspection → admission / coordination commands.
- History → original scope → every action and submission → terminal immutability.
- Recovery → encrypted backup → separate empty database → complete fingerprints.

## Evidence and remaining scope 验证与边界

Executed local results are retained in [acceptance.json](evidence_maintenance/acceptance.json):
884 source checks, 1,042 PostgreSQL/HTTP/concurrency checks (48 new), 704 real-Chrome
assertions, and 89 independent raw-SQL/Decimal assertions. The final named-submitter
constraint was applied additively to the retained rehearsal history; a further complete
repair case passed on that final build. Five work orders retain four accepted repairs
and one cancellation, with 22 action records. A separately encrypted backup restored
into a new empty PostgreSQL17 instance, matching all 45 model/association fingerprints
in 2.075 seconds for this small synthetic dataset; this is not a production restore
time claim. Both unsuccessful query-budget attempts and their fixes are recorded.

Queue reminders, external repair vendors, parts/inventory,
procurement/payables, professional device certification, automatic schedule-resource
allocation and service-level commitments are outside this increment. Existing task
notifications retain their original scope; this increment creates no maintenance
notification outbox. Synthetic data and disabled external AI remain the boundary.

Independent cloud hosting and commercial-scale acceptance remain unfinished;
historical Windows-data recovery remains unresolved. Retained course and historical
results do not establish production or professional-device readiness.
