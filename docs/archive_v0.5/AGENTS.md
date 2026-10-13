# ADC v0.5 engineering rules

This is a synthetic course demonstrator, not a medical product. Chinese UI, Django server templates, PostgreSQL invariants.

- Preserve original v0.3 migrations, .env, database volume/project name and history. New model changes require additive reviewed migrations.
- All ordinary business writes use explicit confirmed POST forms, CSRF, service authorization, row/version concurrency protection and atomic transactions. AI must never execute writes/SQL/tools.
- PatientAccess is an explicit identity binding. Patient number/phone does not authenticate. Do not infer authorization from client IDs or frontend visibility.
- Published care versions/lines cannot be overwritten. Logical Invoice is one per closed Visit. No-treatment = attended, empty lines, zero invoice, mandatory reason. Do not fabricate clinical facts.
- AI provider receives only the consented, best-effort-redacted question. Do not send ORM contexts or record summaries. Reauthorize after network calls. Store metadata only, not prompts/responses/keys.
- Model outputs are untrusted allowlisted intent + bounded score. Output schema, no redirects, explicit fallback, fixed quotas, no automatic retries. Never label the demo rule engine as remote AI.
- Never put API keys in HTML, JS, screenshots, archives, code comments or logs. Backend env only. Never read or print user .env unnecessarily.
- Standard/large modes are a user preference, never automatic age profiling. Preserve keyboard and non-JS business flows. Only local browser speech voices, no audio recording/upload.
- Run 147 pure/static/contract checks then Django check, migration consistency, migrate, and 143 real PostgreSQL tests. Counts are the authored baseline and may change with additions; actual results must be recorded.
- Static browser fixtures are not Django or live API evidence. Keep execution boundaries explicit. Production settings remain blocked pending deployment-specific acceptance.
- Current backlog: appointment-terminal corrections, broader clinical/invoice correction (numeric line correction only is implemented), full directory/account administration, verified patient issuance, public hosting and backup restoration tests. Do not claim them implemented because models exist.

- Use the public care.ledger read contract in finance. Keep reporting snapshots read-only and outside nested transactions.
- Finance is billed revenue, not cash. Missing costs/off-roster earners block profit and fund; zero/negative fund policy remains undecided.
- Numerical correction prepares an immutable-history full version; an independent finance reviewer publishes it atomically. Never overwrite prior versions or sum both.
