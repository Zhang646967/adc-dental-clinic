# Replacement appointments（预约改期优化）

Find an available interval → compare original/new arrangements → explicitly
confirm → verify the linked successor. This batch addresses front desk staff
having to infer free intervals from whole clinic sessions and manually type
every replacement time.

## Resulting workflow（业务流程）

1. Open a scheduled appointment in the current front desk clinic and choose
   **改期并创建后继预约**. Its original date, dentist and business number remain visible.
2. Select a China-calendar date in the next 14 days and optionally a dentist.
   The bounded search keeps the original duration, considers starts every
   30 minutes relative to each session, and checks both patient and dentist
   commitments, including other clinics and live waitlist holds.
3. **选择这个时间** fills the existing time fields. Staff can still manually
   enter an arrangement allowed by the existing booking rules. They record
   the patient's stated reason and open a comparison preview.
4. The preview saves no appointment. Staff compare both arrangements, check
   their explicit acknowledgement and confirm within 15 minutes.
5. The original booking becomes retained reschedule history only when the
   unique successor commits. The existing booking command copies requests,
   checks shared slot/resource locks and saves the reschedule audit.

The HTML endpoint remains the same. Its ordinary form POST now produces the
preview; the signed confirmation is the write step. Existing domain booking
and reschedule commands remain intact. No schema, new public API, automatic
patient acceptance, professional qualification verification or solver change
is introduced.

## Changes and uncertain results（变化与回执）

Conflicting appointments/holds, paused or inactive destinations, changed source
state, revoked grants and switched workspace contexts are checked again at
confirmation. Pause/resume changes the destination's admission revision and
invalidates earlier previews. An unchanged arrangement is rejected before
creating pointless replacement history.

Repeated confirmation returns the unique already saved successor only when its
immutable fields and original actor's reschedule audit match the signed proposal.
A subsequently cancelled or rescheduled successor is returned in its current
state; it is never restored to scheduled. Another account or different proposal
cannot overwrite that result. This is application-level replay handling, not a
transport exactly-once guarantee.

Stale, expired and unverified responses lead to the original record and its
authorized related booking. Coordination return links remain typed and scoped;
no external redirect URL is accepted.

## Search scope（搜索范围）

At most 80 current-clinic sessions, 1,000 relevant visits, 1,000 live holds,
480 start times and 30 displayed recommendations are considered. Original
durations over 12 hours use manual checking. Limits and incomplete reads are
explicit; absence from the candidate list is not proof of universal unavailability.
The original booking is omitted from conflicts solely while evaluating its
replacement. Other appointments, including completed occupying intervals,
remain blockers. Expired pending offers do not hold capacity and are not
automatically recycled by a query.

## Acceptance（验收）

Run the existing PostgreSQL gate plus `tests.test_reschedule_optimization`.
Exercise candidate selection, original/new comparison and explicit confirmation
in real Chrome. Verify conflict after preview, repeat confirmation, source history,
scope refusal and narrow/large-text layout using database facts. Preserve the
normal Mac database, private configuration, RC tag and historical evidence.

### Executed local acceptance — 2026-10-14

- **884 source checks and 793 PostgreSQL/HTTP tests passed**, including 50 new
  rescheduling test methods. The gate also passed Django checks, migration
  drift detection, applying all existing migrations and temporary-instance cleanup.
- **57 real Chrome checks passed** for candidate selection, timezone-prefilled
  controls, no-write preview, explicit confirmation, repeat receipt, a booking
  made after preview, pause/resume invalidation, all seven role homes and scope
  refusals. Selection, comparison and recovery were checked at 390 CSS pixels
  with large text.
- Visual review found an internal form key in a conflict error. After replacing
  it with the business message, **14 additional Chrome checks and the full gate
  passed**. Long appointment numbers now wrap within the rescheduling pages.
- **15 independent PostgreSQL assertions passed**: original intervals/history,
  unique matching successors, copied requests, one reschedule event per source,
  unchanged sources after refusal, retained competing bookings and admission
  revision, and no implicit treatment, billing or waitlist creation.

The isolated database retains the first successful partial-run reschedule and
all subsequent fixtures; it was never reset to obtain a pass. The first repeat
URL check compared a browser-inherited page anchor with the HTTP redirect.
The corrected check requires the same successor path and clinic query, while
the independent duplicate-record checks remain intact.

[Sanitized acceptance record](evidence_rescheduling/acceptance.json) contains
the application file hashes and exact check scope. The screenshots use synthetic
course data: [replacement selection](evidence_rescheduling/replacement-search-large-text.png),
[comparison](evidence_rescheduling/replacement-comparison-large-text.png) and
[conflict recovery](evidence_rescheduling/replacement-conflict-readable-large-text.png).
Private credentials, proposal tokens, cookies, dumps and original Mac data are
excluded from the public evidence.

These results do not complete cloud course acceptance or recover the missing
Windows database. Search results are temporary observations, not reserved times.
