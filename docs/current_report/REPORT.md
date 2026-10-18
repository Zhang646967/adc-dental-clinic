# ADC System Development Report

R1 delivery and R2 implementation plan 系统开发进展与下一阶段规划

Report date 2026-10-18   Application baseline 6a06f35   R2 status PLANNED

## 1 Current release and next decision 当前版本与下一步

R1 financial evidence is delivered on the Mac and in GitHub. The next implementation is R2 operational assurance（运行保障）: explain failures safely, detect stalled work and stale recovery copies, then rehearse a controlled recovery. Keep the current transactional Django and PostgreSQL architecture while strengthening module contracts.

The agreed product is one dental chain with approximately 5-20 clinics. Existing capacity evidence covers five clinics on this Mac. The system continues to use synthetic data（合成数据）, CNY and Asia/Shanghai business dates; external AI is disabled. The new plan does not establish twenty-clinic capacity, independent hosting or commercial readiness.

This report updates the system analysis, delivery evidence and next implementation sequence as of 18 October 2026. The application observations below were accepted on 15 October 2026 at commit 6a06f35 [3-4]. R2 requirements and thresholds are proposed work, not newly executed tests.

| Area | Current position |
| --- | --- |
| Application | R1 payment evidence and independently reviewed reconciliation delivered |
| Regression | 908 source checks; 1,106 PostgreSQL/HTTP/concurrency tests |
| Browser | 2,423 isolated checks; 205 further checks on the updated Mac |
| Capacity | Five clinics, twenty accounts, 30 minutes; 9,000 requests |
| Recovery | 50 model/association fingerprints match after encrypted empty-target restore |
| Next coding batch | R2.1 request correlation and safe structured operational logs |

Cloud acceptance awaits private server and hostname inputs. The original Windows database recovery remains unresolved. The frozen RC1 report remains the historical design record; this report is the current development and planning companion.

Mind map 思维导图: ADC → delivered R1 {money evidence, permissions, recovery} → planned R2 {diagnosis, observation, response} → independent host and measured expansion.

## 2 Business workflow and module ownership 业务流程与模块职责

The main patient journey connects booking, arrival, dentist care, actual treatment, the versioned invoice, receipts or refunds and financial review. Equipment repair connects a responsible work order, another manager’s acceptance, a service event and separately reviewed expense. Existing appointments and scheduling decisions retain their own protected commands.

Seven workspaces（工作身份）separate function, clinic and record authority. A person with multiple grants activates one role at a time. A role switch does not allow self-review or combine permissions. Clinical records, money and equipment rules remain inside their owning module; callers use defined operations [1-2].

| Role | Responsibility and boundary |
| --- | --- |
| PATIENT | Own appointments, invoice projection and authorized portal actions |
| FRONT_DESK | Current-clinic reception, booking and invoice-related receipt/refund evidence |
| DENTIST | Assigned clinical work and actual treatment; no independent finance approval |
| MANAGER | Current-clinic equipment, schedule coordination and reconciliation proposals; limited money projection |
| FINANCE | Channel configuration and independent money/evidence/match review under chain authority |
| HQ | Authorized aggregate reporting; no detailed statement or patient access from reconciliation |
| SYSADMIN | Account and directory governance; technical privilege does not grant clinical access |

Billed revenue, cash received, equipment costs and approved refunds are distinct facts. Missing cost is distinct from confirmed zero. Suggestions are not appointments, an inbox commit is not human agreement, and an approved daily handover is not proof of external channel settlement. Operational monitoring must preserve each distinction.

Mind map 思维导图: Patient journey → appointments and care; money → invoice, cash and independent review; equipment → repair evidence and explicit scheduling; identity → active role, clinic and object authority.

## 3 R1 financial evidence closure 资金凭据与逐笔对账

Finance establishes stable clinic-specific channel accounts. New receipt, refund, equipment-expense and reversal requests bind the account and reference into a signed preview. The cash entry and first evidence version are saved atomically; a different finance account decides whether to post. Legacy entries keep an explicit missing-evidence status until a separately reviewed supplement is supplied.

Managers upload private UTF-8 CSV statements with six v1 columns, at most 2 MiB and 1,000 rows. Source bytes, digest, parser version and normalized rows stay in the database. Confirmation uses a server-held preview and reparses the source. Exact repeats are reported and skipped; a conflicting transaction identity rejects the entire acceptance.

| Step | Invariant |
| --- | --- |
| Propose matching | Same clinic, account, CNY currency, direction, amount and current approved reference |
| Independent review | Different account; current grants and source facts rechecked under locks |
| Active correspondence | One statement line to one POSTED cash entry; database uniqueness and transactional rechecks |
| Correct evidence | Append a reviewed version; invalidate the affected active match and retain its decision |
| Handle differences | Keep missing evidence, fees, combined deposits and unsupported allocations visible |
| Daily handover | Keep four gross internal totals separate from current channel matching and next-day settlement |

