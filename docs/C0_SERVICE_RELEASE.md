# C0 patient services: implementation and release record

Historical source-slice record. Subsequent executed local acceptance and protected installation are documented in [C0.3](C03_RELEASE_ACCEPTANCE.md); the original limits below retain their original date.

Patient need → understandable service → clinic/team and fee terms → available time → explicit booking.

Record date: 2026-10-22, America/Los_Angeles. Source implementation continues from
`e41753d065b7317da3e900b24ab51f4b473c4997`. This is an implemented source candidate,
not an installed or clinically qualified commercial release.

## What a patient can do in this source version

The root and legacy `/start/` open the customer homepage. Eight guides explain
initial assessment, cleaning/gum care, tooth pain/restoration, children's visits,
orthodontic consultation, missing-tooth consultation, follow-up and imaging-related
assessment. Guides explain what to discuss; they do not declare that a clinic
offers those treatments. Actual offerings come from complete published clinic
service descriptions linked to existing `BookingService` records.

Each offering describes its purpose, suitable needs, this appointment's contents,
exclusions, preparation and fee terms. Fees distinguish assessment-dependent,
fixed and starting prices; missing amounts are never converted to zero. Displayed
amounts are information, not a billed treatment, charge or payment receipt.
Only clinician names are projected publicly; home/contact details, qualification
notes and patient records are not displayed. No credentials or clinical approvals
are invented.

Patients continue from a service into the existing booking commands. Date left
blank searches chronologically through the existing 14-day horizon, bounded to
80 displayed choices. Clinician preferences must belong to the selected service.
The confirmation form accepts an optional 500-character visit reason, retained in
the own-patient appointment and the existing authorized reception/clinical view.
Duplicate confirmation returns the stored result without overwriting the original
reason. No reason is added to audit summaries, browser storage or external AI.

Service choice survives ordinary login and an explicit multi-role selection.
The short-lived signed navigation payload binds user, login workspace and typed
service ID; it cannot select a role, clinic or URL. Normal activation and current
patient authorization happen first. Staff-role selection discards the hint;
another login clears it; expiry, revocation and service retirement return to the
ordinary destination. A currently active patient can continue through the login
link without another password prompt. That GET only reads an existing context.

Children's service descriptions can be published, but guardian/delegate access
is still a C1 requirement. Their online call to action directs the person to
front-desk verification; the self-booking filter excludes that category.

## Clinic-owned content workflow

The current-clinic manager's **患者服务内容** workspace lists each existing booking
service and shows missing descriptions, incomplete content, drafts, published
offerings and offerings hidden by inactive receiving configuration. It gives
editable templates and an authorized draft preview; preview cannot accept a
booking. Another clinic, a patient or an assigned-but-inactive manager role
cannot use that workspace or preview.

1. Configure the clinic's actual booking service, duration, receiving clinicians,
   opening hours and resources through the established catalogue workflow.
2. Create its patient description. Use a template as a draft starting point;
   replace it with the clinic's actual scope, preparation and fee information.
   Preview and check the customer wording.
3. Explicitly select publication, preview the change, then confirm. Existing
   clinic scope, workspace signature, CSRF, policy revision, transaction, audit
   action and operation replay protections apply. Withdrawal uses the same
   preview/confirmation workflow. GET never publishes.

Templates do not register a new treatment, add scheduling eligibility, invent a
price or auto-publish. A new installation or an upgraded catalogue can therefore
have no published offerings until its owner has completed this work. Empty states
say so. No migration populates or renames existing business data.

## Routes after installation

