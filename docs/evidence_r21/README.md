# R2.1 executed local acceptance 已执行本地验收

Adversarial requests → real proxy logs → protected business facts → independent
recovery. Accepted **2026-10-18**; base planning commit `08510fb`.
[Machine-readable acceptance](acceptance.json) binds the changed source files.
[The implementation contract](../R21_SAFE_DIAGNOSTICS.md) explains controls,
operator actions and retention trade-offs. Full R2 and cloud acceptance remain pending.

| Layer | Executed result |
|---|---|
| Source regression | 918 checks; ten new adversarial serializer methods |
| PostgreSQL/HTTP/concurrency | 1,119 tests; thirteen new R2.1 methods; empty-test-db migrate/check and no new migrations |
| Real Chrome business workflows | 568 assertions across five clinics: partial receipts/refunds, equipment payments/reversals, CSV/match review and evidence correction |
| Real Chrome authorization | 248 assertions: seven roles, ordered foreign-clinic/account/object probes, limited projections and independent review |
| Real Chrome diagnostics | 78 assertions: safe failures, twenty parallel references, login/CSRF, clinical draft, invalid receipt, stale equipment request, malformed CSV, keyboard and 390px large text |
| Actual operational sinks | 28 browser requests correlated across Django, Gunicorn and Nginx; 63 credential/patient/reference marker values absent |
| Runtime commands | Real command body reached before its exception; failed command and unavailable-worker DB preserve exit 1 without printing private input |
| Local candidate HTTPS gateway | 15 GET logins accepted; 18 POST logins yielded 11 expected CSRF refusals and seven 429s; a 100-GET burst yielded 40 successes and 60 controlled 429s; 133 distinct matching server references |
| Size rotation | 250,000 safe records; 106,409 earliest records rotated out, 143,591 retained including the final record; production 10m/three-file options and no OOM |
| Independent financial oracle | Twenty SQL/content assertions; gross receipts 50,100.10, refunds 100.10, net patient cash 50,000.00 CNY; equipment expense/reversal 50.05 each |
| Encrypted restoration | Fifty model/association fingerprints match in a new empty PG17 target; 2.452-second recorded local restore/compare interval; source unchanged and temporary target removed |

The financial oracle also checks 24 confirmed/one retained stale match, thirty
accepted statement lines, retained original CSV digests, independent reviewers
and separate stale internal handovers. Invalid submissions and matching do not
invent cash or change billed revenue. One authorized synthetic clinical draft
was saved without closing treatment or issuing a bill.

The local gateway uses a private self-signed localhost certificate and the tested
candidate template. This does not prove public DNS, real certificate issuance,
renewal, mainland access or independent-host service. The private fault URLs
existed only in a disposable rehearsal mount and return 404 in the normal app;
they are not repository or Mac application routes.

Initial failed attempts remain recorded: a launcher mock needed to recognize the
new build argument; three new test fixtures/assertions needed the correct clinic,
JSON keys and post-login workspace; a browser helper needed the required clinical
confirmation checkbox. The final complete gate and browser runs pass. Actual
implementation fixes include late framework context loss, inherited raw gateway
logging, native DB value exposure and credential-bootstrap capture.

Original thirty migration files and frozen RC1 report outputs remain unchanged.
The Mac encrypted pre-update backup and 48-model/70-configuration snapshots were
prepared. Exact-commit CI must pass before application cutover; this local record
does not itself claim the Mac has been updated. Delivery/report synchronization
is recorded separately after the cutover.

Retention is size-based; seven-day deletion and separate protected collection
are not implemented. No thirty-minute capacity repeat, 24-hour monitoring,
ASVS-wide pass, twenty-clinic qualification or cloud acceptance is claimed.
R1's 2026-10-15 evidence and unresolved Windows recovery retain their original scope.

Mind map: request/context/privacy → actual three-layer correlation → seven-role
business facts → measured rotation → exact money → encrypted empty-target restore
→ exact-version CI and protected Mac release.
