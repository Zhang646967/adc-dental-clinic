# Commercial V2 inspected baseline

## Current implementation check: 2026-10-24

C1.1–C2.1 have retained local synthetic delivery records. C2.2–C2.3 application `021a2183f52ff2170298134e610aea5d30fe28e7` has passing exact CI (1,104 source rules /1,688 PostgreSQL, HTTP and concurrency cases), five-clinic actual Chrome/native-handler journeys and independently checked treatment/money facts. Combined capacity, populated restoration and protected installation passed and are recorded separately in [the current release](evidence_c23/release.json). Check that record before interpreting source availability as deployment.

| Area | Inspected current capability | Remaining boundary |
|---|---|---|
| Identity and authority | Verified appointment-only relationships, explicit website/native subject, clinic/service/action scope, selected referrals and sensitive-read metadata | Source-aware imports, broader professional roles, actual qualified reviewers and production onboarding |
| Clinical continuity | Actual encounter/history/findings, immutable plan versions and catalogue definitions, self-only step decisions, typed actual execution and original charge snapshots | Qualified signatures/consent/archive, periodontal breadth, prescribing and materials |
| Follow-up and lab | Actual-care completion rules, attributed front-desk contact, explicit appointment links, manual dispatch/return/cycle acceptance and readiness | Real supplier integration and full QC cohort metrics; status counts are not outcome rates |
| Observed schema |49 migrations,101 tables/100 ORM tables,966 ORM columns,282 SQL FKs and74 application triggers;17 ER views | Preserve all47 prior migration bytes and nullable historical unknowns; compare actual installation separately |
| Measured environment | Five synthetic clinics and local exact-image journeys; new clinical 30-minute workload has its own dated result | No20-clinic, independent-cloud,24-hour or real clinical maturity claim |
| Report |80 business cases plus SF-01 and17 actual ER views delivered | Fixed-name Word/PDF render/validation and final installation evidence recorded with release |

The dated audits below remain unchanged historical observations. Their earlier source, table, role and deployment limits do not describe the later implementation automatically.

## Historical audit: 2026-10-23

Inspected source: `3d0fb0002e7aa5631f5f12763c2885f85e278dee`. Read with the [maturity study](research/DENTAL_PRACTICE_STUDY_20261023.md) and [next-stage plan](COMMERCIAL_V2_NEXT_STAGE.md). This audit reads current code and retained evidence; it does not rerun the application tests or certify professional clinical use.

| Area | Current observation | Next-stage implication |
|---|---|---|
| Executed local baseline | C0.3 records application `3b78cc5f430f18411bf50e4314f287b2c95666a0`, passing exact CI with 1,095 rules and 1,474 PG/HTTP/concurrency cases; encrypted restore and protected local update completed | Earlier B1.6/C0/C0.2 deployment/CI gaps below are historical for those dates; this does not complete the broader commercial program |
| Patient channels | Published service catalogue, website/native continuation and appointment workflows; eleven native pages, official offline compilation and handler-to-server checks retained | Actual WeChat runtime/device/experience and cloud remain NOT_RUN; new identity subject selection is planned |
| Identity | `PatientAccess` uses one-to-one user/patient references; `BookingReceipt` refers to self-access; patients are not merged by shared phone | Add reviewed relationships and bounded grants; resolve actor/subject/replay semantics before migration |
| Professional scope | Active role/clinic and assignment checks exist; qualification catalogue association lacks the proposed verified scope/validity lifecycle | Add explicit professional and shared-care authority; technical or manager roles do not inherit clinical access |
| Clinical and financial boundary | `VisitRecordVersion` contains notes/allergy and financial snapshots; `complete_visit` publishes charge lines, creates a bill and closes the visit transactionally | Add clinical encounter/plan/performed facts and a typed charging bridge; retain old records and money without fabricated diagnoses |
| Follow-up and readiness | Cancellation follow-up, front-desk coordination, resource availability and repair workflows work within their scopes | Add clinical recall and internal lab-case readiness; sterile-package/material tracking remains separate work |
| Observed database | 70 tables, 171 SQL foreign keys, 42 triggers, 40 migration files (39 original files retained) | Preserve all 40; future logical models are proposals until additive migrations and observed ER verification |
| Capacity | Retained B1.4: five clinics, twenty accounts, 30 minutes, 9,000 requests at 5 rps; patient rescheduling workload, p95 0.453 s | Historical specific-workload evidence, not twenty-clinic or new clinical workload qualification |
| Sustained operation | C0.3 retained an unreproduced host-collector incident/UNKNOWN gap; short healthy follow-up is recorded | Safe diagnostic detail and sustained observation remain needed; cloud and 24-hour acceptance are separate |
| Formal report | Current report describes implemented baseline: 59 business use cases plus SF-01; actual ER updated | Future clinical cases remain in the planning package until implementation and acceptance |

