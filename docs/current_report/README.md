# Current system report 当前系统报告

Delivered R1 → current evidence and limits → detailed R2 plan → staged acceptance.
Report date: **2026-10-18**. Application baseline: **`6a06f35`**.

- [Word report](ADC_Current_System_Report_20261018.docx)
- [PDF report](ADC_Current_System_Report_20261018.pdf)
- [Readable Markdown report](REPORT.md)
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
five-clinic/twenty-account capacity and independent encrypted restoration. R2 is
**PLANNED**: the report does not claim that its logging, observation or service
targets have already passed. Local acceptance and independent-cloud acceptance
remain separate. The original Windows-data recovery remains unresolved.

This is the current development companion to the
[frozen 63-page R5/RC1 course report](../release_report/README.md). The original
Word/PDF, UML models, migrations and RC tag retain their historical identities.
The documentation update requires no business migration or application restart.

## Source and reproduction 源稿与复核

`report_source.json` is the editable report text. `baseline.json` records only
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
