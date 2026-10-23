# Dental practice maturity study and ADC development decisions

Evidence → clinic work → product gaps → domain design → staged acceptance.

**研究结论：下一阶段优先建设可信患者身份与连续诊疗闭环，并提前衔接复诊召回、技工件和前台排班。**

Study date: 2026-10-23. Inspected source: `3d0fb0002e7aa5631f5f12763c2885f85e278dee`. The teacher's starting reference is the [Open Dental Quick Manual](https://www.opendental.com/site/quickmanual.html). This is a desk study and a code/evidence audit, not a survey of Chinese clinics or an assessment of a customer's actual clinical practice.

Read this study with the [next-stage plan](../COMMERCIAL_V2_NEXT_STAGE.md), [source register](dental_study_sources.json), [requirement-to-acceptance trace](NEXT_STAGE_TRACEABILITY.json), and [commercial master plan](../COMMERCIAL_V2_MASTER_PLAN.md). Proposed entities and scenarios are **PLANNED**. The current physical ER remains in [database/](../database/README.md).

The [artifact validation record](planning_validation.json) checks trace consistency, local references, proposed diagrams and preservation of the current schema/report files. It is not execution evidence for the proposed clinical functions.

## 1. Decision and research method（结论与方法）

ADC has a useful transactional operating foundation. Its next commercial challenge is continuity: connecting the right person, accountable professionals, successive visits, clinical evidence, external work and money without confusing their meanings. Adding more menus or increasing the number of concurrent accounts alone will not close that gap.

The retained product direction is one dental chain per independent deployment, initially mainland outpatient dentistry. Five to twenty clinics is a sizing hypothesis. “Full replacement” must cover the first customer's contracted clinical services; a synthetic teaching installation is a separate delivery milestone.

The study uses six product families: **Open Dental, Dentrix Ascend, Dentally, CareStack, 领健 e看牙 and 牙医管家**. Official manuals establish documented workflows; vendor feature pages establish advertised scope. Neither demonstrates comparative security, performance, adoption, improved outcomes or suitability for a Chinese clinic. Regulatory and professional sources identify responsibilities to review locally. The ADA survey provides dated US operating context, not Chinese prevalence estimates.

The source register records what was read, its evidence type and limitations. No competitor account, patient record or private integration was accessed. Search results led to primary documentation; forum anecdotes, advertisements for unrelated products and unverified market-share claims were not used as evidence.

The course notes provide the analysis method:

- **Note 3, pp. 1–5 and 11:** distinguish required observable behavior from design; trace goals to design/code; specify invariants, preconditions, postconditions and responses to unwanted events.
- **Note 5, pp. 4–10:** separate concerns, keep visibility restricted, hide changeable decisions behind operations, and design for useful flexibility rather than unrestricted generality.
- **Application:** every next-stage item identifies a business problem, actor, authority, state/data owner, failure response and acceptance scenario. More diagrams are useful only when they resolve a decision.

Mind map: evidence → {manual behavior, clinic obligations, operating context, inspected ADC facts} → {supported finding, design inference, field question} → development decision.

## 2. What to learn from Open Dental（从参考系统提取可取之处）

The Quick Manual organizes work around appointments, family, account, treatment plan, chart, imaging and management. The transferable idea is a connected patient journey with distinct business records. Its American insurance, guarantor, coding and payment-provider assumptions require adaptation.

