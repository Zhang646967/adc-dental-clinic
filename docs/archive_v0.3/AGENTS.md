# ADC development constraints

Read `README.md`, `docs/PHYSICAL_DESIGN.md`, `docs/CHANGELOG_v0.3.md` and `docs/TEST_REPORT.md` first.

- This is an unexecuted Django/PostgreSQL engineering candidate. Never report framework/import/migration/UI/concurrency success from AST or pure-function tests.
- Preserve v0.2 terminology and the twenty logical objects. Visit remains the lifecycle record. Patient number is not a patient login. Dentist/patient are not permanently owned by one clinic.
- Invoice is one logical document per closed visit. Content lives in VisitRecordVersion + TreatmentRecord. Do not introduce a second independently editable invoice-line source.
- No actual patient or staff data, original case PDF/photos, secrets, or font files in the repo/package. Seed accounts get random passwords.
- Critical writes go through service functions, with server-side action/scope/state validation and audit in the same transaction. Do not expose unrestricted ModelAdmin/ModelForm writes to states or published content.
- PostgreSQL is required. Do not remove exclusion constraints/triggers or swap to SQLite merely to make tests pass.
- Use one role/scope binding, not a Cartesian product. is_staff/is_superuser is not a business-authorization bypass.
- Frozen migration expressions in adc_core/db.py and identifier function paths must remain importable. SQL snapshots in docs/sql must match migration SQL.
- Care/finance business services are not implemented. Do not render a completed/payment success screen without those services and tests.
- Run checks: `python -m unittest discover -s checks -v`; then in a real isolated PostgreSQL environment `python scripts/integration_gate.py`.
- If a gate fails, retain the real output, fix the defect, and rerun. Never claim an unrun test as passed or rewrite recorded prior evidence.
- Final public release requires a full dependency/image lock, production server/static setup, HTTPS, login throttling, scoped permissions, synthetic demo isolation and backup/restore evidence. Do not simply delete the production blocker.
