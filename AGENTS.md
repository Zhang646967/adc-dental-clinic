# ADC RC1 engineering rules — macOS development

The user resumed macOS migration on 2026-10-12 and requested a public
`adc-dental-clinic` repository. The original Windows host was reset. The supplied
RC1 ZIP contains source and historical artifacts, but no Git history or database
backup. Preserve tag `v1.0.0-rc.1`; develop on `main`. Use a fresh synthetic demo.
Current host instructions are in `docs/MACOS.md`; older Windows reports retain
their historical validation status.

Development target: a commercial outpatient dental platform, independently
deployed per dental chain, with full replacement of clinical records and
prescribing in the contracted clinic scope. The user selected this direction
on 2026-10-22. The existing implemented/running baseline remains synthetic and
has not been qualified for production clinical use. Preserve the distinction
between target requirements, implementation, actual verification and release.

## Current commercial V2 direction

- `docs/COMMERCIAL_V2_MASTER_PLAN.md` and its linked baseline/backlog govern new
  development. This supersedes the old RC feature freeze and teacher-only
  delivery priority; historical records keep their original scope.
- Customer interfaces foreground clinic/product identity and actual business
  tasks. Academic labels and developer acceptance checklists belong in separate
  engineering materials. Isolated test environments retain accurate provenance.
- Full clinical replacement includes reviewed dental records/plans, consent,
  signatures/amendments/archive, prescribing/pharmacy and the contracted
  nursing/material/imaging/lab flows. Billing notes alone do not establish it.
- Existing seven-role authority is the implemented baseline. New professional
  roles/scopes need explicit policy, additive implementation and negative tests;
  planning them must not grant privileges or certify professional qualifications.
- Reuse established booking/resource locks, immutable financial history and
  independent reviewer boundaries. Preserve all 39 migrations; clinical model
  extensions require reviewed ADRs, additive migrations and actual PG evidence.
- Keep synthetic accounts/data separate from production initialization. Demo
  credentials already disclosed for local testing must never become customer
  credentials. No real medical records, private keys or backups in source/GitHub.
- Clinical/pharmacy/privacy acceptance requires the relevant qualified people.
  Do not invent their participation or equate code/fixtures with their approval.
- Commercial planning does not authorize procurement, broader public exposure,
  real-data import, live prescribing/payment or a previously rejected upload.
  Continue authorized implementation and record concrete environment blockers.

## C0 service-content source candidate

- `docs/C0_SERVICE_RELEASE.md` and `docs/evidence_c0/verification.json` distinguish
  source implementation, executed rules and unexecuted target acceptance.
  `SERVICE-01` is implemented; broader C0/clinical requirements remain incomplete.
- `scheduling/0006_servicepresentation` is an additive migration; the original
  39 migrations and observed schema snapshots remain unchanged. Reverse refuses
  populated service descriptions. Do not label design-derived table counts as observed.
- Public guides do not imply clinic capability. Only complete explicitly published
  operational offerings appear; unknown fees remain NULL. No template auto-publishes.
- Only the current-clinic manager edits/previews/publishes content through normal
  signed preview/confirmation and audit. Authorized draft preview cannot book.
- Patient service hints bind user, login workspace and typed service ID, expire
  after ten minutes and resume only after ordinary valid PATIENT activation.
  GET can read an existing context but cannot create or select one for this handoff.
- Child descriptions do not authorize guardian self-booking. Preserve the explicit
  front-desk verification path until separately implemented authorization exists.
- Port 18000 remains the prior installed baseline until a protected target update
  actually succeeds. Do not present candidate routes as a working new deployment.

