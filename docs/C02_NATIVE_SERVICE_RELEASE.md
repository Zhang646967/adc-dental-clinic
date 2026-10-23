# C0.2 native service journey — source candidate

Published offering → understood scope and fees → selected service → explicit
confirmation → own appointment and front-desk follow-through.

Record date: 2026-10-22, America/Los_Angeles. The plan was recorded in
[C02_NATIVE_SERVICE_PLAN.md](C02_NATIVE_SERVICE_PLAN.md) before implementation.
Source parent: `05730d88e8d164384c1e5b7083428740255e5aba`.
Status: implemented source; not installed, PostgreSQL-accepted or commercially
qualified. The port-18000 instance remains the earlier baseline.

## Patient-facing change

The native home starts with service discovery. Patients can filter the actual
published offerings by need/search, category and clinic, open a service detail,
read suitability, appointment contents, limitations, preparation, fee terms,
location and current receiving clinicians, and continue with that exact service.
Child offerings remain discoverable but require front-desk verification; they
cannot enter self-booking or new native waitlist registration.

Known zero, starting prices and assessment-dependent unknown fees stay distinct.
Amounts are decimal strings or NULL in the API. Service fees do not create a bill,
payment, treatment or clinical assessment. Only clinician identifiers/names are
projected; no private directory, cost, qualification or patient fields are added
to the service catalogue.

The booking form accepts an optional 500-character visit request. The backend
normalizes and signs it in the preview. Confirmation uses that signed text,
ignores raw replacement fields, and records it in the existing complaint field.
The preview and own appointment show it; the existing rescheduling command
preserves it in the successor. It is not copied into audit summaries, client
persistent storage or an external service. Visit refresh clears cached private
content before a fresh authorized read.

Customer pages use patient/product wording and an accurate compact environment
label from server settings. This changes presentation, not production
initialization, authentication or clinical qualification. Existing assigned
patient login is retained; customer self-registration/recovery remains planned.

## Service and command contracts

- `/api/mini/v1/catalogue/` reuses the website's complete, explicitly published,
  active/operational profile projection. `offerings` includes all published
  categories; `services` includes only self-bookable ones. Active clinics remain
  available as front-desk contacts. `resource_clinics` is a list of integer IDs,
  correcting the former dictionary/number mismatch.
- `/api/mini/v1/services/<id>/` is a PATIENT-only, no-store service detail read.
  Draft/incomplete/retired and absent services share the same not-found response.
- New native candidate, booking-preview and waitlist requests require a published
  self-bookable service. Missing services do not fall back to legacy inventory.
  Stale/cross-clinic/child service hints fail clearly rather than substituting a
  different service. Older server responses fail with ordinary patient guidance.
- Booking and waitlist previews use the existing coherent read-only PostgreSQL
  snapshot helper. Service terms and the signed resource/publication revision
  therefore come from one observation. They do not reserve anything.
- New booking confirmation passes an internal publication guard through the
  shared command. It runs after the established physical locks and before Visit,
  claim and receipt writes. The usual resource snapshot rejects catalogue/fee
  changes, including withdrawal/republication. The flag is not an HTTP input.
- Native waitlist confirmation takes patient then physical locks and rechecks
  the signed publication revision and current eligibility before the existing
  join command. An unpublished or changed offering cannot become a new request.
- Successful booking/waitlist receipts are read before these new-request gates.
  Replay returns the saved result's current state, including later cancellation
  or withdrawal, without overwriting text or reviving the original request.
- Own visit detail projects `reschedule_service` separately. The rescheduling UI
  uses that authorized retained service, including legacy visits, and does not
  depend on public catalogue visibility. The original same-clinic/service,
  permission, resource and unique-successor rules still decide the change.
  Existing offers/history remain readable and actionable under their prior
  promise/ownership rules; publication withdrawal does not cancel care.

No new migration or model is introduced. All 40 current migrations, including
the unexecuted C0 presentation migration, are byte-identical to the source parent.
Clinic/role/CSRF/workspace checks and the shared resource inventory remain in use.
Direct SQL and writers outside the application lock protocol are not certified
by these new application rules.

## Verification record

| Check | Actual result |
|---|---|
| Pure Python rules/source suite | 1,095 passed; includes 5 new projection/privacy contracts |
| Native source, binding, transport checks | 107 passed; 11 registered pages |
| Actual JavaScript Page handlers with mocked API | 23 scenarios passed |
| Python parse / migration preservation | 495 files parsed; all 40 migrations unchanged |
| New Django/PostgreSQL API regressions | 25 authored, not executed |
| Django system check, migration drift/apply and full PG/concurrency suite | Not executed in this environment |
| Current 11-page official WXML/WXSS compiler, IDE/device, browser and keyboard acceptance | Not executed |
| Protected copy upgrade, installed backend/client and commercial clinical qualification | Not executed |

Earlier nine-page offline compiler evidence is historical and does not cover
this eleven-page source. The current compiler binaries are not available here.
Docker socket permission is denied and the host has no Django; the previously
attempted isolated dependency installation failed to resolve PyPI. Those
constraints are retained, not bypassed. Raw local logs are in the separate review
package; exact source hashes and scope are in
[evidence_c02/verification.json](evidence_c02/verification.json).

## Release sequence and next work

Run the identified candidate through the existing isolated `./RC_MACOS.sh verify`
gate in an environment permitted to use Docker/PostgreSQL. It must not reuse the
running project's database, secrets or volumes. That gate is read/rehearsal work,
not a runtime update. Then complete C0's protected-copy migration reconciliation,
ordinary and negative website/native journeys, and official native compilation
and runtime checks. Deploy matching backend and client only after those gates.

Target manual journey: manager publishes reviewed content → patient opens native
service discovery/detail → selects an offering in a non-first clinic → records
a request → confirms → reads the same request in their appointment → manager
withdraws the description → existing appointment can still be read and, where
the original domain rules allow, rescheduled. Also verify drafts, child services,
stale confirmations, fee changes, ownership and receipt replay failure paths.

This source slice closes channel inconsistency. C1 identity/guardian/professional
authority and the clinical record, prescribing, payment, privacy and recovery
requirements remain governed by the commercial master plan. No real clinic
capability, price, professional review or go-live approval is fabricated here.
