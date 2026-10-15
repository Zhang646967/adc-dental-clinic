# Payment evidence and transaction reconciliation 资金凭据与逐笔对账

Source facts → versioned evidence → private statement preview → proposed match →
independent financial review → retained differences and recovery.

R1 supports one clinic chain using synthetic data, CNY business amounts and
Asia/Shanghai fact dates. It adds evidence to the existing separately reviewed
cash ledger. A match records correspondence; it does not receive, refund or
transfer external funds and does not change bills, balances or quarterly profit.
The broader learning sequence is in [Mature systems study](MATURE_SYSTEM_STUDY.md).

## Responsibilities and daily work

1. **FINANCE** establishes each clinic's synthetic payment-channel accounts.
   Codes are stable and unique per clinic. Methods are CASH, CARD, BANK_TRANSFER,
   E_WALLET and OTHER. Disabling an account prevents new requests/imports; existing
   evidence and accepted statements remain available for historical reconciliation.
2. **Current-clinic FRONT_DESK** selects a channel account and evidence reference
   with each bill receipt/refund request. **Current-clinic MANAGER** does the same
   for equipment payments/reversals. Preview and confirmation bind both fields.
   CashEntry and its first evidence version are committed together. The different
   finance reviewer approves or rejects both atomically through the existing cash
   review. Pending evidence is not proof of posted money.
3. **Current-clinic MANAGER** uploads a synthetic statement, reviews its entire
   batch summary and the first twenty preview rows, and explicitly accepts it.
   Parsing a valid file saves a private draft, not accepted statement lines. Each
   accepted batch records actual new and skipped counts. The importing manager is
   the named follow-up owner for its unmatched differences.
4. The manager opens an accepted line, reviews bounded candidate evidence and
   explicitly proposes one cash entry. Candidates require an exact account,
   reference, amount, direction, currency and current approved evidence. A proposed
   match remains pending; no automatic match is accepted.
5. **A different FINANCE account** confirms or rejects the pending match. Current
   grants, preparer eligibility, evidence version, source identity and uniqueness
   are checked again under locks. Switching the preparer's role never allows
   self-review. One cash entry and one statement line can each have only one active
   PENDING/CONFIRMED match. Rejected/stale decisions remain readable.
6. **HQ** sees authorized chain counts only. Managers see their clinic's financial
   amounts, channel references and matching history without patient identifiers,
   clinical notes or invoice details. Technical privilege does not grant business
   access. Existing front-desk/doctor/patient permissions remain in force.

Mind map: actor → current role/clinic → source → evidence → explicit proposal →
different reviewer → correspondence, with no independent cash side effect.

## Evidence corrections and historical records

Pre-R1 cash entries retain their original values and an explicit missing-evidence
status. No migration infers a payment method or reference. Existing historical
pending cash requests keep their prior review path; posted records can then be
supplemented. All newly prepared cash requests require evidence at the command
boundary, including reversals.

For a posted entry, its authorized source operator requests an evidence supplement
or correction with a reason. A different finance account decides. A rejected
version leaves the previous approved evidence effective. Approval makes the new
version effective and atomically marks any old active match STALE, preserving its
original submitter, review and timestamps. The money entry remains unchanged.
The same account/reference may be resubmitted with a reason when a matching choice
needs to be reopened. Reconciliation must then be proposed and reviewed again.

Wrong money follows the existing cash/invoice correction or reversal commands;
changing evidence cannot adjust a balance. Combined deposits, fees, split
allocations, unsupported currencies and missing references remain unmatched
differences. There is no balancing journal or automatic write-off.

Mind map: missing evidence → explicit supplement; wrong evidence → new version →
independent decision → stale old match → explicit rematch; wrong money → original
cash/source correction workflow.

## CSV v1 contract and retained source

Routes: `/finance/payment-accounts/`, `/finance/reconciliation/`, the import at
`/finance/reconciliation/import/`, and evidence actions beside existing cash pages.
These are authenticated Django forms; no external business REST API is introduced.

```text
transaction_id,booked_on,direction,amount,currency,reference
SYNTH-001,2026-10-15,IN,100.00,CNY,SYNTH-RECEIPT-001
```

- UTF-8 (an optional BOM is accepted), an exact six-column header, at most 2 MiB
  and 1,000 data rows. Malformed encoding, quoting, dates, columns, controls,
  nonpositive amounts or conflicting IDs reject the file before an accepted line.
- Transaction IDs and references are trimmed, case-sensitive visible text up to
  eighty characters. IDs are required. A missing statement reference is retained
  as a difference, and cannot match a required nonempty cash reference.
