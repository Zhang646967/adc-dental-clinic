# Next stage: trustworthy identity and continuous dental care

Clinic contract → verified person and authority → structured encounter → staged care → recall/readiness → measured acceptance.

**下一阶段目标：让同一患者跨多次就诊得到连续、可追溯的服务，让前台知道下一步应由谁、在何时、完成什么。**

Date: 2026-10-23. Research/source baseline: `3d0fb0002e7aa5631f5f12763c2885f85e278dee`. This planning increment follows the [maturity study](research/DENTAL_PRACTICE_STUDY_20261023.md). C1.1 is now implemented with synthetic local evidence in [the C1.1 release record](C11_PATIENT_RELATIONSHIPS.md). C1.2 is also locally delivered in [its executed record](evidence_c12/release.json). C2.1 is locally delivered with exact CI, recovery and protected installation; C2.2–C2.3 are locally delivered with exact CI, capacity, recovery and protected installation; consult [their release record](evidence_c23/release.json); professional and commercial acceptance are separate. It refines C1–C2 in the [master program](COMMERCIAL_V2_MASTER_PLAN.md); it does not replace the C3–C8 clinical and production release gates.

## 1. Outcome, scope and priorities（目标、范围与优先级）

Deliver a synthetic, locally testable journey in which an authorized patient/representative can book; the appropriate professional records findings; a plan spans visits; only actual performed treatment reaches the existing reviewed financial workflow; and unfinished care has an owner and due window. Staff and patient channels must show the same committed facts.

A concrete demonstration follows one synthetic patient from initial examination to an agreed staged plan and a later visit requiring a lab case. Front desk books the next step, sees a delayed case and coordinates a new arrangement with the patient; the dentist records actual completed work; finance reconciles its unique charge source; remaining care stays visible. A separate representative-booking case proves that appointment authority does not grant clinical-consent or chart-reading authority. These are workflow examples; clinical indications and templates require professional review.

Continue one independent deployment per dental chain. The first customer's mainland outpatient service scope and the proposed 5–20-clinic envelope need validation. Keep current adult self-service and all existing appointment/resource/money invariants. Front desk remains responsible for daily scheduling; resource catalogue administration remains with the clinic manager.

Priority is determined by dependency and business harm, not by the number of missing features:

| Priority | Work | Reason |
|---|---|---|
| P0 | Patient subject, representative authority, professional scope, clinical/financial separation | Later clinical data must belong to the correct person and responsible professional |
| P1 | Structured history/chart, multi-visit plan, actual execution, recall and lab readiness | Creates a usable continuing-care workflow and improves everyday coordination |
| Parallel | Clean environments, sensitive-read audit, protected objects, monitoring diagnosis, recovery design | These are needed as the corresponding data and workflows appear |
| Later program gates | Full signing/archive, prescriptions/pharmacy, materials/infection control, provider payments/interfaces, independent hosting/pilot | Required for contracted real clinical replacement; not represented by this local milestone |

Do not add autonomous clinical AI, automated overbooking, a generalized workflow designer, all possible insurance products or distributed services in this increment. Customer-required clinical functions remain in the full program even when outside this next slice.

Mind map: next outcome → {right person, right professional, continuous plan, actual execution, next action} → protected facts and usable worklists.

## 2. Delivery increments（分批实施）

| Increment | Concrete deliverable | Entry / exit condition |
|---|---|---|
| **C1.0 Contracts and ADRs** | Service matrix; actor/action matrix; identity/grant/receipt ADR; encounter/charge ADR; proposed ER and state tables | Define ordinary and exception journeys. Record unconfirmed clinical/local assumptions. Obtain professional review before using the relevant workflow for real care |
| **C1.1 Patient relationships** | Front-desk relationship case; attributable verification; bounded appointment grant; website/native subject selector; grant expiry/revocation | Preserve self-service; no contact-to-access shortcut; revoked/stale/concurrent confirmations cannot produce unauthorized effects |
| **C1.2 Professional/shared-care authority** | Credential source/validity; clinic/service scope; controlled cross-clinic identity/referral request; sensitive-read audit; departure/session handling | No role switch/self-review bypass; no unrestricted chain search; existing seven roles keep their tested scope until explicit new authority exists |
| **C2.1 Clinical workspace** | Reported/reviewed history; structured encounter; tooth/surface/dentition findings; bounded draft saving; clinical worklist | Correct patient/encounter/author/version; unknown facts preserved; clinical reviewer validates the applicable templates and terminology |
| **C2.2 Treatment continuity** | Plan versions and alternatives; accepted/deferred/declined steps; actual execution; next-visit linkage; charging bridge | No charge from an estimate or unperformed step; no lost signed/original facts; retained original invoice history reconciles |
| **C2.3 Recall and readiness** | Clinician-directed due windows; front-desk contact/booking work; lab dispatch/return/acceptance/rework; readiness blockers | Lab delay or unavailable prerequisite produces accountable coordination; an appointment is not cancelled silently; recall closes on the defined actual-care event |