1. Preserve old migrations, historical snapshots, .env, Compose identity and database volumes. New schema changes need additive migrations and actual PostgreSQL validation.
2. After authenticated login POST, exactly one valid role is activated server-side and routed directly; zero or multiple roles see selection. Never bypass context creation, grant checks or stale-token protection. Role and clinic are separate choices. Manager/frontdesk choose clinic inside their workspace. Doctor sees assigned visits; patient uses PatientAccess.
3. WorkspaceContext in DB is authoritative; session contains an opaque key only. Unsafe HTTP requests need CSRF plus signed context token (AI uses X-ADC-Workspace); writes re-lock/recheck context and grants. Never use hidden menus as authorization.
4. One person cannot self-approve by switching roles. Multi-role account does not imply combined privileges. Changing context must invalidate stale forms and guide progress.
5. All booking channels and offer publication/acceptance use shared slot/resource locks and checks. PG advisory locks are an application protocol, not enforcement against arbitrary direct SQL by DB owners.
6. Waitlist suggestions and offers are NOT bookings. Only explicit owner/frontdesk confirmation creates a Visit. Limits/expiry must be rechecked. Do not introduce automatic acceptance.
7. Solver maximizes cardinality only in the bounded fixed-30-minute bipartite graph. Preserve the enumerated-scope caveat. Do not label it CP-SAT, chair allocation, travel optimization or clinical qualification verification.
8. Task-guide labels/routes/selectors are curated. Model intent is untrusted, outputs are allowlisted. AI never clicks, submits, writes SQL or chooses permissions. Next-step is instructional only.
9. Reauthorize after external AI. Key stays backend-only. Consent before limited text externalization; no raw database records/prompt history in logs. No API call in tests unless explicitly separated and authorized.
10. Preserve patient and staff accessibility modes; no automatic age profiling, no required drag/hover/chat, no remote audio fallback. Pause/exit guides without data submission.
11. Keep billed revenue vs cash, missing vs zero, snapshot vs closed ledger, one logical invoice vs multiple versions distinct. Preserve no-treatment semantics and reviewer separation.
12. Static tests and fixture screenshots never prove Django/PG/E2E or real model results. Current expected counts are documented, not coverage percentages. Never disable a safety assertion to get green tests.
13. Technical/admin, production, recovery, resource constraints and terminal correction gaps remain explicit. Production candidates still need real target-environment and recovery validation.

Run: unittest checks; Django check; makemigrations --check --dry-run; migrate; manage.py test tests --settings=config.settings.test. Browser fixture scripts are additional UI checks, not substitutes.

14. Account governance is not a public identity service or a clinical authority. Keep technical self-management and technical/superuser targets outside the UI. Repeat password and target-state verification inside the same audited transaction.

15. SU-26 contact maintenance is FRONT_DESK/current-clinic only. Preserve the exact five-field whitelist, separate clinical/identity/account fields, preview-before-write, explicit confirmation, signatures, audit cursor (ABA) and operation-ID replay guard. No raw contact values in audit or external AI. Published invoice header snapshots never follow current-contact edits.
16. The first Windows verification entry is VERIFY_ISOLATED_WINDOWS.cmd. Never merge its Compose file with the running project, reuse real .env, expose verification DB ports or use down -v. Old reports are historical; current evidence lives under docs/evidence_v09a10.

17. Migration tools must never restore into an existing database or infer a Docker target. Pin a local context and an explicit source container ID. Keep PG17, business timezone, schema and historical data unchanged during host migration.
18. Logical transfer bundles are PRIVATE and unencrypted; exclude .env and Git history. Preserve unlisted/local files separately. Rehearsal success is not a live cutover, E2E result, production release or evidence that Windows can be discarded.

19. macOS source migration and a new synthetic local demo are authorized. Do not claim recovery of the reset Windows database. Backup import still requires a supplied trusted synthetic backup and the explicit import-copy flag. Existing logical migration tools stay unchanged.
20. SU-27/28 is SYSADMIN/current-workspace-only bounded directory registration and qualification-record association, not clinical verification or a general CRUD editor. Keep code uniqueness, preview-before-save, password/confirmation checks, signed context binding, audit-cursor ABA protection and replay guards. No automatic accounts, grants, appointments, scheduling eligibility or history rewrites. No deletion or renaming.

## Availability maintenance (B1.3.1; replaces alpha.6 ownership)
- Only current-clinic FRONT_DESK maintains availability, intake and waitlist planning; an assigned role is not the active role. MANAGER maintains resource catalogues and independently reviews coordination.
- Stop/replace only future effective source slots without protected visits or effective holds.
- Never rewrite original interval/clinic/dentist or delete history; replacement uses a new row.
- Maintain actor/context/grant/source-slot lock ordering and retain original exclusion constraints.
- Record true test scope: static/template/AST tests do not prove ORM/HTTP/PG behavior.
- Mac source migration is active; do not infer or restore a missing v0.7 database.

## Front desk coordination (alpha.7)
- SU31 is an explicit-slot, current-clinic FRONT_DESK read projection; never a ticket, patient consent or stop-booking flag.
- Reuse availability impact policy and existing slot locks, compute complete bounded results before paginating, fail closed on malformed/oversized relations.
- Project patient business codes only. Keep personal/clinical fields in existing authorized detail pages. Manager cannot inherit front access.
- Expired pending holds, accepted offers, live visits and historical visits are distinct. Never cancel care to make availability look empty.
- Typed coord_slot navigation is not authority or arbitrary URL redirect. Original commands own writes and each destination must reauthorize.
- Observe current facts after returning; a clear read never guarantees a later maintenance command. No new schema/model, freeze, automated reassignment or notifications.

