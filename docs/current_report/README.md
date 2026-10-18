# Current system report 当前系统报告

Delivered R1 → implemented R2.1 → protected Mac evidence → next R2.2 stage.
Report date: **2026-10-18**. Application baseline: **`ccdcdcd`**; [exact application CI passed](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39127594480).

- [Word report](ADC_Current_System_Report_20261018.docx)
- [PDF report](ADC_Current_System_Report_20261018.pdf)
- [Readable Markdown report](REPORT.md)
- [R2.1 contract](../R21_SAFE_DIAGNOSTICS.md) and [local/delivery evidence](../evidence_r21/README.md)
- [Detailed R2 plan and requirement-to-test trace](../R2_OPERATIONAL_ASSURANCE_PLAN.md)
- [ASVS 5.0.0 scoped security gap register](../SECURITY_ASVS_GAP_REGISTER.md)

The ten-section report covers business/module responsibilities, seven roles,
R1 financial closure, executed acceptance, R2 requirements, the first coding
batch, candidate monitoring/recovery targets, development gates, security gaps
and provenance. Each section ends with a mind map. English is the main text;
Chinese terms identify the corresponding course/business concepts.

## Status and scope 状态与适用范围

R1 application results come from the **2026-10-15**
[executed acceptance](../evidence_financial_evidence/README.md), including local
five-clinic/twenty-account capacity and independent encrypted restoration.
R2.1 is **DELIVERED_ON_MAC** with 918 source checks, 1,119 PostgreSQL/HTTP/concurrency
tests, 894 isolated Chrome assertions and 410 Mac assertions. Fifty restore
fingerprints match; 48 durable Mac fingerprints and 70 configuration files remain.
R2 is **IN_PROGRESS**; worker/backup monitoring, full capacity/observation and
independent-host targets remain pending. Local acceptance and independent-cloud acceptance
remain separate. The original Windows-data recovery remains unresolved.

This is the current development companion to the
[frozen 63-page R5/RC1 course report](../release_report/README.md). The original
Word/PDF, UML models, migrations and RC tag retain their historical identities.
R2.1 added no migrations. This report companion is synchronized after the
application cutover; its documentation-only update does not restart services.

## Source and reproduction 源稿与复核

`report_source.json` is the editable report text. `baseline.json` separately records historical R1 and current R2.1
evidence. It contains only
sanitized aggregate facts and provenance; it contains no credentials, database
dumps, patient records or imported CSV content. `build_report.py` generates both
the Word report and `REPORT.md` using Python with `python-docx`:

```sh
python docs/current_report/build_report.py
```

PDF export is a separate step. This delivery used the bundled document runtime
and its LibreOffice/Poppler renderer with an isolated font cache, then inspected
all ten rendered pages. A fresh export requires a fresh visual review; it must
not overwrite the historical RC1 report. `validation.json` records the source,
output hashes, page count and checks for this revision. The generator does not
access a database, host configuration or the running application.

Mind map: current text + sourced facts → Word and Markdown → PDF export →
page-by-page inspection → integrity checks → exact-commit CI → GitHub/Mac sync.