Importing or matching never posts money, changes an invoice or invents a balancing entry. The five-clinic browser scenarios cover partial receipts, refunds, equipment payments/reversals and evidence correction. After additional load-time review, 29 matches are confirmed and one prior decision remains stale; 5,031 statement lines are retained. Those are deliberately bounded synthetic scenarios, not a real reconciliation coverage rate [3].

Mind map 思维导图: Authorized account → signed evidence → retained CSV → exact proposal → different reviewer → readable differences/corrections; internal handover and channel settlement remain separate.

## 4 Executed evidence and its scope 已执行验证与适用范围

R1 separates source checks, database behavior, real-browser interaction, resource observation and independent recovery. The published acceptance record contains positive and adverse cases, retained failures and the final corrected results [3]. Assertion counts describe executed checks, not coverage percentages.

| Check | R1 observation |
| --- | --- |
| Regression | 908 source checks; 1,106 PostgreSQL/HTTP/concurrency methods; 41 new R1 database methods |
| Browser | 2,423 isolated assertions; seven roles and foreign-clinic probes before, during and after load |
| Mixed load | 9,000 requests: 7,200 reads and 1,800 valid writes across twenty accounts |
| Latency and resources | p95 0.337 s; maximum 0.7315 s; no unexpected failure, duplicate effects, OOM, restart or deadlock |
| Independent writes | 900 unique patient creations and 900 exact draft-note saves; original money/invoice facts unchanged |
| Ancillary work | Five 1,000-row imports and five independent match approvals inside the measured window |
| Recovery | 50 model/association fingerprints match; recorded local restore-and-compare interval 2.556 s |
| Mac protection | 43 original models and 70 private configuration files preserved; RC tag retained; 205 browser checks |

The independent financial oracle retains receipts of CNY 50,100.10 and refunds of CNY 100.10, giving net patient cash of CNY 50,000.00. Equipment expense and reversal are CNY 50.05 each. Imports and matching do not change these amounts.

The workload uses Linux containers on a Mac with limits totaling two CPU cores and 1,728 MiB. It does not reproduce an independent 2 GB cloud server. The RC owner database identity was used; production runtime-role separation was not measured. Keyboard preview/explicit confirmation and 390px large-text layouts were checked; native macOS menu option selection was not automatically verified.

Mind map 思维导图: Layered tests → independent money facts → continuous workload and resources → separate encrypted restore → exact-commit CI → original Mac preservation.

## 5 R2 business requirements 运行保障业务需求

The next problem is operational responsibility. When a front-desk settlement fails, staff need a safe support reference and a clear instruction to check stored state before resubmitting. When coordination notices stop, the operator needs to distinguish an idle worker from an unavailable database or overdue work. When a backup exists, the owner needs its real recovery point and restoration evidence.

The requirements note makes the expected outcome testable rather than describing the system as merely reliable [1]. Each R2 requirement therefore specifies an actor, an observable condition, a protected invariant, a failure response and an acceptance case.

| Requirement | Observable result and protected invariant |
| --- | --- |
| R2-01 / 02 | Server request ID and safe JSON events; no secret, clinical, CSV or submitted URL/body data |
| R2-03 | Bounded logging and documented access/retention; financial history is not pruned as operational noise |
| R2-04 / 05 | Fresh worker-loop success and indexed due-backlog age; future retry and human read stay distinct |
| R2-06 | Private HEALTHY/WARNING/CRITICAL/UNKNOWN state; acknowledgement never clears the underlying fault |
| R2-07 / 08 | Separate backup, verified download and independent restore points; original running database is protected |

Use private operator commands/files first. The platform operator diagnoses infrastructure; authorized clinic staff resume their workflow and finance verifies money independently. This adds no business role, public metrics endpoint, new business REST API or automatic financial action. SYSADMIN remains an account-governance role, distinct from private host access.

Keep the modular monolith（模块化单体）and existing worker. Do not introduce a large monitoring stack or separate services before their resource and ownership need is demonstrated. Business audit and operational logs have different responsibilities [2,5].

Mind map 思维导图: Failure → actor and observable symptom → protected business invariant → explicit response → acceptance; operator, clinic and finance responsibilities stay distinct.

## 6 First implementation batch 首轮实施合同

R2.1 will implement request correlation and safe structured operational logging. At request entry, the server generates the support ID and returns it in X-Request-ID. A client header cannot choose that ID. Completion and safe failure events share the same request context; concurrency and exceptions must not leak context between requests.

