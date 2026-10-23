# C0.3 patient-channel acceptance and protected delivery

Published services → website/native booking → existing care continuity → observed schema → protected installation.

2026-10-23. This increment closes the previously unexecuted C0/C0.2 framework and database gate. It also fixes a real clinical regression: the public `care/<str:category>` guide route intercepted `/care/<visit-id>/`, returning 404/405 instead of the clinical workspace. Guides now use `/care/guides/<category>/`; numeric clinical routes retain their original behavior and authorization. A real route-resolution regression and the existing care tests cover the failure.

The public service website now shares the existing optional large-text preference, with an accessible control enabled only when its local script is available. At 390px, service cards become one column. Ordinary navigation and booking forms continue without JavaScript; CSP remains unchanged.

## Executed local acceptance

- Full isolated PostgreSQL 17 gate: 1,095 rules and 1,474 Django/HTTP/concurrency cases passed. First-run failures and the actual fix are retained in the evidence.
- Five synthetic clinics: 187 actual Chrome/native-handler HTTP checks, including non-first clinic selection, signed patient requests, ordinary website forms without JavaScript, manager withdrawal/republication, stale confirmation rejection, receipt replay and own retained-service rescheduling.
- Independent database checks: 64 passed; unique receipts/successors and resource releases match the saved results. Original 500 invoices and 500 posted cash entries remain CNY50,000 each; service publication and booking create no treatment or money.
- Current eleven-page native project: 107 transport/source checks, 23 mocked Page-handler scenarios and official offline WXML/WXSS compilation passed. HTTP-adapter execution is not a WeChat runtime or device test.
- Actual migrated schema: 70 SQL tables, 69 ORM tables/632 columns, 171 SQL FKs and 42 application triggers. Original 39 migrations unchanged; the existing additive service-description migration is the fortieth. Six ER views and searchable dictionaries were regenerated from metadata.
- Formal report: stable Word/PDF names, 59 numbered business use cases plus SF-01, new SU-59 service publication, current ER and ordered clinical development scope. Rendering/content evidence is separate from business execution.

## Delivery gates

The exact application commit must pass GitHub CI. Rebuild and rerun the accepted journeys with that identified image, restore an encrypted same-version backup into an empty independent database, and rehearse the original 39-migration database upgrade on a copy before installing. Keep the original volume, original records, private configuration and RC tag. Explicitly reviewed synthetic descriptions may be added through the manager's business commands after the original data comparison; no auto-publication migration runs.

Current and final records are under [evidence_c03](evidence_c03/README.md). This document records the execution contract; installation and exact-image/CI outcomes are established by their own records, not by this checklist.

## Next development boundary

Continue C1 under the [commercial master plan](COMMERCIAL_V2_MASTER_PLAN.md): patient/guardian relationships and attributable professional authority before longitudinal records and prescribing. C0 as a whole is incomplete. This delivery remains a synthetic local system; AppID/WeChat runtime, public cloud, new-version capacity and sustained observation remain separate gates. Historical Windows-data recovery remains UNRESOLVED. No real data, professional certification, purchases or public exposure are introduced.

Mind map: Service publication → {content, fee meaning, current scope} → patient choice → explicit shared booking → {retained care, accurate ER, independent recovery} → exact CI and protected delivery.

## Executed protected target update

Application `3b78cc5f430f18411bf50e4314f287b2c95666a0` passed [exact CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39946371153): 1,095 rules and 1,474 PostgreSQL/HTTP/concurrency cases. Its exact image repeated 187 five-clinic journeys and 64 independent database checks; all 566 selected application file hashes matched. An encrypted 70-table/29,875-row rehearsal restored into an empty independent database with all facts and 42 triggers matching. The original encrypted 39-migration database copy then upgraded with all 66 original row groups retained; 6.128 seconds after the empty replacement was ready.

The original loopback instance now runs that tested arm64 image on port18000, with its original database container/volume, 70 private configurations, RC tag and original records retained. An existing failed observer is recorded as UNKNOWN_OBSERVER_UNAVAILABLE; its observations and host journal were archived encrypted before the planned new observation identity. Current six-condition/host health is a snapshot, not continuous or 24-hour evidence.

After the original-data comparison, eight explicitly synthetic descriptions were saved through authorized manager preview/confirmation. Only two existing policy revisions changed as expected (four each); eight resource actions and eight audit events appended. Original patient, appointment, clinical and money rows remain unchanged. Fees remain ASSESSED/NULL. Final target browser and brief observation outcomes are recorded separately.

Target checks passed: 263 Chrome checks across nine existing accounts/seven roles, 13 native-handler HTTP read/preview checks without business confirmation, and all70-table/171-FK/42-trigger schema sections matching the ER source. A later collector-unavailable/collection-gap event recovered; three independent healthy samples and existing fresh collector conditions supported documented closure. The incident and UNKNOWN gap remain retained, root cause unreproduced. No source-code fix or uninterrupted observation is claimed.
