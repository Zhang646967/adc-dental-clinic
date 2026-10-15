# Local multi-clinic results 本地多诊所验证结果

Scoped data → continuous load → independent database checks → encrypted recovery.
The machine-readable record is [acceptance.json](acceptance.json); the complete
contract and limits are in [Multi-clinic capacity](../MULTICLINIC_CAPACITY.md).

| Check | Executed result |
|---|---|
| Independent synthetic scenario | 5 clinics, 20 distinct measured accounts, 10,939 patients before the accepted run, 10,505 visits, 500 invoices, 150 assets |
| Continuous traffic | 30 minutes, 9,000 HTTP requests, 7,200 reads and 1,800 valid writes |
| Arrival model | 20 concurrent requests per wave every four seconds; five requests/second on average |
| Response time | p95 0.341 s; maximum 1.8945 s, including client queue time |
| Positive-load failures | 0; no dropped arrivals, duplicate patients, OOM, container restarts or database deadlocks |
| Independent write facts | 900 unique patients in their expected clinic; 900 exact draft-note/version changes; other historical business facts unchanged |
| Browser permission/business assertions | 1158; seven roles, foreign IDs, search, current-clinic booking choices, stale forms, revoked grants, password/session invalidation, self-review and simultaneous duplicate confirms |
| Regression | 897 host/source checks; 1065 real PostgreSQL/HTTP/concurrency tests |
| Encrypted empty-target restore | 45 model/association fingerprints match; 2.641 s for the recorded restore-and-compare interval |

The initial seed had 10,004 patients. Short preflights added 35; the earlier
interrupted run added 900. Those records were retained. The accepted run then
added 900 more. The interrupted run had an independently measured 833.297-second
business-write gap and **does not pass continuous capacity acceptance**. A new
wall-clock/monotonic/arrival-gap gate and temporary idle-sleep prevention were used
for the accepted run. The local application changes were the same in both runs.

The ordinary read paths were also measured independently of HTTP. Front-desk
patient page/count queries fell from a median 7.070 to 2.591 ms; the dentist path
from 5.289 to 2.386 ms, with identical authorized patient sets. The manager's
20-row daily-close page fell from 51 to 32 queries, and finance from 49 to 30.
These are warm local instrumented measurements, not public-network latency.

After the load, five clinics each completed a 10.01 CNY refund, matching receipt
and separate 10.01 CNY equipment expense with independent finance review. Duplicate
confirmations returned the same record. The independent SQL oracle verifies
50,050.05 CNY gross receipts, 50.05 CNY refunds, 50,000.00 CNY net patient cash,
50.05 CNY equipment expenses, no pending entries and one independently rejected
self-review test request. Existing billed revenue remains 50,000.00 CNY.

The test uses Linux containers on the Mac, with per-service limits totaling two
CPU cores and 1,728 MiB; it does not reproduce an independent 2 GB cloud server.
The RC synthetic database-owner identity is used. Application clinic permissions
are tested; independent customer tenancy and production database role separation
are outside this measured environment. Commercial maximum capacity and a real-data
pilot are not approved. Cloud deployment/access/24-hour gates remain NOT_RUN;
original Windows-data recovery remains unresolved.

Mind map: clinic/role scope → valid mixed writes → continuity and resources →
independent money/history checks → restore → exact-commit CI → protected Mac update.
