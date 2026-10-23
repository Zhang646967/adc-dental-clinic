# C0 service presentation schema delta

Published patient information → existing appointment service → clinic-owned scheduling.

This additive migration was executed in the isolated PostgreSQL 17 rehearsal on
2026-10-23. `schema_snapshot.json`, the catalogue ER, DBML and field/FK catalogues
now reflect the observed migrated structure. The 69-table result from 2026-10-21
remains historical evidence, preserved in its original delivery records and Git history.

`scheduling/0006_servicepresentation` adds `adc_service_presentation`:

| Column | Type / key | Meaning |
|---|---|---|
| `id` | bigint PK | Description identity |
| `service_id` | bigint FK, UNIQUE, required | One description per existing `adc_booking_service`; protected deletion |
| `category` | varchar(24) | Patient discovery category; no clinical authority |
| `title` | varchar(100) | Patient-facing service title |
| `summary` | varchar(240) | Purpose of this appointment |
| `suitable_for` | text, application limit 1,600 | Needs to discuss |
| `visit_content` | text, application limit 2,400 | This appointment's scope |
| `limitations` | text, application limit 1,600 | Exclusions and matters requiring confirmation |
| `preparation` | text, application limit 1,600 | Preparation information |
| `fee_mode` | varchar(12) | `ASSESSED`, `FIXED` or `FROM` |
| `fee_amount` | numeric(12,2), nullable | Unknown is NULL; confirmed zero remains zero |
| `fee_note` | text, application limit 1,600 | Fee coverage and separately confirmed items |
| `is_published` | boolean, default false | Explicit publication choice |
| `updated_at` | timestamp with time zone | Last description update |

The database fee check permits assessment-dependent pricing only with NULL
amount, and fixed/starting pricing only with a present non-negative amount.
The manager's form and repeated command validation enforce text completeness
before publication. Public reads additionally reject incomplete imported content
and filter inactive clinic/department/service/dentists or unenabled resource
policies. Child-service visibility does not grant guardian self-booking.

Changes use the existing `ResourceAction` retained proposal/confirmation workflow
and clinic `ResourcePolicy.revision`; no separate price, invoice or clinical
fact is created. An FK is a structural relationship, not an authorization grant.

The observed result is 70 SQL tables, 69 ORM tables, 632 ORM columns and 171 SQL
foreign keys, with all historical 42 SQL triggers retained and 40 application
migration files. The sixth-version documentation uses actual metadata; it does
not infer runtime installation or clinical qualification from these counts.

No business data migration or auto-publication runs. A reverse guard refuses to
drop the table when descriptions exist; restore/cutover requires the normal
protected-copy rehearsal and independent reconciliation.
