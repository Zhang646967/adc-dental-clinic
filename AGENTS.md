# ADC v0.9.0-alpha.10 engineering rules

Synthetic local course demonstrator; not a medical, payment or public-production product.

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

19. Host migration is ON HOLD. Do not invoke export, restore, cutover or a user-instance upgrade without explicit next-stage authorization. Existing migration tools stay unchanged.
20. SU-27/28 is SYSADMIN/current-workspace-only bounded directory registration and qualification-record association, not clinical verification or a general CRUD editor. Keep code uniqueness, preview-before-save, password/confirmation checks, signed context binding, audit-cursor ABA protection and replay guards. No automatic accounts, grants, appointments, scheduling eligibility or history rewrites. No deletion or renaming.

## Availability maintenance (alpha.6)
- Only current-clinic MANAGER; an assigned role is not the active role.
- Stop/replace only future effective source slots without protected visits or effective holds.
- Never rewrite original interval/clinic/dentist or delete history; replacement uses a new row.
- Maintain actor/context/grant/source-slot lock ordering and retain original exclusion constraints.
- Record true test scope: static/template/AST tests do not prove ORM/HTTP/PG behavior.
- Mac migration remains paused; the user's v0.7 instance must not be overwritten implicitly.

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
- SU34/35/36 add a workflow record only. No implicit slot pause/resume, appointment cancellation, offer answer, care change or patient notification.
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