Sources: [C0.3 execution](evidence_c03/README.md), [database catalogue](database/README.md), [B1.4 capacity](evidence_b14/capacity.json), current `portal`, `patients`, `registry`, `accounts`, `care` and scheduling models/services. Historical Windows-original data recovery remains UNRESOLVED. No new commercial clinical readiness is claimed.

## Historical audit: 2026-10-22

The following rows retain their original inspected version and evidence state. They are not the current deployment status.

Date: 2026-10-22. Inspected local source: `c750e7ebabc6bfa90769570a8468972ae7b94b14`. This audit describes files and retained records; it does not rerun historical tests or certify the running application.

| Area | Inspected source or record | Observation | V2 consequence |
|---|---|---|---|
| Staff entry | `templates/registration/login.html` | Course-project introduction and synthetic-data notice are hard-coded into the normal login | Product/environment design and professional identity replace academic framing in customer routes |
| Staff workspace | `templates/base.html` | Sidebar labels the application as a course/synthetic demonstration | Environment indicator and product identity must be configurable and tied to the correct deployment/data boundary |
| Patient entry/workspace | `templates/portal/login.html`, `templates/portal/base.html` | Distributed credentials, course wording and synthetic/no-actual-payment footer | Verified patient onboarding and accurate production capability/status presentation |
| Developer checklist | `templates/entry/index.html`, `adc_core/entry_catalog.py`, login/shell links | Six-route personal acceptance checklist is linked from normal user pages | Move acceptance tooling into a separately authorized internal path; normal entry serves actual patient/staff tasks |
| Clinical model | `care/models.py` | `VisitRecordVersion` has free-text `clinical_note`, allergy/header snapshots and treatment charge lines; `Invoice` points to a current record version | Design structured dental encounters/documents, plans, signatures, orders and prescription/fulfilment models without rewriting historical billing sources |
| Financial documents | `templates/care/invoice.html` | Correctly distinguishes business settlement, revenue version and receipt/tax-invoice status; includes a hard-coded course disclaimer | Preserve financially accurate status and snapshots; make test provenance appropriate to the actual document/environment |
| Professional authority | `workspaces/rules.py`, `AGENTS.md` | Seven current roles; directory qualifications explicitly do not prove professional authorization | Add reviewed nursing/pharmacy/records authority and professional credential/scope evidence; no automatic permission expansion |
| Production configuration | `config/production_contract.py`, `config/settings/production.py` | Candidate stage/host/runtime-owner separation, secure cookies/HTTPS and 1 h session age exist | Retain controls; add complete release evidence, session governance, MFA/recovery and deployment lifecycle rather than treating configuration as qualification |
| Existing business foundations | `scheduling`, `coordination`, `finance`, `care`, `workspaces`, associated AGENTS rules | Shared locked commands, explicit confirmations, scope, immutable money/history and independent review are existing design foundations | Retain and extend domain boundaries; verify new clinical/financial integration invariants |
| Historical full regression | `docs/evidence_b153/application_ci.json` | Records1,052 rule and 1,402 PostgreSQL/HTTP/concurrency checks for application `72b613e`; stored CI success | Evidence applies to that version and workload, not unimplemented clinical V2 |
| Prior Mac delivery | `docs/evidence_b153/delivery.json` | Records preserved original data/configuration and local delivery; WeChat runtime/device/cloud remain NOT_RUN | Retained historical baseline; new rollout, real data and real external systems need their own acceptance |
| Latest local entry increment | `docs/evidence_b16/validation.json` | 1,060 source checks recorded; 5 authored HTTP tests unexecuted locally, CI upload blocked, Mac update not run | Commercial plan must not imply latest source was deployed or its HTTP/database changes passed |
| Capacity baseline | `docs/evidence_b14/capacity.json` | Five-clinic/twenty-account synthetic workload, 30 min, 9,000 HTTP requests at 5 rps, retained scope | Define a new clinical/user/data/interface workload before claiming commercial capacity |

The source scan covered the active care, portal, account, configuration, template and native-client areas for clinical/professional concepts and user-visible academic wording. An absent item in this audit is a gap in the reviewed implementation evidence, not proof that no historical design text mentions it.

User-confirmed V2 decisions: independent deployment per dental chain; complete clinical replacement including electronic records and prescriptions. Mainland outpatient use and 5–20 branches remain planning assumptions to validate with the first customer.