C1.1 can be developed with synthetic relationship-verification evidence. That demonstrates software behavior only. The first clinic must appoint the authorized identity/records and clinical reviewers; the developer does not certify their qualifications.

The internal lab workflow in C2.3 uses explicitly recorded synthetic/manual acknowledgements. Actual supplier exchange remains `INT-01`/C5. Drug-specific work continues to depend on C4 authority/review. Internal lab readiness and non-drug follow-up have no inherent dependency on dispensing, so they should not wait behind the entire pharmacy implementation.

Mind map: contracts → identity → authority → record → plan/execution → recall and readiness; security and operations accompany each step.

## 3. C1.1 implementation contract（首批可执行规格）

### Actors and responsibilities

- Front desk opens a relationship/verification case, records the request and coordinates missing information in the current clinic.
- A specifically authorized identity/records reviewer records the verification result and basis. This authority must be explicitly modeled; a technical administrator or unrelated finance account does not inherit it.
- An authenticated account may act for a patient only through its own existing self-access or a valid, action-scoped grant. Identity relation and login credential are separate.
- Patient/representative screens always name the selected patient and acting capacity. Staff screens preserve the actual acting employee.

### Business rules

1. Distinguish **contact**, **family relationship**, **legal representative/guardian**, **appointment delegate**, **financially responsible person**, and **clinical-consent authority**. They are not interchangeable.
2. A contact or relationship can exist without a login. Verification evidence has source, verifier, time, effective interval and status. Store only the minimum needed; do not put identity documents or patient text in operational logs.
3. Initial delegated capability covers the agreed appointment actions: list authorized appointments, book, reschedule and cancel. Clinical history, documents, consent signing and payment authority are separate later grants.
4. Never bind or merge identities merely because a phone number, name, address, patient number or OpenID matches. Preserve ambiguous candidates for restricted human resolution.
5. Existing `PatientAccess` remains the authoritative adult self-access baseline. Do not reinterpret its one-to-one row as a family membership or impersonate a child account.
6. Every unsafe request binds actor, subject patient, clinic/workspace, action grant, authority revision and operation ID. Confirmation rechecks authority under the shared booking lock protocol.
7. Revocation/expiry prevents new effects and stale-preview confirmation. Already committed appointments remain historical business facts and receive explicit coordination if needed. Replay after revoked authorization must not reveal an otherwise inaccessible patient's result; an authorized replay returns the original current result without recreating it.
8. Selecting another patient invalidates the current form/preview. Draft requests and request identifiers never carry over to another subject.
9. Website and mini-program use the same server operation. Two authorized representatives competing for the same patient/resource do not bypass existing patient and physical-resource constraints.
10. Suspension, verification refusal and missing evidence produce a clear next action for front desk. They do not silently create access or abandon the original appointment.

The applicable rules for minors, changes in legal capacity, adult delegation and separate data-processing versus treatment consent need the clinic's approved policy. The personal-information threshold for children under 14 must not be treated as a universal medical-consent or adulthood rule.

### Required ADR decisions before migration

**ADR-C1-IDENTITY:** keep clinical identity independent of contact/accounts; choose minimal relation/grant tables; define verified-source/effective-time history; specify restricted duplicate-resolution and revocation transactions.

**ADR-C1-RECEIPTS:** current `BookingReceipt.access` references the self-only `PatientAccess`. Specify an additive actor/subject/authority representation for delegated confirmations while preserving every existing receipt. Compare extending receipt authority with a dedicated delegated receipt under one shared command; choose one, document uniqueness/replay/privacy rules and prove existing self-access behavior. Do not create a second booking inventory.

**ADR-C1-PROFESSIONAL:** specify role, action, clinic/service, care relationship, validity and reviewer. Directory qualification records are evidence inputs, not an authorization decision. The first increment must not enable future prescription or clinical-copy authority accidentally.

**ADR-C2-CLINICAL-MONEY:** separate encounter/finding/plan/performed event/document from legacy published financial records. Use a typed, unique charging source; historical clinical notes and bill versions remain readable in their original semantics.

