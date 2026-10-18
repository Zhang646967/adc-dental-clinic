# R2.2 executed acceptance and delivery

Notification progress → eligible backlog → visible observation failure → preserved
business facts → exact-version CI → protected Mac. Date: **2026-10-18**.
Application **02a9dbc90583fbcad47567e64ae77ae810eca33f**; [application CI passed](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39134681755).

- [Local acceptance](acceptance.json): 978 rule/source checks, 1,145 real
  PostgreSQL/HTTP/concurrency tests, 32 live fault checks and 869 Chrome assertions
  (568 financial workflow, 248 role/clinic isolation, 53 notification/accessibility).
- [Mac delivery](delivery.json): 437 authorized-read Chrome assertions;
  48 original durable fingerprints and 70 original private configurations match.
  Original database volume and RC tag remain; no test business is injected.
- [Requirement-to-test trace](requirement_trace.json) connects R2-04/05/06 and
  acceptance groups to concrete tests and executed evidence.
- [Operator contract](../R22_OPERATIONS_OBSERVATION.md) defines conditions,
  ownership, bounded retention, recovery and private commands.

Initial runtime/browser/recovery evidence belongs to ed7e10e. The final application
02a9dbc differs only in a corrected time-of-day-dependent search test, one new midnight
case and integrity manifests. Runtime modules/configuration are byte-identical;
the final source passed the complete 1,145-test gate and exact CI before Mac delivery.
The initially failed CI is retained and explained in local acceptance.

The worker was actually killed before commit (rollback, then one message per
original grant) and after commit (positive barrier, external KILL and engine exit
137; no duplicate/replayed task). Graceful stop was observed in 24.588 seconds;
forced precommit stop in 110.042 seconds in this local run. These observations
support the tested 120-second detection gate, rather than a customer SLO.

Future retries were excluded from due work; FAILED and NO_RECIPIENTS remained
separate. Repeated acknowledgement retained one responsibility transition and
did not clear the fault. Database and observer outages, corrupt/foreign/future/
overly accessible files, a competing collector, and simulated low space were
checked. New good samples were required to recover. Thirty-two protected clinical,
money, equipment and authorization projections matched across the injected faults;
notification/task test history was checked separately.

An independent SQL oracle verified synthetic receipts **CNY 50,100.10**, refunds
**100.10**, net patient cash **50,000.00**, equipment expense/reversal **50.05**
each, 24 confirmed and one retained stale match. Matching never changed bills.
Logs contained none of 64 credential/patient/CSV/reference markers; 992 requests
were correlated across application, Gunicorn and gateway. Fixed startup/stop
notices are separate from structured request events; native request-error and
database output remain suppressed.

An age-encrypted backup was decrypted/restored into a new empty PostgreSQL target:
all **50** model/association fingerprints (including CSV bytes and retained
financial history) matched in **2.454 seconds** including target preparation and
comparison. The source was unchanged; the temporary target/network were removed.
Only the identified rehearsal containers/networks were stopped afterwards; its
business and operations volumes and private failed-harness records were retained.

Local acceptance is a checkpoint; its pending-at-that-time rollout fields are
resolved by the separate delivery record. New operational files have their own
encrypted Mac snapshot; existing database-only daily backups do not automatically
include them. No new migration or business role was added; all 30 project
migrations, the frozen RC course report and RC tag remain.

**Remaining gates:** R2.3 created/downloaded/restored backup freshness; R2.4 the
equivalent 30-minute capacity repeat, 24-hour observation, host event collection
and full security/runbook review; independent cloud operation awaits the server.
No external alert delivery, strict seven-day log expiry, twenty-clinic capacity,
ASVS conformity or commercial readiness is claimed. Original Windows-data recovery
is unresolved.

Mind map: committed notice → separate progress facts → private read-only observation
→ incident/unknown → responsible response → unchanged money/care → verified version.