## Admission control (alpha.8)
- User local deployment and release validation are deferred to v1.0. Do not ask for every-alpha manual verification. Continue developer checks and record gaps truthfully.
- New additive schema: booking_paused and intake_revision on AvailabilitySlot. Preserve old13 migrations; do not mix old binaries with new writing code.
- Pause is not is_active=False or clinical cancellation. Existing valid PENDING offers remain promises; exact authorized acceptance may create the corresponding Visit.
- New booking, inbound reschedule, candidate enumeration and offer publication all obey intake gate. No client-provided bypass flag.
- Old previews and drafts must not revive after pause/resume (revision); successful request replay must not undo later changes. Replacement inherits pause.
- SQL owners/direct ORM outside command protocol are not guaranteed by this application admission policy. Never claim unexecuted PG/HTTP/concurrency tests passed.


## Accountable coordination tasks (alpha.9)
- Front desk can initiate a paused-slot task and records a future follow-up deadline. Existing historical deadlines remain absent. SU34/35/36 add a workflow record only. No implicit slot pause/resume, appointment cancellation, offer answer, care change or patient notification.
- Only current-clinic MANAGER/FRONT_DESK. A frontdesk claims for themself; another frontdesk cannot update an owned task. A manager may requeue an unavailable owner's work without impersonation or expanding grants.
- One active task per source slot, source identity is immutable, no deletion/terminal rewrite. Preserve new migration and all previous 14 migrations.
- Start only after explicit pause on future effective source. Submit/approve only against full bounded current facts and a still-paused future source. Accepted old offers can still become protected visits.
- READY is not a guarantee that facts will stay unchanged. Approve rechecks submitted fingerprint, time and blockers; reviewer must differ from latest submitter. A workflow stamp does not authorize clinical or availability edits.
- Progress codes are operator declarations only, not consent or verified booking results. No free-form personal/clinical text; managers see only aggregate evidence, never patient references from task logs.
- Use actor/context/grant/slot/task write locks, strict signed 15-minute proposals, revision/replay checks, transactional audit. Prior successful requests return current task, never undo later transitions.
- User deployment/release validation remains deferred to v1.0. Developer checks continue; no claim that authored PG tests or migration files have run.


## Task notices (alpha.10)
- Task, audit and durable Outbox intent share one transaction; do not replace the row with an on_commit-only callback. No network effects in the task command.
- Freeze original eligible grant targets; dispatch and read reauthorize current role/clinic and ownership. Do not backfill new recipients or mix roles. Never include patient identifiers, contact details or raw statement payloads in notices.
- Worker changes only notice state and inbox rows, with short event transactions, SKIP LOCKED, event/grant uniqueness and bounded backoff. No automatic task, appointment or offer actions.
- GET never marks read; explicit own-message POST only. Read is not agreement or proof of comprehension. Read-only instances do not acknowledge, retry or dispatch.
- Event history and current task state are distinct. A completed delivery is an inbox-row commit, not a human receipt. No FIFO/external exactly-once promise.
- Preserve previous15 migrations. New notification data blocks destructive reverse. Old writers cannot coexist with the current task/notice workflow.
- v1.0 scope is bounded by docs/V1_SCOPE_AND_REMAINING.md. After this batch only operations/UX closure and RC assembly remain in plan; user validation begins at RC.

## Patient self-rescheduling (B1.4)
- PatientAccess and active PATIENT context authorize only own source. Same-clinic, same-service replacements use existing resource rules; ordinary candidates use current duration, valid held offers retain promised duration.
- Shared locked rescheduling owns the original terminal state, unique successor and claims; portal adds BookingReceipt in the same transaction. Offer acceptance stays in coordination and links the same reception result. Preserve all 39 migrations.
- Replay returns saved result current state; never revive later cancellation. Rescheduling is not a cancellation or a clinical/financial fact. Old offer and follow-up evidence links remain historical.

## Native patient mini-program (B1.5.1)
- The user requires a native WeChat course client and later a teacher-only cloud demonstration. `clients/wechat` and `/api/mini/v1/` are the narrow assigned-patient channel; they reuse existing commands, PatientAccess, session/CSRF and workspace signatures. No alternate booking inventory or automatic phone/OpenID binding.
- Login explicitly activates only authorized PATIENT, even for a multi-role person. Business confirmation still rechecks authorization and resources under existing locks. Session cookies/passwords stay out of client persistent storage and logs.
- Preserve all 39 migrations and actual ER relations. Source/transport/HTTP tests and real backend Page-handler runs do not establish WeChat-tool compilation, device operation, upload or cloud acceptance. Keep those readiness fields separate.
- Local loopback packages are for the developer-tool simulator. Experience packages require a registered AppID and verified HTTPS request domain with domain checks enabled. No AppSecret in the client; cloud hosting and platform inputs are still pending.