| Audience | Route | Behavior |
|---|---|---|
| Public | `/`, `/start/` | Customer service homepage |
| Public | `/services/` | Published service directory and filters |
| Public | `/services/<service_id>/` | Service contents, preparation, fee terms and booking continuation |
| Public | `/care/guides/<category>/` | Educational visit guide and actual matching offerings |
| Public | `/clinics/` | Branch address/contact information for published offerings |
| Patient | `/portal/slots/` | Service-first, own-patient availability query |
| Manager | `/scheduling/service-content/` | Current-clinic content and publication readiness |
| Manager | `/scheduling/service-content/<profile_id>/preview/` | Authorized content preview; no booking |
| Staff | `/workspace/` | Previously named `dashboard` endpoint |

Staff and patient login URLs are unchanged. The portable `START_HERE.html` remains
an engineering handover checklist; ordinary customer pages do not link to that
checklist. The earlier B1.6 public walkthrough design is superseded here. Public
discovery renders without workspace/patient context processors and does not
create or mutate a workspace. Local, synthetic and staging presentation retains
a compact **测试环境** label. Presentation cannot establish production readiness.

## Schema and history

The 39 pre-existing application migrations are byte-for-byte preserved.
`scheduling/0006_servicepresentation` adds one table with a protected one-to-one
reference to the existing booking service. Fee state has a database check;
published completeness is also rechecked by the public read projection.
Reverse migration refuses when descriptions exist. No existing appointment,
claim, clinical version, financial document, patient or account is backfilled.
See [schema delta](database/C0_SERVICE_SCHEMA_DELTA.md). The observed historical
schema snapshot and its six rendered ER views retain their original provenance.

## Evidence and limits

| Check | Result for this source slice |
|---|---|
| Standard-library rule/source suite | **1,090 passed** |
| Focused content, handoff rules and entry checks | **38 passed** |
| Original 39 migrations | Compared with parent Git bytes; unchanged |
| Changed Python syntax / template block nesting | Checked; not a Django template compilation or layout test |
| New catalogue/publishing/handoff Django cases | 41 authored; **not executed** |
| Updated public-entry Django cases | 5 authored; **not executed** |
| Django system check / migration drift / PostgreSQL migration and full regression | **Not executed** |
| Actual browser, 390px, keyboard and non-JS customer journeys | **Not executed for the new version** |
| Local running-instance update | **Not performed** |

The execution environment can edit this checkout and run the standard-library
suite. It cannot connect to the local Docker Unix socket. The host has no Django;
installing the pinned dependencies in an isolated temporary directory also failed
because PyPI DNS resolution is unavailable. These are environment blockers, not
passing framework/database results. Historical CI results apply to their original
commits, not this source candidate. No old release evidence has been relabeled.

The observed installed source checkout remains `7ee448edc3fef5952c40cfc1202550324aaface0`;
the previous application remains the running baseline on port 18000. The routes
above are target routes after an accepted update, not claims of current availability.

## Complete the executable gate before installation

From a terminal with permission to use this Mac's Docker Desktop, in the exact
candidate checkout, run:

```sh
./RC_MACOS.sh verify
```

This existing runner uses a uniquely named isolated Compose project, a disposable
PostgreSQL 17 database, no application `.env`, no published database ports and no
running-instance volume. It checks source integrity, rules, Django checks, migration
drift, migrations and the complete real test suite. Logs/results go to the ignored
`evidence/verification/` directory. Keep the exact source commit with its result.
Do not replace this gate with SQLite or migrate the original instance to test it.

After that gate passes, rehearse upgrading a protected copy of the old database
and compare the old business/configuration fingerprints; add the new table to
the current metadata comparison without rewriting historical observations. Then
verify customer and manager paths in the real browser, including negative cases,
mobile width, keyboard and script-disabled operation. Install the identified
image only after those checks and a verified encrypted recovery point; preserve
the original database identity and private configurations. Do not reverse through
populated new content or discard new writes to make rollback appear successful.

This slice implements service discovery and publication. Full clinical records,
prescribing/pharmacy, guardian authorization, professional qualification review,
production initialization and the other V2 acceptance requirements remain in the
[commercial master plan](COMMERCIAL_V2_MASTER_PLAN.md) and backlog.