These decisions are bounded design work, not permission to build a universal IAM or workflow engine.

Mind map: relation evidence → verified authority → selected subject → signed intent → locked recheck → one effect; revocation closes new authority while retaining history.

## 4. Domain, ER and state design（领域关系与状态设计）

The [identity proposal](research/identity_concept.svg) and [clinical proposal](research/clinical_concept.svg) are small logical views. Dashed/proposed nodes are not current tables. Cardinalities express the design proposal, not a migration already applied. Their [DOT sources](research/identity_concept.dot) and [relationship explanations](research/MODEL_NOTES.md) are retained.

The original planning baseline was **70 tables, 171 SQL foreign keys, 42 application triggers and 40 migration files** in the C0.3 snapshot. The dated C1.2 baseline was **80 tables,205 SQL foreign keys,50 application triggers and44 migration files**. The C2.2–C2.3 observed candidate now has **101 tables,282 SQL foreign keys,74 application triggers and49 migration files**, preserving all47 prior migration bytes; current installation status is recorded separately. Append new migrations and produce an observed schema diff, regenerated ER/DBML/field catalogues, old-row comparison and independent restore evidence for each schema release. Never alter the observed snapshot merely to make it match a future drawing.

Minimal clinical structure to evaluate in C2:

- `Encounter` identifies an actual clinical interaction; existing `Visit` remains compatible with appointment workflows. Its mapping and creation trigger must be explicit; cancelled bookings do not imply encounters.
- Versioned findings/history retain author, source, observed time, recorded time, tooth/surface or other applicable structured value, and professional review.
- `TreatmentPlan → PlanVersion → PlanStep`; actual `PerformedProcedure` links a step where applicable and an encounter. A step can require several executions. Unplanned care has an attributable reason.
- Consent/signature records link the exact patient/authority, document/procedure and version. The C3 mechanism determines qualified signing; a saved flag does not.
- `RecallEpisode` links the clinical instruction/due window and eventual actual-care result; communication attempts and appointment links remain separate history.
- `LabCase` links patient/plan step, supplier, promised date, appointment dependency and append-only status events. Clinical acceptance differs from parcel receipt.

Use separate state tables for relationship verification, grants, clinical documents, plan decisions, actual execution, recall and laboratory work. Plan acceptance does not complete treatment; treatment completion does not prove cash collection; message delivery does not prove patient agreement.

Mind map: identity/authority → encounter findings → accepted plan → actual procedure → charge; parallel evidence → documents, lab, follow-up, archive.

## 5. Proposed business acceptance（待执行场景）

The original full-program scenarios below retain their proposed scope. The C1.1 and C1.2 software slices have separate executed evidence; later clinical, professional and platform gates remain **NOT_RUN**. The [trace file](research/NEXT_STAGE_TRACEABILITY.json) links them to business problems and existing/new backlog requirements. Apply to at least five synthetic clinics where clinic isolation is relevant.

| ID | Scenario | Required observable result |
|---|---|---|
| NS-01 | Existing adult patient uses website and native client | Existing self-booking/reschedule/cancel and receipt semantics remain intact |
| NS-02 | Contact calls about a child before verification | Reception can continue; no patient login/chart permission appears |
| NS-03 | Verified representative receives appointment-only grant | Only that patient's permitted appointment actions become available |
| NS-04 | Contact/payer tries to view clinical documents | Denied unless separately authorized; no record-content or existence leak outside permitted identity checks |
| NS-05 | Two unrelated patients share a phone/name | No automatic merge or account binding; restricted review preserves both histories |
| NS-06 | Parent switches patient with an old form open | Old preview cannot act on either unintended subject |
| NS-07 | Grant revoked/expired after preview | Confirmation rejected; no new visit/claim; authorized history retained |
| NS-08 | Two representatives confirm overlapping bookings concurrently | Only the permissible effect commits; patient/resource uniqueness holds |
| NS-09 | Response lost after valid confirmation | Authorized retry returns the saved current result; no second booking |
| NS-10 | Patient transfers between clinics | Explicit identity/referral handling; clinic role alone grants no unrestricted cross-clinic chart search |
| NS-11 | Professional credential/scope expires or staff departs | New restricted actions fail; sessions/grants handled; prior authorship remains readable |
| NS-12 | Multi-role user tries self-review or technical role opens a chart | Independent review and clinical object authority remain enforced |
| NS-13 | Patient submits history; professional finds a discrepancy | Reported and reviewed versions both retained; no automatic verified-negative allergy |
| NS-14 | Tooth/dentition/surface entered graphically and by keyboard | Both paths produce the same reviewed structured fact; invalid combinations have actionable feedback |
| NS-15 | Two clinicians edit one encounter or switch patients | Version conflict preserves acknowledged work; no cross-patient text |
| NS-16 | Patient accepts version A, then a plan changes | Version B needs its own decision; A and completed work remain recoverable |
| NS-17 | A multi-visit procedure is only partly performed | Remaining plan stays pending; charge facts reflect actual authorized execution only |
| NS-18 | Clinical amendment after billing | Clinical and financial histories remain distinct; no silent bill rewrite or duplicate charge |
| NS-19 | Recall booked, cancelled, contacted unsuccessfully, then completed | Due responsibility survives cancellation; completion uses the agreed actual-care event |
| NS-20 | Lab return delayed or quality rejected | Readiness blocker and owner visible; original appointment preserved until explicit coordination |
| NS-21 | Resource fault intersects a planned follow-up | Existing replacement/reschedule/cancellation rules apply; plan history and consent do not disappear |
| NS-22 | Website/native patient reads progress; HQ opens reporting | Patient sees authorized released facts; HQ sees permitted aggregates, not notes/contact text |
| NS-23 | Billing preview, duplicate execution-to-charge delivery and refund | One charge source per effect; estimates do not post money; financial review and allocations reconcile |
| NS-24 | Upgrade, dependency failure, backup and empty-target recovery | Old rows/receipts and new relationships/history/files match independent facts; expired authority does not revive |

