# Care, cash and equipment workflows（接诊、财务与设备流程）

Arrival → documented care → published bill → independent cash review → retained
equipment and financial facts.

This is the user-requested extension of the course demonstrator. The uploaded
course note on Requirements Specification / Design Specification informs the
separation below: business responsibilities first, implementation and verifiable
criteria second. New business scope is a project decision, not a claim that the
lecture prescribed these particular clinic rules.

## 1. Care and settlement（接诊与结算）

**Actor:** the assigned dentist in the current dentist workspace. Front desk
staff record actual arrival using the existing appointment command.

1. Confirm the correct visit and its actual arrival. A scheduled, cancelled,
   rescheduled or closed visit cannot receive ordinary draft treatment edits.
2. Review the patient's allergy information explicitly. A changed information
   version reopens this check. Unknown information is not treated as no allergy.
3. Save the optional care narrative, limited to 4,000 characters. This is a draft
   fact record; it does not confirm treatments, close the visit or create money.
4. Confirm only treatments actually provided, their standard units and quantities.
   Withdraw a mistaken draft line with a reason. Current catalog prices become
   line snapshots; later catalog edits do not rewrite published history.
5. Review the completion checklist, lines and total. Treated completion requires
   current allergy review and confirmed lines. Untreated closure requires no
   lines, a reason and a zero bill.
6. Explicitly publish once. One logical invoice retains successive published
   versions. Closed-care review shows the published facts and a link to that
   invoice; it does not show an empty draft or a new close form, and it does not
   mistake the absent draft for missing review of the published record.
7. Correct published quantities/prices through the existing separate-request,
   independent-finance-review workflow. Published clinical narratives and
   identity/header snapshots remain unchanged.

The narratives appear only in the assigned dentist's care workspace. Patient
billing pages and finance invoice/review pages do not receive clinical notes.
The checklist checks recording completeness, not clinical safety.

~~~mermaid
flowchart TD
  A["Front desk: actual arrival"] --> B["Dentist: review information"]
  B --> C["Dentist: optional draft note and confirmed actual lines"]
  C --> D{"Completion outcome"}
  D -->|"Treated: current review and lines"| E["Publish treated bill"]
  D -->|"Untreated: no lines and reason"| F["Publish zero bill"]
  E --> G["Retain published facts and unique invoice"]
  F --> G
~~~

Mind-map summary:

- Care: assigned actor → arrival state → current information version.
- Draft: narrative → actual lines → quantities/units/prices → reasoned withdrawal.
- Publication: treated checks or zero untreated closure → one invoice → retained versions.
- Correction: separate request → different reviewer → old facts retained.
- Privacy: dentist narrative stays outside patient bills and finance review.

## 2. Cash and receivables（现金账与应收核对）

**Submission:** current-clinic FRONT_DESK for bill receipts/refunds; current-clinic
MANAGER for recorded equipment fees. **Decision:** a different FINANCE account
with active chain authority. Existing seven roles remain intact.

1. Open the current bill or equipment-event source. Identify the clinic, source,
   fact date and CNY amount. Receipt requests cannot exceed the current unpaid
   balance; refund requests cannot exceed verified net receipts.
2. Preview and explicitly submit a request. Its immutable source, amount, date,
   preparer and explanation are retained. PENDING does not count as money.
3. Finance reviews the source, current balance, amount and explanation using
   another account. Switching roles does not permit self-review.
4. Preview the decision and explicitly confirm. Approval creates the POSTED
   effect; refusal creates REJECTED. Both retain their original facts.
5. Current receivables include bills with no cash requests. They use only the
   current invoice version and posted entries. Historical invoices do not double
   the billed total, and pending requests do not reduce the balance.
6. A later bill correction preserves posted cash. If net receipts exceed the new
   bill, the remaining credit is shown as **待退余额**. Front desk staff submit a
   refund for independent review.
7. For a mistaken posted entry, append an original-amount reversal request.
   Never edit/delete a terminal entry. An expense reversal references its original
   expense; after a fully reversed fee, a new correctly checked request may be
   posted. A source may have only one pending/posted reversal of a normal entry.

Amounts:

| Measure | Meaning |
|---|---|
| Billed revenue（开单收入） | Current published invoice amount; existing quarter policy |
| Net recorded receipts（已审核净收） | Posted receipts minus posted refunds |
| Remaining receivable（待收） | max(current billed amount − net receipts, 0) |
| Refund balance（待退余额） | max(net receipts − current billed amount, 0) |
| Equipment cash expense（设备现金费用） | Posted equipment fees minus their posted reversals |

Equipment cash fees are separate from the existing dentist-quarter cost model.
They are not silently deducted again from quarterly profit. Cash recording is a
synthetic course workflow and does not connect to payment channels, tax invoicing,
bank feeds or external fund transfers.

~~~mermaid
flowchart TD
  S["Front desk or manager: source and fact"] --> P["Preview and confirm request"]
  P --> N["PENDING: no cash effect"]
  N --> R["Different finance account: independent review"]
  R -->|"Approve"| A["POSTED: ledger effect"]
  R -->|"Reject"| X["REJECTED: no cash effect"]
  A --> V["Mistake: append reversal request"]
  V --> N
~~~

Mind-map summary:

