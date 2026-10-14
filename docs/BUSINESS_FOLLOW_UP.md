# Business follow-up（业务跟进优化）

Unfinished facts → role-specific work lists → existing confirmation workflow
→ verified business outcome. This development batch follows the user's request
to improve the full business chain after cloud preparation. It does not change
the RC tag, database schema, booking rules or independent-review requirements.

| Business problem（业务问题） | Resulting behavior（优化结果） |
|---|---|
| Front desk must browse history to find overdue outcomes | Current-clinic overdue and today's arrival queues, with direct record links; lateness never becomes an automatic no-show |
| Checked-in patients can disappear among historical visits | Dentist sees all their unclosed checked-in visits in arrival order, including previous dates |
| Coordination work is scattered across menus | Front desk sees their in-progress and unclaimed tasks; manager sees independent reviews and paused future slots needing a separate next decision |
| Expired offers prevent wait requests returning to matching | Current-clinic expired-offer count links to explicit recycling; valid existing offers remain visible when a slot is paused |
| Patients can miss an offer or hunt for a bill | Own live offer deadlines, expired preference/offer follow-up and current-version invoice links appear on the patient homepage |
| Quarterly profit is blocked without an obvious preparation queue | Quarter list identifies roster, missing/draft costs and off-roster billed dentists using the existing financial policy; confirmed zero remains distinct from missing |
| Management sees rates without unresolved-work scope | Manager receives current-clinic counts; headquarters receives clinic-level overdue counts and recent quarterly completeness, without patient identity or clinical text |

Appointment lists support task queue, China calendar date, state and exact visit
number. Front desk and the assigned dentist may additionally search patient
number/name within their existing scope. Pagination retains filters. Invalid
filters return a visible error without showing an unfiltered dataset.

Correction lists distinguish all history, open requests and independently
reviewable requests. The last excludes the current account's own requests.
The original detail/command still rechecks reviewer separation and current facts.

Homepage previews show at most five items per group, with the exact group count
and a link to the full related list. Financial homepage completeness is explicitly
limited to the six most recent established quarters; the complete quarter list
is paginated. These are observed facts, not a global priority score, clinical
quality rating, cash balance or permanently closed ledger.

The technical role keeps account/directory tools and receives no business data.
No GET accepts an offer, changes an appointment, marks a message read, issues an
invoice, confirms a cost or changes an account. Users open the existing detail
pages and confirm actions with the existing CSRF, workspace, replay and audit
checks. Read-only demonstrations can display these work lists.

## Acceptance（验收）

Run `tests.test_business_worklists` against PostgreSQL, then the full isolated
regression gate. Check all seven workspaces in real Chrome, including filters,
work-list links, 390px/large text and refused cross-role navigation. Repeat a
real business write through an existing signed confirmation form and verify
the database result. Record actual results separately from historical G3/G4
evidence and cloud acceptance, which remains pending server purchase.


Local acceptance passed on 2026-10-14: 884 source checks, 743 PostgreSQL tests
(including 38 new business scenarios), 59 real Chrome business checks and 24
final-runtime role/layout checks. The independent database oracle confirmed
200.00 current revenue, 30.00 costs, 170.00 profit and 17.00 fund, while retaining
the original 400.00 invoice version. No-treatment care closed with a zero invoice;
coordination approval left source maintenance as a separate decision.

The initial roster scenario and browser-selector/navigation assumptions failed
and were corrected; an already accepted offer was preserved rather than reset
or replayed. Final privacy and empty-state fixes passed a repeated full gate and
all-role Chrome smoke. See [sanitized acceptance evidence](evidence_business_worklists/acceptance.json).