| Documented capability | Useful business lesson | ADC adoption decision |
|---|---|---|
| [Appointment lists and daily/weekly views](https://www.opendental.com/site/0_appointments.html) separate confirmations, unscheduled work, recall and earlier-opening requests | A calendar must expose work that still needs action | Retain front-desk scheduling ownership. Add typed readiness/recall worklists; avoid one undifferentiated “pending” list |
| [Family information](https://www.opendental.com/site/0_family.html) groups related people and financial responsibility | Patient, contact and payer are different concepts | Model relationships explicitly. A family/contact/payer link grants no automatic chart access or treatment-consent authority |
| [Treatment plans](https://www.opendental.com/site/0_treatmentplan.html) retain active/saved alternatives, priorities and planned appointments | A course of treatment survives individual appointments | Version plans and steps; relate each actual performed event to its agreed plan version where applicable |
| [Clinical chart](https://www.opendental.com/site/0_chart.html) connects tooth history, periodontal records, prescriptions, consent and lab work | Clinicians need a patient-centered longitudinal workspace | Introduce structured findings and dental charting alongside protected original notes; support keyboard entry as well as a graphical view |
| [Patient accounts](https://www.opendental.com/site/0_account.html) and [payment allocations](https://www.opendental.com/site/0_patpayment.html) connect balances, procedures, prepayments and payment splits | A receipt and the debt it settles are separate facts | Extend existing reviewed cash evidence with explicit allocation rules. Keep estimate, charge, cash, refund and tax document distinct |
| [Recall lists](https://www.opendental.com/site/0_recalllist.html) retain due dates, contact attempts and booking actions | “Reminded” does not mean “returned for care” | Add an accountable recall obligation linked to actual attended/completed care, with deferred, unreachable and declined outcomes |
| [Lab cases](https://www.opendental.com/site/0_labcases.html) link sending, return and quality checks to appointments | An empty chair does not guarantee readiness for a crown-fitting visit | Bring internal lab-case tracking and readiness coordination forward into the clinical-continuity increment |
| [Imaging](https://www.opendental.com/site/0_images.html) keeps patient images and documents together | Images need identity, provenance and accessible comparison | Start with controlled attachments and authoritative imaging references; a photo uploader is not a qualified diagnostic viewer |
| [Management](https://www.opendental.com/site/0_manage.html) and [supply inventory](https://www.opendental.com/site/0_supplyinventory.html) cover tasks, accounting, suppliers and orders | Operational work extends beyond chair bookings | Add purchasing, lots, expiry, use and infection-control requirements from actual clinic workflows; the brief inventory manual alone does not establish this full traceability |

Three choices should **not** be copied automatically: deleting historical business facts because another product permits it; letting a family guarantor see all clinical records; or allowing an appointment-completion shortcut to substitute for attributable actual-treatment confirmation. ADC's retained history, resource locks and independent financial review remain useful differentiators in its design, without claiming superiority to another system's implementation.

Mind map: Open Dental → {patient workspace, planned care, actual care, payments, recall, external work} → continuity with distinct facts and explicit responsibility.

## 3. Wider benchmark and contemporary clinic needs（更广泛的对标）

| Source family | Observed lesson | What it changes in the ADC plan |
|---|---|---|
| Dentrix Ascend: [cases grouped into visits](https://learn.dentrixascend.com/courses/clinical-essentials-for-teams/lessons/treatment-planning/topic/creating-a-treatment-plan-case/), [recare work](https://learn.dentrixascend.com/courses/scheduling-essentials-for-teams/lessons/scheduling-recare/), [signed-note addenda](https://learn.dentrixascend.com/courses/clinical-essentials-for-teams/lessons/charting/topic/adding-an-addendum-to-a-signed-clinical-note-2/) | Planned steps, the next appointment and signed clinical evidence have separate lifecycles | Split clinical completion/signing from the old invoice-linked record lifecycle; add unscheduled accepted-treatment work |
| Dentally: [versioned medical-history forms and review](https://help.dentally.com/en/articles/3566262-how-to-manage-a-patient-s-medical-history-information) | Patient-reported answers retain their source; previous histories remain accessible; review/invalidation is explicit | Website/mini-program intake produces a reported version, followed by professional review. It cannot overwrite a verified allergy fact automatically |
| CareStack: [location-scoped search](https://carestack.zendesk.com/hc/en-us/articles/44464270867860-Patient-Search-Scope-Configuration), [recall](https://carestack.com/en-GB/dental-software/features/recall-management), [multi-site operations](https://carestack.com/en-AU/who-we-serve/groups-dsos) | Their search documentation explicitly describes the tension between branch restriction and duplicate identities/fragmented histories | Keep chain-level identity resolution separate from permission to read a clinic's clinical record; add a restricted cross-clinic verification/referral path |
| 领健 e看牙: [official scope](https://www.lingjian.cn/kouqiang/about-eky.html) | Advertises clinical records, inventory, imaging, chain management and supplier connections together | Review workflow handoffs and supplier responsibilities; do not interpret a marketing list as proof of traceability or integration quality |
| 牙医管家: [developer's App Store description](https://apps.apple.com/cn/app/%E7%89%99%E5%8C%BB%E7%AE%A1%E5%AE%B6/id904824378) | Describes mobile appointments, follow-up, clinical/financial/inventory work and role-based collaboration | Extend the mini-program as a patient task channel while staff retain attributable professional workspaces; do not replicate every desktop form on a phone |

The [ADA Q3 2026 report](https://www.ada.org/-/media/project/ada-organization/ada/ada-org/files/resources/research/hpi/state_us_dental_economy_q32026.pdf) discusses demand, costs and recruitment together. Its methodology reports 750 responses, including 704 private-practice respondents, with stated respondent-selection biases (pp. 43–45). This supports investigating team capacity and cost visibility alongside booking utilization. It does **not** establish the frequency of those problems in China or an effect ADC will achieve.

For a mainland outpatient clinic, the [2022 clinic filing rules](https://app.www.gov.cn/govdata/gov/202212/28/495617/article.html) connect actual services, personnel, equipment, infection control and local regulatory reporting. The [2025 electronic-record notice](https://app.www.gov.cn/govdata/gov/202507/01/531972/article.html) makes role/task/purpose/time-limited access and traceability especially relevant. These responsibilities extend beyond the presence of a login screen.

Mind map: wider comparison → {staff capacity, documented continuity, scoped sharing, supplier coordination, mobile tasks} → clinic-specific operating contract.

## 4. Clinic shortcomings and software shortcomings are different（诊所与软件分别分析）

The following are **failure modes to investigate**, not measured claims that every clinic has them. Improving software without assigning clinic responsibilities can simply digitize an incomplete process.

| Clinic-level failure mode | Business consequence | Organizational response | System support |
|---|---|---|---|
| Nobody owns the next step after a visit | Accepted treatment or necessary follow-up remains unscheduled | Assign a responsible role, due window and escalation route | Recall/unscheduled-plan worklist linked to completed care |
| Front desk optimizes the calendar without clinical readiness information | Patient arrives before lab return, clinical review or required resources are ready | Clinical staff define prerequisites; front desk coordinates commitments | Explain the blocker and its owner; preserve the existing appointment until explicit coordination |
| Different people use “family”, “contact”, “payer” and “guardian” interchangeably | Wrong information disclosure or inappropriate consent handling | Approve distinct identity and authority procedures | Separate relationship evidence and action grants |
| Informal messages are the only handover | Lost task, unclear response and untraceable delay | Define sending, acknowledgement, due date and escalation | Typed task/event history; message delivery is not task completion |
| Cost or sales targets dominate quality review | Apparent utilization can conceal rework, incomplete records or poor follow-up | Review financial and quality measures together | Cohort-based outcomes, missing-data flags and attributable exceptions |
| Instruments/materials are tracked only as purchases | Expired stock or a failed sterilization cycle cannot be traced to affected use | Assign stock/infection-control ownership and release/recall procedures | Lot/package/cycle/use chain, quarantine and reconciliation |
| Clinical work depends on an individual doctor's memory | Transfer, absence and cross-site care become fragile | Standardize relevant record templates and handover responsibilities | Longitudinal chart, professionally confirmed findings and pending results |
| Downtime and staff departure have no practiced process | Care or record access stops unexpectedly | Train on continuity, access revocation and reconciliation after recovery | Controlled downtime/export procedures, recovery drills and named incident ownership |

Infection-control traceability is grounded in the [CDC dental summary](https://www.cdc.gov/dental-infection-control/hcp/summary/sterilization-disinfection.html), which connects processing records, monitoring and failure response. Chinese implementation must be reviewed against applicable requirements including the published **WS 506-2016** standard and local practice. This study verified its official publication entry; it did not perform a full clause-by-clause conformity assessment.

**Field-validation proposal:** observe two general single-site clinics and one chain branch, if access becomes available; interview reception, dentists, nursing/infection-control, finance and the owner (approximately 6–10 participants, qualitative rather than representative). Walk through a first visit, multi-visit treatment, a lab delay, a failed follow-up and an end-of-day exception. Use consented synthetic/redacted examples. Record present owner, actual waiting time, duplicate entry, workaround and desired outcome. No interviews have yet occurred.

Mind map: clinic operation → {roles, handovers, capacity, quality, continuity} + system support → measurable task completion; software does not supply missing clinical authority.

## 5. ADC gap assessment from inspected code（代码支持的差距）

“Foundation” means useful existing behavior; “partial” means the larger business obligation remains incomplete; “missing” means no corresponding implemented domain was found in the inspected active models/routes. “Unverified” describes execution evidence, not necessarily missing source. No maturity percentage is invented.

| Area | ADC evidence and current position | Remaining business gap | Priority |
|---|---|---|---|
| Scheduling/resources | **Foundation:** `scheduling/models.py`, `resource_models.py`, shared locks, day/week front-desk views, reception, waitlist and self-rescheduling | Team/assistant availability, phased occupancy, clinical/lab prerequisites and capacity forecasts | Preserve existing behavior; readiness in C2, phased resource work later |
| Identity/relationships | **Partial:** `patients/models.py`; `portal/models.py` has a one-user/one-patient `PatientAccess` | Guardian/delegate authority, multiple authorized patients, identity mismatch review and controlled cross-clinic continuity | C1 first |
| Professional authority | **Partial:** seven workspaces; `DentistQualification` records a catalogue association | Verified credential validity and clinic/service authority; nursing, pharmacy and records responsibilities | C1 first |
| History and clinical record | **Partial:** allergy review and `clinical_note`; `VisitRecordVersion` also carries financial snapshots | Structured medical history, diagnosis/findings, attributed clinical review, tooth/surface/periodontal data and longitudinal view | C2 |
| Multi-visit care | **Missing:** no treatment-plan/step/performed-event domain in current schema | Plan alternatives, accepted versions, staged execution, deferred treatment and outcome follow-up | C2 |
| Clinical document evidence | **Missing as a complete clinical lifecycle:** published financial versions are protected | Clinical signing/amendment/archive, procedure-specific consent, controlled copies and retention | Design in C1/C2; C3 gate before real replacement |
| Imaging/laboratory | **Missing as a protected clinical workflow** | Patient/study identity, source files, pending results, lab dispatch/receipt/quality/rework and due-date coordination | Internal lab flow C2; controlled files C3; external integration C5 |
| Prescribing/pharmacy | **Missing:** no prescription/review/dispense model and professional role | Authorized prescription, reviewed knowledge, rejection/correction, partial dispense/return and charge prerequisites | C4, required for contracted prescribing |
| Recall/post-care support | **Partial:** cancellation follow-up and coordination tasks exist | Clinical follow-up obligations, unanswered symptoms for clinical review, overdue recall and actual completion linkage | Bring forward to C2 |
| Instruments/materials | **Partial:** asset and repair workflows exist | Consumable lots/expiry, purchase/receipt/use/return, implant traceability, sterilization release and affected-patient trace | C5, prerequisite for relevant real services |
| Finance | **Foundation:** receipt/refund evidence, reviewed cash, CSV one-to-one reconciliation, invoice version history | Deposits and allocations across bills, provider callbacks, cost/profit completeness, actual tax/insurance interfaces | C6; define performed-charge contract in C2 |
| Patient website/native client | **Foundation for synthetic booking:** eleven native pages and shared server effects | Verified guardian subject switching, intake, plan understanding, approved documents and controlled reminders | Extend through each business slice |
| Quality and management | **Partial:** cancellations, improvements and existing financial reports | Overdue clinical work, plan completion, lab delay/rework, record quality and consistent cross-clinic denominators | Define now; implement with source facts |
| Security and privacy | **Foundation:** scoped writes, signed previews and safe operational logging | Sensitive-read/export auditing, professional-purpose access, privileged account protection, retention and vendor access governance | Continuous, starting C1 |
| Production operations | **Local evidence only:** restore, fault exercises and C0.3 installation retained | Independent host operation, complete off-host recovery, sustained observation, release support and customer exit | Parallel workstream; C7/C8 qualification |

The code-specific design pressure is visible in [`care/services.py`](../../care/services.py): `complete_visit` validates actual charge lines, publishes a `VisitRecordVersion`, creates an `Invoice` and closes the visit in one transaction. That behavior is appropriate to its existing bounded workflow. It should not be stretched into a universal clinical signature, long treatment-course completion or prescription state machine. The recommendation is additive clinical ownership with an explicit charging bridge, not a rewrite of historical invoices.

Likewise [`patients/selectors.py`](../../patients/selectors.py) derives visibility through registration/visit and assigned-dentist relationships. New shared-care authority needs a deliberate relationship policy; simply broadening the query to all patients in the chain would not implement it.

The [C0.3 delivery record](../evidence_c03/delivery.json) identifies a locally accepted synthetic application, 70 tables, 171 SQL foreign keys, 42 triggers and 40 migration files. Its tests and protected upgrade are completed evidence. The [B1.4 load record](../evidence_b14/capacity.json) measured a specific five-clinic/twenty-patient, 30-minute, 5-request/second workload; it is historical, not proof of the new clinical workload or twenty-clinic production capacity. WeChat runtime/device/experience, cloud and professional clinical qualification remain separate pending evidence. The collector's unreproduced failure/gap remains in history.

Mind map: ADC → retain {resource consistency, scoped commands, money history, recovery} → extend {identity, clinical facts, continuity, external work, production responsibility}.

## 6. Systems analysis and design decisions（系统分析与设计）

### 6.1 Requirements and sociotechnical boundaries

Use four complementary views: **actor goals**, **business process/handovers**, **domain data/invariants**, and **lifecycle/authority**. A use-case count is an index, not completeness evidence. A real scenario should cross several use cases and include refusal, expiry, interruption, missing results and recovery.

The system boundary includes the clinic's human decisions and external dependencies. Front desk owns scheduling and contact; clinicians own diagnosis, clinical prerequisites and performed treatment; nursing/infection-control owns applicable execution and instrument release; pharmacy owns its reviewed professional steps; finance owns payment/reconciliation review. One employee may hold several roles, but each action remains attributable and required independent review cannot be achieved by switching roles.

Under the [2018 prescription-review norm](https://wjw.wuxi.gov.cn/doc/2023/02/13/3881781.shtml), the publication distinguishes institutions that execute the norm from other institutions that refer to it. ADC should adopt the reviewed-before-charge/dispense workflow already selected in its master plan, then obtain clinic-specific pharmacy/legal applicability review. A finance approval is not pharmaceutical review.

### 6.2 Domain and database boundaries

Keep the modular Django/PostgreSQL system. Strengthen module contracts and read projections first; split services only when actual deployment, ownership or load evidence justifies the extra consistency burden.

| Distinction to preserve | Proposed owner/contract | Consequence for ER and commands |
|---|---|---|
| Account / patient / relationship / permission | Identity owns verified relationships and time/action-scoped grants | Relationship alone is not a grant. Preserve current self-access and receipt history; add explicit actor and subject semantics |
| Appointment / encounter | Scheduling owns a promised slot; clinical module owns actual interaction | Retain `Visit` compatibility. Decide an additive encounter link before migration; do not infer a clinical encounter from every cancelled booking |
| Finding / planned step / performed event | Clinical module owns versioned observations, plans and execution | A planned or declined step cannot create a performed event or charge |
| Clinical note / signature / amendment | Clinical records owns authored versions and their evidence | Financial correction approval must not approve clinical authorship; signed original remains readable |
| Estimate / charge / invoice / cash / allocation | Finance owns receivables, posted cash and allocations | Typed source links and uniqueness prevent duplicate charges; old invoice amounts remain fixed |
| Equipment asset / stock lot / sterile package / actual use | Equipment, inventory and infection control own separate lifecycles | “Operational asset” does not imply “sterile instrument”; recalls trace actual use |
| Task / notification / provider receipt | Task owner controls completion; delivery adapter reports transport state | Read/sent/delivered/completed are not interchangeable |

Use normalized relationships for identities, permissions, plan steps, performed events, charge sources and stock movements. Reserve JSON for bounded, versioned snapshots or reviewed template extensions. Store event time separately from recording time. Preserve measurement units, tooth-numbering scheme, provenance and unknown values. Add indexes/constraints for actual invariants, not speculative combinations.

The proposed [identity](identity_concept.svg) and [clinical-continuity](clinical_concept.svg) views are **logical design proposals**, not observed SQL. The actual ER remains generated from migrated PostgreSQL. Future additive migrations must regenerate it and verify constraints, history and recovery before the course report describes those relations as implemented.

[FHIR RelatedPerson](https://hl7.org/fhir/R4/relatedperson.html) and [Encounter](https://hl7.org/fhir/R4/encounter.html) are useful vocabulary references here, explicitly using the published R4 pages. They do not dictate ADC's tables or prove FHIR conformance. External imaging work should use the partner's actual [DICOM interface/conformance documentation](https://dicom.nema.org/Medical/dicom/2024d/output/html/part01.html); a generic standards link is not integration acceptance.

### 6.3 State models and failure behavior

- **Relationship verification:** `PENDING → VERIFIED / REJECTED`; a verified relation may be `SUSPENDED / EXPIRED / REVOKED`. A new grant requires its own scope; a suspended/revoked authority cannot confirm an old preview.
- **Plan revision:** `DRAFT → PRESENTED → ACCEPTED / DECLINED / DEFERRED`. Editing an accepted proposal creates a new version requiring the appropriate decision. Patient acceptance is separate from procedure-specific informed consent.
- **Execution:** a planned step may have several performed events across encounters. Cancellation of the remaining plan preserves completed events. Financial consequences require a separate reviewed command.
- **Clinical record:** draft/review readiness precede signing; signed content is amended through an attributed linked record. Exact signing and retention controls belong to C3. C2 cannot label a normal save as a qualified clinical signature.
- **Recall:** due window → contact attempts → booked → attended/completed, with unreachable/deferred/declined and overdue states. Cancelling its appointment restores pending follow-up responsibility, not a false completed state.
- **Lab case:** requested → dispatched → acknowledged → returned → quality accepted, with delayed/rework/cancelled paths. Receipt is not clinical quality acceptance; a failure creates coordination without silently cancelling the appointment.

### 6.4 Usability, measurement and operations

Use a patient banner with explicit subject and acting capacity, a clinical timeline with source/date/status, a front-desk day view with readiness blockers, and a worklist showing owner/due date/next action. Ordinary draft edits should be fast and recoverable; reserve deliberate confirmation/review for authority, clinical commitments, signatures and money. Keep keyboard/non-drag paths, readable status text, narrow-screen layouts and clear conflict recovery.

Define business metrics before a dashboard:

| Metric | Proposed definition / essential boundary |
|---|---|
| Cancellation rate by slot | Unique scheduled appointment instances in a defined start-date cohort; patient and clinic cancellation separate. Rescheduled originals and terminal successors need separate episode analysis, not silent recoding |
| Late cancellation/no-show | Versioned clinic cutoff and explicit outcome; record counts and observation maturity. Do not mix an unobserved future appointment into the outcome denominator |
| Recovered chair time | Released bookable minutes that were subsequently used for actual care / eligible released minutes; require event evidence. New appointment counts alone overstate recovery |
| Recall completion | Clinically completed eligible recall episodes within the agreed due window / eligible episodes whose window has closed; distinguish booked, declined and lost-to-follow-up |
| Plan progression | Accepted version's due steps completed with attributable performed facts / due steps; preserve clinical changes, patient refusal and partial execution |
| Lab readiness/rework | Required cases accepted before the relevant appointment / cases due; rework and delay shown separately |
| Financial health | Receivables, cash, allocations, refunds, unresolved reconciliation and recorded costs separately; missing costs cannot yield a meaningful profit claim |

These are proposed contracts, not changes to B1.1's existing metric. First reconcile old definitions, then version any changes. Cancellation-rate differences may reflect service mix, lead time, patient constraints or clinic cancellations. Investigate counts and stratified comparisons before changing slots; a before/after dashboard alone cannot establish causal improvement. A small, ethically appropriate scheduling/reminder trial can follow, with waiting time, patient choice, contact burden and safety as guardrails. Predictive AI and automated overbooking are not the next dependency.

Use the current [OWASP ASVS 5.0.0](https://asvs.owasp.org/) as a versioned security review catalogue and [SRE service objectives](https://sre.google/workbook/implementing-slos/) for user-visible reliability. The existing proposed 20-clinic/30-rps and availability/recovery targets remain planning hypotheses. Define representative workloads and operating responsibility before offering an SLA. Recover SQL plus protected files, source/version links and relevant keys; a database-only restore ceases to be enough when clinical documents are introduced.

Mind map: analysis → goals + people + exceptions; design → owners + relations + state contracts; assurance → user tasks + business facts + recovery + measured outcomes.

## 7. Recommended development order（下一步顺序）

The next usable milestone is **C1–C2: trustworthy identity and continuous care**. Finish the outstanding C0 environment/scope contracts alongside it; do not claim all C0 work was completed by service-page delivery.

1. **C1.0 — contract and model decisions:** first-clinic service matrix, role/action matrix, identity/receipt compatibility ADR, clinical-to-finance ADR and proposed ER. Desk-research decisions can proceed now; professional/clinic validation remains attributable and pending.
2. **C1.1 — patient and representative relationships:** verified, bounded authority; explicit patient switching on website/native client; preserve adult self-service. Start with appointment actions, not automatic clinical-document access.
3. **C1.2 — professional and shared-care authority:** credential evidence and validity, clinic/service scope, authorized referral/identity resolution, sensitive-read/export audit and staff departure handling.
4. **C2.1 — structured clinical workspace:** medical-history versions, professional review, tooth/surface findings, attributable encounter drafts and patient-safe concurrency.
5. **C2.2 — multi-visit plans and actual execution:** versions/alternatives, accepted steps, next appointment, actual performed events and a single controlled charging source.
6. **C2.3 — recall and treatment readiness:** owner/deadline-based follow-up, unscheduled accepted treatment, internal lab-case delay/rework and front-desk coordination. Clinical consent/signature evidence designs progress with this slice; real-use qualification still requires C3 and every contracted dependency.

This refines the earlier sequential roadmap: recall and internal lab readiness no longer wait for completion of pharmacy or all inventory integrations. Full prescribing, instrument/material traceability, commercial payments and deployment qualification remain mandatory where contracted. Protected objects, security, recovery, environment separation and monitoring run across the batches.

The detailed [next-stage plan](../COMMERCIAL_V2_NEXT_STAGE.md) defines entry/exit conditions and 24 proposed acceptance scenarios. The backlog retains existing IDs and executed service statuses; newly added requirements remain planned. No calendar promise is made before clinical reviewer, integration and customer inputs are known.

Mind map: C0 contract closure → C1 identity/authority → C2 record/plan/recall/readiness → C3 evidence → C4/C5 clinical execution → C6 money → C7/C8 qualified operation.

## 8. Research limits and next decisions（证据边界）

This study does not establish market-wide clinic deficiency rates, product rankings, improved cancellation outcomes or clinical/legal approval. The first customer must still identify service scope, local reporting/insurance/tax obligations, authority reviewers, external imaging/lab/payment providers, retention/signature arrangements and support/hosting responsibilities.

The [2017 electronic-record norm](https://www.beijing.gov.cn/zhengce/zhengcefagui/201905/t20190522_59868.html) informs unique patient identity, attributed history and archive/retention design. The [Personal Information Protection Law](https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm) informs lawful-purpose, sensitive-data and child-information handling. These sources have different scopes; data-processing consent, medical informed consent, appointment delegation and financial responsibility must be reviewed separately. Neither a generic checkbox nor a guardian phone number settles all four.

The practical next implementation is C1.1 after its bounded identity/authority and receipt ADR is agreed. It creates a visible patient-channel improvement and a sound basis for C2, while the full clinical replacement remains a larger, explicitly gated program.