Scenario families must include keyboard/390px large-text operation and understandable empty, refused, stale and offline-response outcomes. Real professionals must review the relevant clinical scenarios before real clinical use; developer-created synthetic fixtures are not their approval.

Mind map: normal journey + wrong subject + revoked authority + concurrency + partial execution + failed handover + recovery → business invariants.

## 6. Engineering and delivery gates（工程与交付门槛）

For each implemented slice: run affected rule/HTTP tests, real PostgreSQL migrations and concurrency checks, then the full existing regression. Verify the exact implementation commit in CI. Compare website and native effects against independent database facts; distinguish offline compilation, Page-handler HTTP execution, actual WeChat runtime, device and experience release.

For this new multi-visit workload, repeat the five-clinic/twenty-account baseline with a declared operation mix and valid business writes, then add representative clinical drafts, authority changes and follow-up work. Keep old baseline results separate. Start with the retained 30-minute/5-rps/80% read–20% valid-write envelope and ordinary-request p95 under five seconds, zero unexpected failures, duplicate effects or visible OOM. Do not infer 20-clinic capacity from it. The larger proposed commercial envelope needs separately measured history size, active sessions, throughput, attachments and external-dependency behavior.

Before a local schema update: encrypted backup, trusted empty-copy rehearsal, old-record comparison, same-version independent restore, exact CI, then protected update and role-based browser checks. Include nonempty new relationship, plan, consent/history and attachment fixtures when those features exist; a zero-row restore is not their semantic acceptance.

Independent hosting, privileged MFA, sensitive-read/export monitoring, backup freshness, full-service recovery and customer support remain commercial gates. The unreproduced collector incident needs safe stage/category diagnostics and sustained observation; retain historical UNKNOWN intervals rather than treating a fresh healthy sample as proof of continuous operation.

Update the formal course report after actual implementation: business rules/use cases first, then actual ER, state models, interfaces and executed acceptance. Keep future proposals explicitly separate. Implemented local slices update the formal report only after executed gates; future professional and production proposals remain separately labeled.

Mind map: source → exact tests/CI → business facts → observed schema → encrypted recovery → protected installation → attributable professional and target-environment acceptance.

## 7. Immediate work package and outstanding inputs（近期工作包）

C1.1, C1.2 and C2.1 have local delivery records. C2.2–C2.3 complete the plan/actual-charge/recall/lab local software slices; their combined exact-image acceptance and protected delivery passed and are tracked in the current release record. The next commercial package follows C3 consent/document lifecycle; its professional contract must be designed before real clinical use. Wider C1/C2 backlog requirements remain separately tracked.

No server purchase or AppID is needed to design and verify this local synthetic slice. Actual WeChat experience release and cloud operation require those inputs later. Before real clinical replacement, obtain the first clinic/service matrix, authorized professional reviewers, local integration/retention requirements and funded operating responsibilities. Record each dependency with its owner and evidence; do not invent approvals or dates.

The next release should be judged by whether its complete patient journey works and its histories reconcile. Menu count, test count and table count support review but do not establish commercial maturity.
