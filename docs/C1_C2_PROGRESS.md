# C1.1—C2.3 execution register

The active objective is to complete **all C1.1 through C2.3 work** in
[the next-stage plan](COMMERCIAL_V2_NEXT_STAGE.md). A partial source change or a
passing unit test does not complete that objective. C1.2 is followed by C2.1,
C2.2 and C2.3; the plan has no separately defined C1.3 increment.

| Increment | Required business outcome | Current evidence / remaining work |
|---|---|---|
| C1.1 | Verified patient relations, appointment grants, website/native subject selection | Locally delivered; [executed evidence](evidence_c11/release.json). External platform/production gates remain separate. |
| C1.2 | Professional evidence/validity, clinic/service scope, controlled identity/referral requests, sensitive-read audit, departure/session handling | LOCAL DELIVERED. Exact application CI, full regression, five-clinic browser/native acceptance, 80-table encrypted restore, original-copy upgrade and protected installation passed; see [evidence](evidence_c12/release.json). Professional/platform/cloud and new clinical capacity remain separate. |
| C2.1 | Reported/reviewed history, encounter, dentition/tooth/surface findings, safe draft saving and worklist | NOT IMPLEMENTED. Professional review of terminology/templates required before real care. |
| C2.2 | Plan revisions/alternatives/decisions, partial actual execution, next-visit linkage and unique charge source | NOT IMPLEMENTED. Estimates, clinical facts, existing bill versions and cash remain separate. |
| C2.3 | Clinical recall windows, attributed front-desk work, lab dispatch/receipt/clinical acceptance/rework and readiness | NOT IMPLEMENTED. Retain original appointments; close recall only on defined actual care. |

Common completion evidence: NS-01—24 as applicable across five synthetic clinics;
real PostgreSQL and concurrency; full regression/exact CI; website/native
consistency and 390px/keyboard; actual ER/DBML/field catalogues; populated encrypted
restore; protected local update; formal course Word/PDF. The new multi-visit
workload also needs a fresh five-clinic/twenty-account, 30-minute, approximately
5-rps, 80% read/20% valid-write run and independently checked business facts.

Real clinical qualification, approved clinical templates, WeChat runtime/device/
experience, server/cloud and sustained commercial operation cannot be inferred
from synthetic local tests. Their owners, supplied inputs and actual acceptance
must be recorded. Historical UNKNOWN monitoring gaps and unrecovered Windows
data remain historical facts. These boundaries do not prevent local development.

The source report, observed PostgreSQL snapshot and original installation now
cover C1.2.
Future C2 structures remain proposals, never substituted for observed schema.

Mind map: verified identity → professional scope/shared care → encounter/findings
→ plan/actual execution/charge → recall/lab readiness → measured delivery.