## Native waitlist and service centre (B1.5.3)
- Website and native summaries remain own-patient projections. Front desk owns publication; patients explicitly choose additional booking or exact-source replacement. Decline/withdraw never cancel an existing visit.
- Native registration uses the existing patient lock and immutable audit receipt for operation replay; a withdrawn result is returned as current history and never revived. No new table or migration.
- Native offer/withdraw confirmations recheck request revisions under the coordination module's existing locks; shared rescheduling owns unique successors and receipts. Preserve retained service labels from resource snapshots.
- Page handlers plus real HTTP/Chrome and offline compilation do not establish WeChat runtime or cloud acceptance.

## Native service journey (C0.2 source candidate)
- `docs/C02_NATIVE_SERVICE_PLAN.md` records the plan and release boundary;
  `docs/evidence_c02/verification.json` records execution separately.
- Native discovery/detail reuse complete explicitly published operational profiles.
  New candidate, booking and waitlist requests require a published non-child service.
  No raw active-service exposure or invented generic fallback in new-booking UI.
- Native confirmation passes an internal publication guard to the shared booking
  effect; it runs after physical locks and before Visit/claim writes. Ordinary
  receipt replay returns current history before that gate. Do not turn the flag
  into an HTTP option or apply marketing publication to retained offers/reschedules.
- Waitlist confirmation follows patient then physical locks and rechecks the
  signed publication revision/current profile; successful receipt replay precedes
  those new-request checks. Withdrawal/republication cannot revive a stale preview.
- Patient request text is signed in preview, never taken from raw confirmation,
  never logged, and shown only in existing authorized visit projections. Own-visit
  rescheduling projects its retained service separately from public discovery.
- All 40 current migrations are unchanged. Source/page-handler checks are not
  PostgreSQL, official compilation, device or installed-release acceptance.

## C0.3 executed local acceptance and target transition

2026-10-23 follow-up: read `docs/C03_RELEASE_ACCEPTANCE.md` and `docs/evidence_c03/`. Application `3b78cc5f430f18411bf50e4314f287b2c95666a0` passed exact CI (1,095 rules/1,474 PG cases), five-clinic exact-image Chrome/native-handler acceptance, independent same-version encrypted restore, and a protected copy upgrade of the original database. Port18000 has been updated to that image. New local synthetic service descriptions were explicitly created through manager commands, with documented policy revisions and original clinical/money rows preserved. The earlier C0/C0.2 NOT_RUN and port18000-old-baseline statements describe their original dates; they are superseded for these executed scopes by C0.3 records.

Current observed structure is 70 tables/171 SQL FKs/42 triggers after all40 current migration files (39 original bytes preserved). ER, DBML, field/FK catalogues and the fixed-name formal report are current; report has 59 business cases plus SF-01. Public educational guides use `/care/guides/<category>/`; never reintroduce a greedy string route before numeric `/care/<visit>/` clinical handling. The public large-text preference shares `experience.js`; no inline-CSP exception is needed.

The previous inability to verify GitHub target authorization was resolved in this session by authenticated read-only identity/ADMIN verification and an approved normal fast-forward push. Do not generalize that to new destinations or public data. Local synthetic service acceptance does not complete C0/C1 or qualify clinical replacement. WeChat runtime/device/experience, actual cloud, new-version capacity, continuous operation and professional acceptance remain separate; Windows-original recovery is UNRESOLVED. Preserve the archived old observer UNKNOWN history.

## C1.1 patient subjects and relationship verification

C1.1 supersedes earlier self-only patient-channel statements only for appointment actions in an explicitly verified clinic-scoped grant. Read `docs/C11_IDENTITY_CONTRACT.md` and `docs/evidence_c11/`. Preserve all40 prior migrations and all43 current files. PatientAccess remains self-only; relation/contact/account/appointment grant/clinical consent are separate. Only current-clinic FRONT_DESK with explicit can_verify_patient_relationships may verify. Technical governance assigns the duty; it does not verify relationships. Website and native use portal.policies, selected WorkspaceContext and grant revision; recheck under existing appointment locks. Delegates cannot read clinical text or invoices. Revocation preserves existing appointments. New tables and ER must remain aligned. Local evidence, exact CI, installed update and WeChat/cloud/professional acceptance are separately recorded.

