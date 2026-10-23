# C0.2 evidence scope

Plan → implemented source → executed local contracts → pending target acceptance.

`verification.json` records exact source hashes and local execution. The five
new pure projection checks and 23 real JavaScript Page-handler scenarios use
synthetic data. The handlers call a mocked API; they do not establish actual
session/HTTP/database/resource-lock behavior. Existing transport mocks separately
exercise cookie/CSRF/workspace handling and uncertain-network errors.

The 25 new Django cases use real commands and TransactionTestCase, and have not
run here. They cover publication/operational filtering, detail privacy, fee NULL
versus zero, child/missing-service restrictions, signed request preservation,
publication changes and ABA, successful current-state replay, own unpublished
service rescheduling, waitlist rechecks and server environment presentation.

Do not substitute historical B1.5 compiler/HTTP evidence or C0 source evidence
for execution of this exact version. All 40 migration files are preserved; the
prior additive C0 migration still requires actual target validation. No installed
service or remote repository was updated during this slice.
