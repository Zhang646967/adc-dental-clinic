# G3 browser business acceptance — 2026-10-13

Logic chain: real browser commands → committed PostgreSQL facts → independent
financial oracles → refusal and accessibility checks → scoped acceptance.

**PASS for the bounded RC1 G3 routes.** This record completes the browser part
of G3; the separate [worker process acceptance](WORKER_PROCESS_ACCEPTANCE.md)
remains valid. It does not approve a stable release or public deployment.

The real Chrome browser used an isolated synthetic course instance on ports
18001/18002, PostgreSQL 17, the actual Django pages, and ordinary role accounts.
The existing Mac demo on port 18000 was preserved. No source-only ZIP was used
to claim recovery of the reset Windows database. No external AI, mail, payment,
or real patient records were used.

## Completed business routes

| Route | Executed behavior and committed result |
|---|---|
| A01–A04 | Register G3-D1 and two qualification-record associations; separately create/link/grant an ordinary doctor account; create a clinic-1 slot and synthetic patient with UNKNOWN allergy information. Directory registration creates no automatic access or availability. |
| A05–A08 | Preview creates no appointment; explicit patient confirmation creates one; duplicate confirmation adds none. Front desk separately confirms arrival. Responsible dentist reviews allergy information, records actual treatment and publishes one logical invoice. `1.125 × 99.99 = 112.49`; the final original version is `2 × 99.99 = 199.98`. |
| A09–A10 | Later price/contact edits leave the published invoice snapshots intact. Switching the requesting doctor to FINANCE cannot self-approve. A different finance account approves the correction: old V1 remains 199.98; current V2 is 99.99 on the same logical invoice. |
| A11–A12 | Missing cost, zero draft and confirmed zero remain distinct. Editing a confirmed cost returns it to draft. Both revenue and cost-only doctors are included. The independent baseline oracle is income 199.98, costs 130.00, profit 69.98, fund 7.00. After correction: income 99.99, profit −30.01, fund withheld. The real downloaded CSV agrees; HQ reads without editing. |
| B01–B02 | Explicit pause preserves the existing appointment and an unexpired offer. New booking/inbound-reschedule requests are refused, including forms opened before pause. The owner explicitly accepts the previously valid offer under its original deadline; result inquiry alone creates nothing. |
| B03–B05 | With the real worker stopped, task/outbox intent commit while inbox delivery is pending. After restart, GET leaves a notice unread; marking read does not claim the task. A separate claim assigns responsibility. A progress declaration changes neither appointments nor consent. |
| B06–B07 | Protected visits prevent submission. Front desk uses the original reschedule commands to preserve predecessor history. The same submitter switching to MANAGER cannot review themself. A prepared approval is rejected after a new booking changes the facts; manager explicitly returns the task, front desk reclaims/reschedules/resubmits, and another account approves fresh facts. |
| B08–B10 | Approval alone leaves source slot #1 active and paused. Separate replacement preserves its ID/original interval/history and creates slot #16, inheriting pause. Explicit resume creates no booking or offer. A fresh, unexpired draft #3 is rejected after pause/resume because intake revision changed. A second actual worker restart preserves all delivered event/grant inbox pairs and business facts. |

Final synthetic facts: one logical invoice with two published versions; task #1
CLOSED at revision 7, submitted by user 11 and reviewed by user 4; original slot
#1 inactive; replacement #16 active and open. All three source appointments were
rescheduled through explicit commands, preserving their predecessors. Additional
negative-test booking #8 was saved once after a deliberately lost response.

## Refusal, recovery and accessibility

- All seven workspaces were entered through normal login/role/clinic selection.
  Noncurrent roles, foreign clinic/other-patient IDs, same-person review, stale
  facts, old tabs and repeated confirmations were refused. A real UI grant
  revocation invalidated two still-open forms without changing their browser
  session; contact and inbox facts remained unchanged.
- Both routes were exercised against the actual read-only deployment. Previously
  prepared cost and slot-resume submissions were refused; all allowlisted
  business rows, billing-header hashes and booking receipts matched before/after.
  The worker exited without dispatch. Normal mode was subsequently restored.
- A loopback test proxy dropped two successful upstream 302 responses: booking
  confirmation and slot resume. Saved facts were queried afterwards. Booking
  produced one new Visit and one receipt; resume changed intake once without
  automatic booking. Chrome attempted a native retry in the booking case; the
  fault harness blocked it before forwarding. This tests a real lost response,
  not a fabricated application success screen.
- Empty candidate/task lists explain what is missing and how to continue.
  Tab reaches the separate preview and final confirmation buttons. Space toggles
  patient consent; Enter opens a preview. Merely navigating or checking consent
  creates no appointment and does not change availability.
- Real Chrome nested browsing contexts measured **320/390 CSS px**, with
  **16/20 px** root text, across all role workspaces and representative pages
  from both routes. No whole-page horizontal overflow, duplicate IDs or unnamed
  visible inputs were found in the final checks; report tables may scroll inside
  their own containers. Large text was activated through the actual UI.

The Chrome extension's top-level size override did not change the measured
viewport, so those attempts were not counted as mobile checks. The local harness
served the live Django response in an exact-width same-origin frame instead.
Only the test proxy relaxes frame-ancestor headers for those frames; the actual
gateway retains its frame protection. This verifies CSS layout and controls in
Chrome, not physical phones, Safari, a screen reader, or touch hardware.

## Repairs exposed by real browser use

1. Care confirmations shared HTML IDs, attaching labels to the wrong checkbox.
   Separate rendered IDs retain native POST names and version checks.
2. Finance member/roster and cost forms shared IDs and ambiguous confirmation
   labels. IDs and action-specific labels are now distinct.
3. Permission refusals lacked a usable recovery path. A neutral, accessible 403
   page now returns to the current workspace without exposing target records.
4. A READY task with no owner action was described as ended. Its authorized
   read projection now distinguishes awaiting independent review from history.
5. Read-only POST refusals were plain text. The same accessible recovery page
   now explains read-only mode while retaining HTTP 403 and the write block.

Eight new PostgreSQL/HTTP regressions cover the browser-exposed form, permission
and task-wording failures. Existing read-only regression assertions also verify
the recovery page. The focused 14-test run passed. Models, all 16 migrations,
authorization decisions, transaction boundaries and business commands are
unchanged. Full isolated validation passed: 814 source checks, 700 PostgreSQL/HTTP tests,
Django checks, no migration drift, and all 16 application migrations preserved.
The verification project and its temporary database were cleaned up successfully.

## Inspectable evidence and limits

[Machine acceptance](evidence_g3/acceptance.json),
[full PostgreSQL gate](evidence_g3/postgresql-gate.json),
[first gate failure and resolution](evidence_g3/first-gate-failure.json),
[browser attempts](evidence_g3/browser-checks.json),
[final PostgreSQL facts](evidence_g3/browser-final-facts.json),
[downloaded quarter CSV](evidence_g3/a12-quarter-export.csv), and
[lost-response events](evidence_g3/lost-response-events.jsonl) contain synthetic
data only. The read-only snapshot helper deliberately excludes credentials,
contact/clinical text, session keys and signed tokens; invoice headers use hashes.

The browser ledger retains first failed attempts. Genuine application defects
and harness text/date-format expectations are classified separately, with their
resolutions and passing rechecks. Counts describe executed cases, not coverage
percentages. Screenshots are observations of actual pages, not fixtures.

**G2 remains NOT_RUN:** no original Windows/v0.7 database backup was supplied.
**G4 remains NOT_RUN:** no target public server/domain was defined. The course
application remains v1.0.0-rc.1; public GitHub source is not public app hosting.
