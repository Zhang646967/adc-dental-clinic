# C1.2 authority contract and ADR

Status: implemented and synthetically delivered locally; see
[executed acceptance](evidence_c12/release.json). This contract and the local
software evidence do not establish real professional qualification.

## ADR-C1-PROFESSIONAL

Keep the seven existing roles. A **clinical reviewer appointment** is a named,
dated clinic responsibility attached to an active dentist account. Technical
governance records the clinic's appointment reference using its existing
password/target-state checks; this does not certify the reviewer or grant chart
access. The software permits a reviewer to decide another person's professional
case only. It rejects the subject account and the case preparer even after a
role switch. A clinic must independently appoint qualified reviewers before
real clinical use. Synthetic appointments are explicitly identified.

The clinic manager prepares a professional case: exact account, clinic and
booking-service scope (or explicit legacy/no-service scope), credential source,
issuer, internal reference, credential interval and requested action interval.
Actions are READ, RECORD and REFER. None grants prescription, dispensing,
financial approval, clinical-copy/export or consent-signing authority. The
reviewer approves/rejects, and may suspend/revoke a prior decision. Renewal uses
a new case; source evidence and prior decisions are retained. Approval requires
the requested interval to fit within the credential interval. Each decision
records actor, operation ID, state/revision and a retained evidence snapshot.

Approval is rechecked at the actual clinical operation: active account and
dentist role, clinic, exact service, action, effective times and decision state.
Role/credential expiry or revocation cannot be bypassed with a saved form.
Ordinary account departure/security suspension continues to invalidate contexts
and, where applicable, credentials; appointments, prior authorship and financial
facts are retained for explicit coordination.

In an explicitly synthetic instance only, a retained **clinic activation** introduces
this control into existing legacy clinical routes. Non-synthetic instances always
require professional authority, including for newly registered clinics without an
activation row; synthetic source decisions cannot authorize their clinical actions.
There is no public switch to turn it back off. Before
activation, protected future/in-progress visits must have current professional
coverage. All new C2 clinical operations always require professional authority.
The existing system remains its documented legacy baseline until activation;
absence of an activation is never commercial clinical qualification. Synthetic
release rehearsal and the final demonstration must activate the selected clinics.

## Module and transaction boundary

The new `clinical` module owns professional decisions, shared-care authority and
the later independent clinical record. `care` retains the existing published
billing record and reviewed financial history. Booking/resource inventory stays
in `scheduling`; no second inventory or duplicate patient identity is introduced.

Professional changes lock participating user rows in primary-key order, then
current workspace and role/reviewer grants, then the authority case. A clinician
locks their account and authority before clinical/appointment records. Suspension
therefore serializes with an in-flight clinical effect. Manager preparation and
review are separately signed previews; replay returns the retained decision,
not a second grant. There is no automatic approval from a directory certificate.

## Controlled shared-care contract

The assigned source clinician needs current REFER authority for the exact visit
and service. A request retains one patient identity, one source visit, an optional
explicitly selected published legacy record, a different receiving clinic and
clinician, a clinical disclosure basis/reference, purpose and expiry. Only the
selected historical version is released; billing amounts and headers are excluded.
No record selected means no historic clinical payload, not automatic access to
the patient's other records. C2 will add its separately versioned clinical facts.

A current destination front desk with the explicit identity-verification duty
confirms the existing complete patient number or records IDENTITY_DISPUTED.
Same names/phones never merge, retarget or authorize records. The case remains
unresolved if an alternative identity needs investigation. The named receiver
explicitly accepts only after this step, with effective READ scope for the exact
destination service. Neither clinic membership nor acceptance widens general
patient selectors. The receiver checks account, role, expiry and current scope
again whenever opening the released record.

The source clinician, source-clinic manager or patient-self can terminate the
disclosure. The manager sees operational codes and status; identity front desk
sees only the minimum identity projection. Neither receives clinical content.
Website and native patient-self controls reuse the same signed decision. An
appointment delegate cannot use these controls or read clinical content.
Withdrawal/revocation retains appointments, prior decisions and the original
published version; it does not retroactively erase already observed information.

Sensitive HTTP reads append actor, role, typed object/ID, fixed purpose, outcome,
request trace and time in a separate private table, including forbidden responses
from workspace authorization. Route metadata is bounded; no URL/query/body,
identity document, medical text or money reference is copied into runtime logs.
This observation append is permitted on a read-only business demonstration;
it never changes appointments, clinical facts or cash. A logging database failure
does not silently return a successful audited response. Administrative SQL owners
and infrastructure/database access are outside this application read-audit scope.

Source metadata and all decision/read history have PostgreSQL retention guards.
The software rechecks current authority under canonical user locks, while read
responses authorize at the request boundary; revocation stops subsequent reads
and cannot recall an already delivered response. Clinical action expiry retains
operational appointment metadata for explicit handover but removes clinical
patient-detail and allergy-list access without another valid assigned-care scope.

Internal design review: seven-role ownership, patient/grant separation, exact
source/service, immutable history, serializable command effects and money
separation were checked against the C1/C2 plan. Qualified professional review,
actual clinical consent policy and real clinical use remain pending.

The candidate migration is additive to the existing 43 files. Observed PostgreSQL
contains80 tables,205 SQL FKs and50 business triggers after44 migrations; the
installed system remains at C1.1 until exact-version protected delivery completes.

Mind map: source evidence → proposed scope → independent professional decision
→ time/action/clinic/service checks → attributable clinical effect → retained history.