The JSON vocabulary allows UTC time, severity, service, reviewed source commit, event code, request ID, route name, HTTP method/status and duration. Role/clinic metadata requires a validated current workspace. Metric labels must remain bounded; request IDs and business identifiers must not become labels.

| Contract | Implementation and check |
| --- | --- |
| Context ownership | Separate adc_core request context/middleware; preserve existing security middleware ordering |
| Log minimization | Allowlist fields; bounded reason/exception codes; cover framework, gateway and worker sinks |
| Safe failure | Show generic error plus support reference; never SQL, credentials, tokens or internal payloads |
| Atomic business behavior | Logging failure cannot widen authority or rewrite success; required audit failure still rolls back business |
| Storage | Proposed 10 MiB × 3 files per container; at most seven days, possibly earlier size rotation |
| Verification | Forged header, parallel requests, denied access, secret markers and log I/O failure cases |

Do not log names, entered usernames, request bodies, CSV bytes/references, treatment notes, cookies, authorization headers, signed previews, workspace tokens, raw object paths or unrestricted exception messages/locals. Log encoding must prevent injection. Keep business audit as the authoritative retained history [6-8].

This batch needs no business schema migration. Before delivery, run targeted and existing regression tests, exercise affected login/settlement/evidence/equipment error paths in Chrome, require passing exact-commit CI and compare original Mac data/configuration after the protected update.

Mind map 思维导图: Server correlation → allowed metadata → safe errors → encoded private bounded logs → parallel/adverse tests → preserved financial audit and permissions.

## 7 Observation and recovery targets 监测与恢复目标

The following values are proposed engineering defaults for testing. They are not achieved service-level results. Sample every thirty seconds and report stale or missing observations as UNKNOWN. An idle worker is healthy when its database-backed loop is current and no overdue eligible events exist.

| Signal | Initial rule |
| --- | --- |
| Web/database readiness | Fault after two failed samples; recovery after two successful samples |
| Worker success | Stale after 90 seconds when a writable worker is required |
| Due notification age | Over 120 seconds; use PENDING rows already due, not future scheduled retry |
| Observer freshness | Over 90 seconds, invalid clock or foreign instance means UNKNOWN |
| OOM/restart | Any new event retains an incident even when current health recovers |
| Storage | Warn below 20% free; critical below 10% or 1 GiB free |
| Recovery points | Warn after 26 hours for daily server backup or verified off-host source point |
| Independent restore | After deployment and weekly; age warning after eight days; bind backup digest and commit |

Track backup creation, verified Mac download and independent restore separately. A repeated check/download never advances the original backup timestamp. Keep seven server days and thirty Mac days; a corrupt file must not cause pruning of a valid recovery point. A sleeping Mac leaves the off-host recovery point at its last verified download.

Recover only into a distinct empty target with matching source/image/schema provenance. Compare accounts, grants, business/association rows, all four cash legs, evidence versions, original CSV byte digests and match history. Target thirty minutes after the replacement environment is ready. R1’s 2.556-second local interval does not promise cloud replacement time.

A proposed seven-day technical availability objective is 99.5%; report 4xx/409/429 separately. Functional acceptance still rejects an unexpected 403 or other wrong business outcome. Empty traffic is not 100% availability. Repeat the existing thirty-minute mixed-load gate with p95 within five seconds and measure observer/logging overhead.

Mind map 思维导图: Worker + due queue + observer freshness → explicit condition; created → downloaded/decrypted → independently restored point → actual recovery exposure.

## 8 Development sequence and completion gates 开发顺序与验收

Develop R2 in bounded increments. Each increment must preserve original data, history, role scope and independent finance review. Destructive fault injection belongs only to an identified disposable rehearsal, with failed attempts retained.

| Increment | Deliverable and completion gate |
| --- | --- |
| R2.1 Safe diagnosis | Request context, safe JSON logs and inventory; parallel/privacy/error acceptance |
| R2.2 Worker observation | Heartbeat, due-age, private collector and incident lifecycle; prove observer failure is visible |
| R2.3 Recovery freshness | Separate backup/download/restore receipts; corrupt/wrong-key/stale-copy and empty-target recovery cases |
| R2.4 Local release | Security gap review, fault runbooks, seven-role browser/load checks and 24-hour local observation |
| R2.5 Cloud release | Independent HTTPS host; mainland access, Mac offline, restart, renewal, backup/recovery and 24-hour gates |