- Booked dates are ISO dates retained as source declarations. They can differ
  from the ledger's business fact date. Amounts use a decimal point and exactly
  two decimal places; scientific notation, grouping separators and coercion are
  refused. Direction is IN/OUT. Three-letter uppercase source currencies are
  retained; this release matches CNY only and never converts currencies.
- Clinic and channel account are selected through the current authorized
  workspace, not CSV columns. `(account, transaction_id)` identifies a statement
  transaction across batches. An identical repeat is explicitly skipped. A
  conflicting repeat rejects the entire acceptance, including otherwise new rows.
- Original bytes, SHA256 digest, parser version and normalized rows are immutable
  database evidence. The form signs a server-held draft identity and digest,
  rather than trusting row data returned by the browser. Confirmation reparses
  the retained bytes and checks every row and concurrent duplicates again.
- Accepted lines preserve their original batch. Overlapping batches keep their
  own raw source and skipped counts. Drafts and accepted history are private and
  retained; a discarded/expired preview creates no accepted lines. Reupload the
  original file for a fresh preview when necessary.
- The gateway permits a 3 MiB multipart envelope only at the exact import route;
  the application enforces the 2 MiB file bound. General gateway/request limits
  and current rate limits still apply. No document attachments or card secrets
  are accepted by this feature.

Mind map: bounded bytes → strict parser → private draft/hash → explicit acceptance
→ reparse/deduplicate → immutable rows → same encrypted database backup.

## Daily handover and settlement status

[Daily reconciliation](DAILY_RECONCILIATION.md) continues to compare four POSTED
gross totals and require independent review. It remains an internal daily handover,
not a sealed accounting period. The detail page adds current posted/evidenced/
confirmed-match counts and links to channel differences.

A next-day settlement can remain unmatched while the original day is handed over.
The source booked date and cash fact date both remain visible. A daily handover's
approval does not assert that the external channel is reconciled. Matching does
not change the daily cash cursor; a later cash posting still triggers the existing
changed-snapshot warning and explicit new daily-close version.

Mind map: business date → four gross ledger totals → reviewed daily handover;
booked date → channel evidence → separate reviewed match → remaining differences.

## Requirements and protection

| Requirement | Command/read boundary | Acceptance |
|---|---|---|
| R1-01 correct scoped channel | FINANCE configuration; current-clinic source request | Foreign/disabled account, stale account version, role denial |
| R1-02 no cash without new-request evidence | Cash request/initial evidence in one transaction | Required evidence, independent decision, audit rollback |
| R1-03 retained import source | Strict parser and private draft/atomic import | Boundary sizes, duplicate/conflicting IDs, overlap race, byte hash |
| R1-04 exact one-to-one correspondence | Manager proposal and separate finance decision | Amount/direction/currency/reference rejection, active uniqueness, replay |
| R1-05 evidence correction retains facts | Versioned supplement and atomic match invalidation | Legacy missing evidence, reject/approve, SQL and review races |
| R1-06 privacy and current authority | Explicit route roles and scoped projections | Seven roles, stale workspace, revocation, no manager clinical details |
| R1-07 daily and channel states stay distinct | Separate current evidence counts | Next-day settlement, unchanged cash/bill/daily facts |
| R1-08 verified delivery | Full PG/browser/load/recovery/CI/Mac checks | Executed evidence, encrypted empty-target restore, original Mac preservation |

Two additive migrations preserve the previous 28 files byte-for-byte. New SQL
guards protect channel identity, evidence lineage, raw/normalized imports,
accepted rows and terminal matching decisions. Deferred guards require import
counts to match the accepted rows and old matches to be invalidated with new
approved evidence. They do not authenticate a real bank statement.

Write order is current actors/grants first, then the cash entry, evidence,
statement line and matching record. Account locks serialize overlapping imports.
Cash posting keeps its existing day/source lock protocol. Original operations
re-read grants under their locks; known concurrency conflicts roll back. Arbitrary
SQL by database owners is outside the application authorization protocol.

The new evidence is included in normal encrypted PostgreSQL dumps, including raw
CSV bytes. Acceptance requires independent fingerprints of every model and
association, not merely a count of financial rows. Executed results belong in
`evidence_financial_evidence/`; old commercial/G3/G4 records retain their own scope.

Mind map: requirement → actor/contract → invariant → failure response → actual
PostgreSQL/browser/load facts → recovery → tested GitHub commit → protected Mac.