- Source: current bill or recorded equipment event → current authorised clinic.
- Request: immutable facts → preview → confirmation → pending.
- Review: different account → fresh grants/source/cursor → approve or reject.
- Reconciliation: current billed vs posted cash → due or refund balance.
- Correction: new entry and retained predecessor → no terminal rewrites.

## 3. Equipment（设备管理）

**Writer:** current-clinic MANAGER. **Readers:** that manager, chain FINANCE and
HQ. Technical and clinical roles do not inherit equipment-writing privileges.

1. Register a unique equipment code, name/category/location, received date and
   optional acquisition cost / next service date. Unknown cost/date and confirmed
   zero cost remain distinct.
2. Preview before registration. Confirming creates the asset plus its initial
   retained event in one transaction; it does not post an acquisition expense.
3. Record maintenance to stop use, completion of service or permanent retirement.
   A service event can describe routine maintenance or a return from repair.
   It records its fact date, optional cost and next service date.
4. Read overdue/unknown service dates and the current state. Event history keeps
   the preceding and resulting state, sequence, recorder and time.
5. Submit a positive known registration/service fee separately for finance review.
   The event itself is not proof of payment.
6. Retired assets remain in the history and cannot be restored by replaying an
   earlier confirmation. Historical fees can still be reconciled.

~~~mermaid
stateDiagram-v2
  [*] --> IN_SERVICE: Register
  IN_SERVICE --> MAINTENANCE: Record repair
  IN_SERVICE --> IN_SERVICE: Record routine service
  MAINTENANCE --> IN_SERVICE: Confirm service completion
  IN_SERVICE --> RETIRED: Record retirement
  MAINTENANCE --> RETIRED: Record retirement
  RETIRED --> [*]
~~~

Equipment status is an operator's management record. It does not certify clinical
readiness or allocate a chair to a visit. Equipment maintenance does not silently
pause/cancel appointments; the manager uses existing availability and coordination
commands when schedule changes are necessary.

This increment does not implement cross-clinic equipment transfer, stock
purchasing, depreciation, connected-device monitoring or editable equipment
identity/cost history. Registered identity fields are retained; this scope avoids
rewriting expense sources already used in financial review.

Mind-map summary:

- Register: unique code → clinic → category/location → optional cost/date.
- Lifecycle: in service ↔ maintenance → retirement → retained events.
- Maintenance: fact date → known/unknown fee → next due date → overdue follow-up.
- Finance handoff: explicit fee request → different reviewer → separate cash effect.
- Control: manager scope → signed proposal → version checks → append-only history.

## Requirement-to-design-to-test trace（需求追踪）

| Requirement | Implementation boundary | Verification |
|---|---|---|
| CFE-01 editable own-care draft | save_clinical_note, existing Visit/version locks | stale, inactive, role, published and privacy tests |
| CFE-02 accurate closed-care review | one snapshot and published-version display | real closed-care browser / HTTP test |
| CFE-03 no pending cash counted as paid | CashEntry source/state projection | exact-cent balances, unpaid invoices and rejection |
| CFE-04 independent finance decisions | signed decision, fresh actor/preparer grants, source locks | same-person refusal, revocation, concurrent review |
| CFE-05 no stale-source posting | current invoice version and monotonic request cursor | correction and competing approval tests |
| CFE-06 no history rewrite | three added tables and four additive migrations | SQL mutation/lineage guards and separate restore |
| CFE-07 clinic equipment lifecycle | manager scope, asset revision, retained EquipmentEvent | cross-clinic refusal, stale/replayed transitions |
| CFE-08 accessible manual operation | native forms and explicit previews | real Chrome at 390 CSS pixels / large text |

The diagrams are small documentation flowcharts and a lifecycle state view, not
formal BPMN/UML interchange. Mermaid is the documentation renderer; the numbered
steps and mind maps are the accessible text fallback. Each figure has one question,
direct actor/state labels and no time/proportion encoding. They are not placed in
the application UI. Semantic edges follow the implemented state transitions;
diagram readers can use the text path on narrow screens.

## Development and delivery controls

All original 16 migrations remain byte-for-byte unchanged. Four additive migrations
create EquipmentAsset, EquipmentEvent and CashEntry plus history/source guards.
The normal Mac updater stops old application writers before migration and starts
the corresponding tested image. Account grants, original business rows, private
configuration and the historical RC tag must be compared and preserved.

Signed previews expire after 15 minutes and bind the user, current workspace and
clinic. Final commands reauthorize inside audited transactions, recheck versions,
share the existing visit/slot lock ordering and use request operation IDs. A
successful retry returns the current saved result rather than reversing later
work. Database owners issuing arbitrary SQL outside the command protocol are
outside the application-wide booking/cash concurrency guarantee.

Existing quarterly income/fund policy, notification-worker scope, historical G3/G4
evidence and unresolved Windows-data recovery stay separate. Cloud course readiness
requires its own target-server acceptance.

Execution evidence for this increment is recorded in
[evidence_care_finance_equipment/acceptance.json](evidence_care_finance_equipment/acceptance.json).

Local execution passed: 884 source checks, 870 PostgreSQL/HTTP/concurrency tests,
198 browser assertions and 31 independent database checks. An encrypted full
backup restored into a separate empty database with all 41 model and association
fingerprints matching. These figures describe executed checks, not coverage
percentages or cloud acceptance.
