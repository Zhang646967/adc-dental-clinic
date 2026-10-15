# Daily reconciliation and handover 日结对账与交接

Collect four sets of synthetic evidence → manager compares each gross total →
finance independently reviews → resolve discrepancies in the original workflows
→ submit a new version when facts change. This is a retained reconciliation of
this application's approved cash ledger, not a bank balance or a period lock.

## Business contract 业务口径

- One clinic, one `occurred_on` fact date, Asia/Shanghai business timezone, CNY.
  Receipt, refund, equipment payment and expense reversal are separate gross
  totals. A receipt/refund difference cannot disappear in a net total.
- Only POSTED cash contributes money. PENDING applications are counted separately
  and prevent approval. REJECTED applications contribute no money. Bills, invoice
  corrections, original equipment costs and quarterly estimates are not cash.
- The preparer enters the four totals independently from synthetic evidence;
  blank is unknown and is refused. Explicit zero is permitted. Evidence reference
  and handover/reopening reason are mandatory; do not enter patient or bank data.
- The snapshot includes every cash row's monotonic count/max-ID/version-sum cursor
  for that clinic/date. Creation and review compare the entire current snapshot.
  There is no arbitrary clock cutoff or sealed business period. Today may be
  reconciled as of submission; later applications or reviews require another
  reconciliation. Entry date and approval timestamp remain distinct.
- Late posting belongs to its original fact date. A later-date refund belongs to
  the refund's own date; it does not rewrite the receipt day. A late application
  or decision for an already reviewed date marks the old snapshot as changed.
- A close does not authorize, create, reverse or rewrite payments, care, invoices,
  equipment events, quarterly costs, booking or scheduling.

## Responsibilities and workflow 职责与流程

1. **Current-clinic MANAGER:** open **日结对账与交接**, select **编制／重开日结核对**,
   choose the fact date, enter four evidence totals plus references and reason.
   Preview displays ledger totals, evidence totals and each signed difference.
   Confirm explicitly to submit a PENDING version. The preparer is the named
   discrepancy owner; submission is not completed handover.
2. **A different FINANCE account:** compare the retained snapshot, evidence range
   and preparer's explanation. Approve only when all four totals match, no cash is
   pending, the snapshot is current, and the preparer's grant remains valid.
   Switching the preparer's active role cannot enable self-review.
3. **Discrepancies / stale facts:** finance rejects with a concrete reason. The
   preparer returns to authorized receipt/refund, equipment fee, source-cost or
   reversal workflows, or corrects incorrectly transcribed evidence. Each source
   workflow retains its own independent review. No balancing journal is invented.
4. **Reopen explicitly:** after approval or rejection, a manager enters evidence
   and a reason again. A new numbered version references the latest terminal
   version. Only one pending version may exist for a clinic/date. Earlier facts,
   decisions, preparers, reviewers and timestamps remain immutable and readable.
5. **HQ:** read aggregate close history across the chain. Managers see only their
   selected clinic's aggregate close; this grants no patient/invoice-row access.
   Front desk, dentist, patient and technical roles have no daily-close access.

An empty day can be explicitly reconciled with four zero evidence totals. The
absence of a day-close row is never displayed as evidence that no money occurred.
The worklist shows the latest version for each clinic/date, including changed
facts; links traverse retained predecessors and the latest version.

## Design and checks 设计与验证

This business contract extends the requirements/design separation in the uploaded
course note. The ledger policy and staged commercial roadmap are project choices.

| Requirement | Implementation | Verification target |
|---|---|---|
| Do not confuse bills, cash, pending and net amounts | Four POSTED aggregates plus pending count; independent declarations | Exact-cent four-leg scenario; opposing discrepancies; occurrence-date tests |
| Trace responsibility and versions | Immutable DailyClose with previous version and independent review | Rejection/reopening, self-review, SQL lineage/terminal guards |
| Keep late data visible | Retained cursor and live comparison; approval rechecks | Stale preview/review and late-posting browser scenario |
| Preserve permissions | Current workspace and clinic grants, separate finance role | Seven roles, cross-clinic denial, revoked/inactive accounts, CSRF/read-only |
| Prevent duplicate or partial effects | Signed proposals, per-clinic/date lock, audit in same transaction | Replay, concurrent requests/reviews/cash, audit failure rollback |
| Preserve operation and recovery | Additive migrations; new empty restore target | Full regression, browser, independent SQL totals, encrypted recovery, Mac preservation |

New migrations `finance.0006` and `finance.0007` retain all previous 23 migrations.
The latter adds the clinic/date index, database snapshot function and immutable
history guards. Cash creation/review and daily-close commands acquire the same
clinic/date transaction advisory lock before source/entry locks. SQL cash triggers
also participate. Authorization remains application policy; a database owner can
alter triggers and is not a constrained business user. Stop old writers on upgrade.

Worklist pagination is 20 rows; aggregate reads are bounded per displayed day.
Snapshots do not store patient IDs or lists of every cash row. Existing source
histories retain row-level evidence. Daily-close rows are part of encrypted dumps.

Mind map:

- Fact date → Asia/Shanghai → four POSTED gross totals → pending separately.
- Evidence → explicit amounts → references → difference for each category.
- Responsibility → manager preparer → discrepancy owner → finance reviewer.
- Decision → current facts + no pending + equal totals + valid separate people.
- Exception → reject → source workflow correction → new version → retained history.
- Late fact → old snapshot unchanged → warning → explicit reconciliation again.
- Protection → role/clinic → CSRF/signature → day lock → audit → SQL history guards.
- Recovery → encrypted dump → independent empty database → all-model fingerprints.

## Scope and evidence 验证范围

This increment does not add payment-channel classification, bank/payment-provider
imports, receipt attachments, formal accounting periods, daily-close notifications,
external funds, tax reporting, or a general accounting ledger. Evidence is an
operator declaration, not automated bank verification. These remain follow-up
requirements before a commercial financial product can be claimed.

Executed evidence: [acceptance record](evidence_daily_close/acceptance.json).
884 source checks, 994 PostgreSQL/HTTP/concurrency tests (35 new), 444 real-browser
assertions (95 daily-close checks), and 57 independent SQL/Decimal assertions passed.
Encrypted recovery into a new empty PostgreSQL 17 database matched all 43 models
and associations, including four retained daily-close versions; source unchanged.
The 1.904-second fixture restoration is a small-sample result, not a production
recovery-time claim. One read-only assertion harness initially missed JSON decoding;
its failure was retained, corrected and rerun successfully. Public evidence contains synthetic fixtures only. Private
Mac preservation, encrypted backups and runtime checks remain outside Git.
Independent cloud acceptance, commercial-scale load and historical Windows-data
recovery keep their existing unresolved status.
