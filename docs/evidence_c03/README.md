# C0.3 local patient-channel acceptance

Source candidate → executed migration/regression → five-clinic journeys → independent financial/resource facts → protected delivery.

Record date: 2026-10-23. [Scope and fix](../C03_RELEASE_ACCEPTANCE.md).

| Evidence | Scope |
|---|---|
| [regression.json](regression.json) | 1,095 rules, 1,474 PostgreSQL/HTTP/concurrency tests; first failure and correction retained |
| [browser.json](browser.json) | 187 actual Chrome/native-handler HTTP checks in five synthetic clinics; no WeChat runtime claim |
| [business_facts.json](business_facts.json) | 64 independent ORM checks, current invoice/posted cash totals, no new clinical or money effects |
| [native.json](native.json) | 107 source/transport checks, 23 mocked Page cases, official eleven-page offline compilation |
| [database metadata](../database/schema_snapshot.json) | Observed 70-table, 171-FK, 42-trigger structure; no business rows or secret defaults |
| [report validation](../report-source/validation.json) | Current formal Word/PDF content and visual review |

Exact-commit CI, exact-image replay, original-database copy upgrade, encrypted restore and target installation are separate delivery records added only after execution. The source implementation's earlier NOT_RUN records remain historical; this folder records subsequent execution rather than rewriting them.

Historical capacity, prior monitoring gaps, WeChat platform and cloud results are not relabeled as current acceptance. This is not a commercial clinical replacement qualification.