C1.1 protected installation is executed: application `edcb6eb2b89ee54375afd24ea7cff364df7b87a2` passed exact CI, same-image five-clinic acceptance, encrypted73-table restore, original-copy additive upgrade and port18000 verification. Preserve old UNKNOWN observer history; new monitoring has fresh HEALTHY samples. The explicitly synthetic local additions are one delegate account, two front-desk verification duties and two relationship grants; credentials stay private. Detailed evidence and remaining WeChat/cloud/professional gates are in `docs/evidence_c11/release.json`.

## C1.2 professional scope and controlled referral

C1.2 is locally delivered with application `3ff5383161b5e856f8b8178bb07e1c97e2a07fbb` and its exact passing CI. Read `docs/C12_AUTHORITY_CONTRACT.md` and `docs/evidence_c12/release.json`. Preserve all44 current migrations (previous43 unchanged), all80 tables and existing data/configuration. Every new C2 clinical command always requires current exact clinic/service/action authority. Source evidence and qualified reviewer responsibility are distinct; synthetic decisions cannot authorize non-synthetic care. Referrals disclose only their selected published version after identity and named-receiver acceptance; appointment delegates have no clinical consent/read/termination authority. Sensitive-read metadata contains no clinical/contact text. The original local additions are two explicitly synthetic reviewer duties, ten bounded scopes and two retained activations through normal commands, without new patients/appointments/treatment/cash. Historical UNKNOWN gaps remain; safe stage diagnostics never establish their old root cause or close them automatically. C2.1–C2.3 remain required active work; do not label the complete objective achieved on this release.

The C1.2 host-only follow-up `1fa2e2d058bc3581bd3518b7ff086fb9744e8000` passed exact CI and is installed. The business image remains the accepted `3ff5383161b5e856f8b8178bb07e1c97e2a07fbb`; all603 application feature files, images, database and private configuration are unchanged. Diagnostics retain only fixed stage/category plus timestamp. The original UNKNOWN cause remains UNDETERMINED and its incident/history is retained. Details: `docs/evidence_c12/host_diagnostic_install.json`.

## C2.1 structured clinical workspace

C2.1 source and isolated synthetic acceptance are implemented; exact release status is in `docs/evidence_c21/`. Preserve all45 current migrations, especially all44 prior bytes. Actual observed structure is86 tables/225 SQL FKs/56 triggers, not a production qualification. Own self-history and each clinic's interview are independent version ledgers; appointment delegates cannot report/read clinical history. Every new C2 mutation and projection requires strict current professional action scope, including synthetic preactivation. Start only after actual check-in; never fabricate old encounters. Draft saving, explicit preview/confirmation and retained amendments cannot create treatment or money. Conflicted forms preserve entered work and require explicit current-fact comparison before resubmission. Existing care closure checks the confirmed record/history cursor. Structured referral selects one retained version and reuses C1.2 identity/consent/receiver/termination. C2.2 plans/typed charges and C2.3 recall/lab remain required active work, with their new capacity acceptance separate.

C2.1 protected delivery is executed: application `e688b4a933d4a65a01ba7be8c6968e6145f2f0a3`, exact CI1,101 rules/1,592 PG cases,328 same-image browser/native checks,86-table populated recovery and77-model original-copy/preservation. Port18000 uses the accepted image. Host-only safe action projection `8e67f756bab128968fa52e013a4cfc7b60e71e1e` passed exact CI1,104/1,592 and is installed; all623 application feature files and images remain unchanged. Unknown exec actions become a fixed label while every event row remains counted, preserving the existing saturation rule. The UNKNOWN incident, gap acceptance, repair and fresh-sample closure remain retained. Report144pages/71business cases+SF-01/11actualERs. C2.2–C2.3 and their final new capacity workload remain required active work; do not complete the whole objective here.

## C2.2 continuity source checkpoint

C2.2 is an isolated source candidate; read `docs/C22_CONTINUITY_CONTRACT.md`. All45 prior migration bytes remain unchanged. Two additive migrations add ten clinical continuity tables and extend, rather than remove, final-care invariants. The dated candidate observation is96tables/264SQLFKs/67triggers; the installed C2.1 ER/report remain their dated baseline pending combined C2.2–C2.3 delivery. Plan estimates and version decisions never post money. PerformedProcedure owns one original typed charge and retained snapshot; reviewed bill copies do not create another actual event. A reasoned accepted ON_COMPLETION/PARTIAL stage is actual TREATED care without a charge line; it is neither NO_TREATMENT nor a doctor fee waiver. Front desk gets the minimal service/date/arrangement projection and immutable links to normal appointments. Appointment delegates have no clinical plan authority. C2.3 recall/readiness, full exact release gates and the final new capacity workload remain required active work.