- Inject database unavailability, stopped/terminated worker, future retry, monitor failure and simulated storage pressure without modifying the running Mac.
- Verify deduplicated incident opening, acknowledgement and sustained recovery; acknowledgement changes responsibility, not condition truth.
- Check corrupt archives, cached copies with a wrong key and interrupted downloads; preserve previous valid points and all source business records.
- Repeat five-clinic/twenty-account valid mixed work with import/review activity, no unexpected statuses/duplicate effects/OOM and p95 within five seconds.

The full R2 plan defines R2-A01 through R2-A12 and their independent observations [9]. Local R2 acceptance and cloud acceptance have separate statuses. After R2, keep the agreed sequence: R3 longitudinal treatment plans, R4 resource/maintenance coordination, then R5 measured twenty-clinic expansion.

Mind map 思维导图: Diagnosis → worker/observer → recoverable points → local fault evidence → independent host; later care continuity → shared resources → measured expansion.

## 9 Security assessment and release boundaries 安全差距与发布边界

Pin the security assessment to OWASP ASVS 5.0.0. Existing route, grant, object and deidentified-projection tests support an assessment; they do not constitute a standard-wide pass. The new register distinguishes evidence needing review, gaps, actual-host dependencies and product exclusions [6,10].

| Area | Current assessment direction |
| --- | --- |
| Logging and errors | R2 targets inventory, correlation, time, minimal data, encoded events and safe failure |
| Log protection | Private access/rotation must be verified; separate protected collection remains a deployment gap |
| Authorization | Review existing seven-role/function/object/field tests against the complete requirement scope |
| Sessions and MFA | Lifetime/concurrency, session inspection, factor changes and MFA need their own contracts/assessment |
| Customer isolation | One chain’s clinic isolation is not independent customer tenancy |
| Public operation | Needs server IPv4, SSH user/key path, independently verified host fingerprint and owned hostname |

This revision delivers the current report and development plan. Deployment credentials and recovery keys remain private. The application continues to use synthetic data, and the documentation update requires no application restart.

A local observation window cannot prove mainland access, certificate renewal, service while the Mac is offline or replacement-host recovery. Complete those on the actual independent host before declaring the course online release ready. Original Windows-data recovery remains unresolved.

Mind map 思维导图: Versioned security requirement → existing evidence and explicit gap → targeted work; private server inputs → actual host tests → separately accepted public operation.

## 10 References and report provenance 参考资料与报告来源

The course notes supply the requirements and design framework. Official engineering references guide the proposed R2 contracts. ADC records establish the executed R1 results. The proposed thresholds and development sequence are project decisions, not performance claims made by the reference systems.

Report revision date: 2026-10-18 in the project owner’s client date context. R1 evidence date: 2026-10-15 UTC. Aggregate Mac delivery records establish the 43-model/70-configuration preservation and 205-browser-check summary; private keys, credentials, dumps, CSV source contents and private deployment configuration are excluded from this report.

Editable report_source.json and build_report.py generate the Word and Markdown texts; PDF pagination is visually checked after export. The original 63-page RC1 report, original migrations and original RC tag retain their historical identities.

[1] Course note 3 Requirements and specification. Supplied project material, physical page 5 on testable observable requirements.

[2] Course note 5 Software design principles. Supplied project material, physical pages 4-5 and 8 on separation, simplicity, restricted visibility and information hiding.

[3] [ADC R1 executed acceptance](https://github.com/Zhang646967/adc-dental-clinic/blob/6a06f356a0c4697f5b8afe2736ed62d427512806/docs/evidence_financial_evidence/acceptance.json). Immutable application baseline; synthetic local scope.

[4] [Exact R1 application commit CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/38728944434). Successful workflow for commit 6a06f35.

[5] [Google SRE workbook Monitoring](https://sre.google/workbook/monitoring/). Purposeful observation and testing the monitoring/alerting path.

[6] [OWASP ASVS official project and stable standard](https://owasp.org/projects/asvs). Assessment is pinned to 5.0.0; requirement links are in the ADC register.

[7] [Django 5.2 logging configuration](https://docs.djangoproject.com/en/5.2/howto/logging/). Application logger, formatter and handler mechanisms.

[8] [Docker logging configuration](https://docs.docker.com/engine/logging/configure/). Explicit bounded logging-driver configuration.

[9] [ADC R2 operational assurance plan](https://github.com/Zhang646967/adc-dental-clinic/blob/main/docs/R2_OPERATIONAL_ASSURANCE_PLAN.md). Implementation contracts and R2-A01 through R2-A12; planned.

[10] [ADC versioned security gap register](https://github.com/Zhang646967/adc-dental-clinic/blob/main/docs/SECURITY_ASVS_GAP_REGISTER.md). Scoped assessment work, not ASVS certification.

Mind map 思维导图: Course requirements/design → official engineering references → immutable R1 observations → proposed R2 contract → executed future evidence.
