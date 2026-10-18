# Security assessment register 安全验证差距登记

Business permissions → security requirements → evidence review → targeted repair
→ independent assessment. Baseline date: **2026-10-18**; application commit
`6a06f356a0c4697f5b8afe2736ed62d427512806`.

This is a scoped planning register against **OWASP ASVS 5.0.0**, not a completed
assessment or Level 2 conformity claim. Requirement identifiers are pinned to
that tag, because newer standards can move or change them. Short topic labels
below summarize controls; use the official text for a real assessment. R2 aims
to establish evidence for its operational/logging subset. MFA, broader session
governance, read auditing and separate protected log infrastructure require
explicit follow-up contracts.

Status meanings: **EVIDENCE_TO_REVIEW** means relevant ADC controls/tests exist
but have not been assessed against the complete requirement; **GAP** means the
reviewed baseline lacks the stated end-to-end contract; **TARGET_ENVIRONMENT**
requires the actual independent deployment; **OUTSIDE_PRODUCT_SCOPE** is a
product-boundary decision, not a passing test.

R2.1 update: [safe diagnostics](R21_SAFE_DIAGNOSTICS.md) and
[executed local tests](evidence_r21/README.md) now support the logging rows below.
Those rows move to evidence review, not automatic ASVS passes. Size rotation is
verified; strict time expiry and separate protected collection remain gaps.

## Logging and error assessment

| ASVS 5.0.0 | Topic | Baseline status and evidence | Planned action and acceptance |
|---|---|---|---|
| 16.1.1 | Logging inventory | EVIDENCE_TO_REVIEW; R2.1 versioned sink/retention inventory and separate business audit | Inventory all sinks, events, owners, access and bounded retention; R2-A02/A06 |
| 16.2.1 / 16.2.4 | Useful metadata and correlation | EVIDENCE_TO_REVIEW; R2.1 server context and delayed-framework/parallel/real-proxy checks | Versioned JSON allowlist, server request IDs and cross-request tests; R2-A01 |
| 16.2.2 | Explicit time basis | EVIDENCE_TO_REVIEW; existing timestamps exist in business/backup records | UTC/offset in operational records; clock skew and stale observer tests |
| 16.2.5 | Sensitive data controls | EVIDENCE_TO_REVIEW; aggregate worker output and redacted application errors | Marker-secret checks across gateway/framework/worker/command sinks; R2-A02 |
| 16.3.1 | Authentication events | EVIDENCE_TO_REVIEW; R2.1 success/failure/logout events omit credentials; complete control scope still needs assessment | Log result/reason code, not entered names/passwords; verify successful and failed paths |
| 16.3.2 | Authorization denials | EVIDENCE_TO_REVIEW; bounded R2.1 denial events plus existing route/grant checks | Bounded denial codes with no protected target details; R2-A02/A10 |
| 16.3.4 | Unexpected failures | EVIDENCE_TO_REVIEW; generic existing business errors | Safe exception codes and reference ID; infrastructure faults in isolated targets |
| 16.4.1 | Log injection resistance | EVIDENCE_TO_REVIEW; R2.1 strict JSON allowlist and hostile-value checks | Encode structured values and reject arbitrary messages/header IDs; R2-A01/A02 |
| 16.4.2 | Protected log history | TARGET_ENVIRONMENT; host controls need verification | Private access/rotation and tamper review; do not call local files immutable |
| 16.4.3 | Independent log destination | GAP; no accepted separate protected collection system | Retain gap until a separately reviewed deployment and failure test; no automatic external sharing |
| 16.5.1 / 16.5.3 | Safe failures | EVIDENCE_TO_REVIEW; error handling and transactional business-audit rollback tests | Denials stay denied and money stays atomic when logging/dependencies fail; R2-A01/A02/A05 |

Source: [official tagged V16](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x25-V16-Security-Logging-and-Error-Handling.md).
Security event capture and operational alert delivery are separate responsibilities;
R2 tests both without representing an alert acknowledgement as a business approval.

Mind map: event inventory → correlation/time → secret minimization → protected
storage → generic failure → targeted evidence, with remaining gaps retained.

## Authorization and session assessment

| ASVS 5.0.0 | Topic | Baseline status and next review |
|---|---|---|
| 8.1.1 / 8.1.2 | Function and field rules | EVIDENCE_TO_REVIEW; workspace route matrix, financial source contracts and manager projections; review completeness across every interface |
| 8.2.1 / 8.2.2 / 8.2.3 | Function, object and field enforcement | EVIDENCE_TO_REVIEW; seven-role, foreign-clinic and deidentified financial browser/PG tests; preserve while adding operational features |
| 8.3.1 | Trusted service authorization | EVIDENCE_TO_REVIEW; locked commands recheck current workspace and grants; no authority from hidden navigation or client headers |
| 8.4.1 | Independent customer tenancy | OUTSIDE_PRODUCT_SCOPE; one chain's clinic boundaries do not constitute multi-tenant customer isolation |
| 7.1.1 / 7.1.2 | Session lifetime and concurrency policy | GAP in the complete documented policy; production cookie lifetime alone does not prove inactivity handling or parallel-session governance |
| 7.4.1 / 7.4.2 / 7.4.3 | Session termination and account/factor changes | EVIDENCE_TO_REVIEW; account disabling, password/session invalidation and revoked-grant tests; review full requirement scope and exceptions |
| 7.5.2 | User session inspection/termination | GAP; requires its own actor, reauthentication, privacy and test contract |

Sources: [tagged V8](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x17-V8-Authorization.md)
and [tagged V7](https://github.com/OWASP/ASVS/blob/v5.0.0/5.0/en/0x16-V7-Session-Management.md).

MFA, the complete authentication chapter, dependency/supply-chain review, secret
lifecycle, sensitive-read retention and target-host hardening remain **NOT_ASSESSED**
outside these rows. This is not a complete control inventory or an ASVS score.
Real patient/payment use and any claimed legal/professional conformity require
separate product and operational acceptance.

Mind map: role → current scope → object/field → trusted command; session → policy
→ expiry/revocation → independent verification; clinic isolation ≠ customer tenancy.

## Work ownership and release decision

The developer implements and tests R2's request/logging/observer contracts. The
platform operator reviews actual storage, rotation, credentials and recovery.
Clinic/finance reviewers verify authorized business behavior after faults.
The project owner decides future scope and names responsible people before
unattended public operation. No invented staff names or external notification
recipients are assigned here.

Every assessment row should gain source paths, executed test IDs, environment,
review date and remaining exceptions before its status changes. A passing
business test may support a control; it cannot establish the entire standard.
The execution sequence and measurable gates are in
[R2 operational assurance plan](R2_OPERATIONAL_ASSURANCE_PLAN.md).

Mind map: evidence owner → executed check → reviewed exception → explicit decision;
documentation → assessment work, not automatic certification.
