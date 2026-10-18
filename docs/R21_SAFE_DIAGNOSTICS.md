# R2.1 request tracing and safe operational logs 请求追踪与安全运行日志

Server reference → protected business command → safe result record → private
diagnosis. R2.1 implements R2-01/02 and size-bounded operational storage from
[the R2 plan](R2_OPERATIONAL_ASSURANCE_PLAN.md). The complete R2 release remains
in progress; worker monitoring, incident management and continuous recovery
freshness are later increments.

## Request and error behavior 请求与错误处理

Every Django request receives a new 32-character server-generated hexadecimal
reference. Incoming `X-Request-ID` and similarly named headers cannot choose it.
The response returns `X-Request-ID`; proxied gateway logs and Gunicorn access
events retain that same reference. The gateway generates its own reference for
requests rejected before reaching Django, including rate-limit responses.
Discarded connections do not promise an HTTP response.

The outer observer wraps the existing middleware in its original order. It does
not read request bodies, select a workspace, query grants or interpret a reference
as permission. Context is reset in `finally`; Django's later response-warning
records reuse the immutable server context attached to that request. Streaming
bodies are not consumed or rewritten.

Generic 500 pages display the reference and ask staff to check stored records
before repeating a potentially completed action. CSRF failures, workspace
denials, business problem pages and failed confirmation forms also provide a
reference. The 500 renderer avoids navigation/context processors and database
queries. References wrap in narrow large-text layouts and keyboard navigation
remains available.

A request reference is **not** a receipt, approval, business operation ID or
idempotency key. Duplicate confirmations still use their original transactional
replay checks. A successful HTTP response is distinct from payment posting or
independent review.

Mind map: new server ID → existing authorization/transaction → response and private
events → stored-state check; client headers and support references grant no access.

## Event contract and log inventory 日志字段与出口

The application formatter never calls `getMessage()`, formats arbitrary arguments
or renders an exception/traceback. Its allowlist contains a schema version, UTC
time, severity, service, identified source commit or `unknown`, finite event code,
server reference, resolved route name, normalized HTTP method, status and bounded
duration. Only finite exception categories are retained. Role/clinic/actor fields
are omitted; adding logging does not require new permission queries.

| Exit | Retained content and control |
|---|---|
| Django application/framework | Safe JSON for request outcomes, authentication results, authorization/security errors, generic failures and captured Python warnings; no mail-admin error payload |
| Gunicorn | Safe JSON access and server events; access references come from the server response, not incoming headers; raw message/exception text is discarded |
| Nginx | JSON method/status/duration/reference for every configured virtual server; method is allowlisted and native request-error text is disabled |
| Notification worker | Existing aggregate outcome counts and bounded stop notices remain compatible; runtime command failures use safe codes |
| Runtime management stderr | Safe warning/failure events, preserved exit status; arbitrary CommandError/exception text is not printed, including explicit traceback requests |
| Database | Native Docker log capture disabled; PostgreSQL primary errors can quote submitted values even with DETAIL/SQL logging reduced. Application DB failures retain a safe category |
| Account bootstrap | Dedicated explicit maintenance service with capture disabled; generated credentials go to the existing private file |
| Tests, backups and interactive operator tools | Separate private/synthetic execution evidence, outside the application event stream; dump/restore and credentials remain private |

No usernames, names, patient/object identifiers, submitted URLs/query strings,
form fields, CSV contents/references, notes, cookies, authorization headers,
signed previews, connection strings, SQL parameters, unrestricted exception text
or locals are operational fields. No sensitive-read audit or ASVS conformity is
claimed by route-level technical logging.

An operational sink failure emits at most a bounded constant fallback and cannot
change an allowed/denied business result. A required transactional business-audit
failure still rolls back the command. Docker/host access remains a private
operator responsibility; SYSADMIN gains no clinical or log-reading authority.

Mind map: finite event vocabulary → allowlisted metadata → bounded private sinks;
financial audit → independent retained business history; native text → suppressed.

## Retention and operational trade-offs 保留策略与取舍

Captured RC and G4 candidate services use Docker's `local` driver, `max-size=10m`
and `max-file=3`; nominal storage is three 10 MiB files per container, with driver
overhead and compression behavior. Bootstrap and database capture are disabled.
Rotation was exercised in a dedicated disposable container; truncation is an
expected storage bound, not a promise of complete history.

The earlier seven-day maximum was a **proposed** default. Docker's native driver
offers size rotation, not a time-expiry option. This increment explicitly adopts
size-based retention and does **not** claim seven-day deletion. A strict time
policy/export design remains a recorded R2 follow-up. Seven/thirty-day encrypted
backup retention remains a separate, unchanged policy.

Suppressing native database and gateway error strings reduces forensic detail.
Use the safe outcome, reference, route, source version and current readiness to
begin diagnosis. A separate protected/redacted collection system and its access,
failure and retention controls need their own acceptance; local Docker logs are
not described as immutable or independent storage.

Mind map: measured size rotation → explicit truncation; time expiry and protected
collection → follow-up contract; operational logs and backup retention stay distinct.

## Verification and traceability 验证与需求对应

[Executed local evidence](evidence_r21/README.md) separates regression, browser,
runtime sinks, gateway checks, financial oracles and encrypted restoration.

| Requirement | Verification |
|---|---|
| R2-A01 reference/context isolation | `tests/test_request_tracing.py`: forged headers, eight parallel mixed success/failure requests, delayed framework warnings, streaming and DB-free error rendering; real parallel Chrome requests |
| R2-A02 safe sinks and failures | `checks/test_operational_logs.py`: hostile messages/args/extras/exception strings and failed writers; HTTP secret markers, real Gunicorn/Nginx/worker/command checks; optional logging failure versus required audit rollback |
| R2-A10 permission preservation | Seven-role and foreign-clinic/revoked-grant HTTP tests; five-clinic real-browser cash/evidence/equipment and cross-clinic probes |
| R2-A06 storage component | Real production-size rotation in a disposable no-network container; no real-disk-full injection or incident-monitor acceptance |
| Recovery and release protection | Separate empty PG17 restore with binary-content fingerprints; exact-version CI, encrypted Mac backup and original data/configuration comparison |

There are no new migrations, business APIs, roles, automatic approvals, heartbeat
or monitoring endpoints. The original 30 project migration files and RC1 report
remain intact. R2's 30-minute capacity repeat and 24-hour observation belong to
R2.4; R1's historical five-clinic baseline is not relabeled as an R2 result.
Cloud hosting and original Windows-data recovery retain their pending statuses.

Mind map: adversarial request → private runtime sinks → seven-role business facts
→ independent money calculation → encrypted empty-target restore → protected release.

## Private operator procedure 维护人员操作

Use the existing instance status command to identify its own web, gateway and
worker containers. With private host access, read a bounded recent interval of
those containers and locate the reference from the screen/response. Compare
`http.*`, `framework.*`, `server.access` and `gateway.completed` events for that
reference. Older deployments retain their historical logging behavior.

Check the actual business state through the authorized workspace before resuming
work. A reference or alert cannot post money, change a bill, approve a match,
reassign an appointment or bypass a revoked grant. Keep exported diagnostics
private and bounded. Never attach credentials, database dumps or CSV source
contents to an operational report.

Primary mechanisms: [Django middleware](https://docs.djangoproject.com/en/5.2/topics/http/middleware/),
[Django logging](https://docs.djangoproject.com/en/5.2/howto/logging/),
[Docker local driver](https://docs.docker.com/engine/logging/drivers/local/).

Mind map: reference → identified private container → bounded event search →
authorized state check → explicit recovery; no automatic business action.
