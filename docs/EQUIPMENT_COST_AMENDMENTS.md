# Equipment cost supplementation and correction 设备费用补正

Find the original event → settle pending cash or reverse an incorrect posted fee
→ manager requests the verified total → another person reviews → separately
request cash posting. Original costs, decisions and cash entries remain readable.

This increment resolves the previously documented inability to supplement or
correct historical equipment costs. It applies to registration and service events,
including events of retired equipment. It does not reactivate devices or alter
care, bills, visits, availability, quarterly dentist costs or external funds.

## Responsibilities and operations 职责与操作

1. **Manager, selected clinic:** open equipment history or the fee worklist, then
   **费用依据与补正历史**. Compare the original amount, current effective amount,
   posted net expense and pending requests. Unknown is distinct from confirmed zero.
2. If cash requests are pending, have finance resolve them first. If a fee has
   been posted, use the existing original-amount reversal request and independent
   cash review. A source-cost change is allowed only when posted net expense is
   zero and no cash requests are pending. A reversal alone does not change cost.
3. Select **申请补录／更正费用**, enter the **whole verified event cost**, not the
   difference, and record the synthetic source evidence. Zero is an explicit fact;
   blank, negative, nonfinite, excessive-precision and unchanged values are refused.
4. Preview the source, original/current/proposed amounts and evidence. Explicitly
   confirm. The request enters **待独立审核**, preserving the current cost. A
   pending cost request blocks new expense requests for that event.
5. **Different person, active FINANCE role:** open **待审核费用补正**, inspect the
   source and evidence, then preview and confirm approval or rejection. Switching
   the applicant's role cannot enable self-review. Revoked/inactive applicants and
   inactive clinics prevent approval; rejection retains history.
6. After approval, the effective cost is the latest approved supplement. The
   original event and asset acquisition cost remain unchanged. The worklist counts
   each event once using its current approved cost, independent of cash-row count.
7. Manager separately submits the equipment expense. The cash request records the
   precise approved cost basis. Finance independently reviews that cash request;
   the cost reviewer may review cash if they are not its applicant. Neither approval
   calls a payment service. Prior entries keep their original amounts and basis.

Example: original cost unknown → approved supplement ¥120.01 → independently
posted ¥120.01 → original-amount reversal posted → supplement ¥80.00 approved →
new expense ¥80.00 posted. Current cost and net expense are ¥80.00; the original
unknown fact and all three cash entries remain. A rejected request has no effect.

Mind map:

- Source → registration / service → immutable original → unknown ≠ zero.
- Preconditions → no pending cash → net expense zero → reverse and review first.
- Applicant → current-clinic manager → evidence → total amount → signed preview.
- Reviewer → different person / FINANCE → fresh grants → approve or reject.
- Effective facts → latest approved supplement → original retained → one event once.
- Cash → separate request → cost basis retained → independent posting / reversal.
- Protection → replay / stale forms / concurrent requests / audit rollback / DB guards.

## Design and verification 设计与验证

Following the uploaded `note__3.pdf`, requirements describe observable behaviour;
this design explains the implementation. The clinic control rules and commercial
priorities are project decisions, not facts asserted by the lecture note.

| Requirement | Implementation | Verification |
|---|---|---|
| Supplement/correct without overwriting history | Retained cost request with optional prior approved reference | Original values, chained supplements, rejected/terminal immutability |
| Independent approval | Active-role scope, canonical user/grant locks, different-person constraint | Seven roles, self-review after role switch, revoked/inactive actors |
| Prevent bypassing cash review | Shared asset/event lock, no pending cash, net zero | Cash/cost race, posted reversal prerequisite, stale previews |
| Trace each cash amount to its cost source | Nullable approved-amendment FK; null means original event | Old cash retained, new/reversal linkage, mismatched-basis SQL rejection |
| Keep requests repeatable and atomic | Signed 15-minute workspace proposal, source cursors, audit transaction | Replay, competing managers, duplicate reviewers, audit-failure rollback |
| Bounded readable worklists | Current-clinic/chain scope, 20-row pagination, indexed scalar subqueries | Page/query-count and cross-clinic checks, narrow browser layout |

Three additive migrations create one history table, one nullable cash reference,
constraints and PostgreSQL guards. All original 20 migrations remain byte-for-byte
unchanged. Stop old writers before applying the schema; use the matching code.
History-bearing reverse migration is refused. Recovery uses a new empty target.

Current execution evidence is in `evidence_commercial_foundation/acceptance.json`.
Tests and local synthetic browser results do not establish public-course acceptance
or large commercial capacity. The next commercial stages are defined in
[Commercial development roadmap](COMMERCIAL_DEVELOPMENT.md).

The final local gate passed 884 source checks and 959 PostgreSQL/HTTP/concurrency
tests, including 47 new methods. Four Chrome routes passed 349 assertions; 31
independent raw-database checks passed. An encrypted restore into a new empty
PG17 database matched all 42 model/association fingerprints. The small-fixture
restore duration does not establish production recovery performance.
