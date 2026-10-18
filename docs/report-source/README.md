# 报告源文件与复现说明

Case and notes → business/system models → explicit responsibilities → executed
evidence → protected delivery. Date: **2026-10-18**. Business runtime **`02a9dbc90583fbcad47567e64ae77ae810eca33f`**;
[exact application CI passed](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39134681755).


R2.3 independent-recovery host tools **`20961babacf909810bc3149fb92994fb408e8b8c`** passed [exact tool CI](https://github.com/Zhang646967/adc-dental-clinic/actions/runs/39145021878) and protected Mac synchronization. The report records 1,016 source/rule checks, 1,152 real PostgreSQL/HTTP/concurrency tests and 24 real-age/PG restore success/refusal checks. A separate empty target matched 51 tables and 29,144 rows; recovery, comparison and startup took 15.868 seconds. Transport was simulated locally. The original R2.3 first-increment evidence remains historical.

- [Word report](../../课程报告/课程报告_张加良_8210241102.docx)
- [PDF report](../../课程报告/课程报告_张加良_8210241102.pdf)
- [Readable Markdown report](REPORT.md)
- [Format reference and retained scope](FORMAT_REFERENCE.md)
- [R2.3 independent recovery and executed delivery](../evidence_r23/README.md)
- [R2.3 requirement-to-test trace](../evidence_r23/restore_requirement_trace.json)
- [R2.4 next-step acceptance plan](../R24_ACCEPTANCE_PLAN.md)
- [R2.2 implementation and executed delivery](../evidence_r22/README.md)
- [Requirement-to-test trace](../evidence_r22/requirement_trace.json)
- [R2 next-stage plan](../R2_OPERATIONAL_ASSURANCE_PLAN.md) and
  [ASVS gap register](../SECURITY_ASVS_GAP_REGISTER.md)

The report follows the supplied **86-page university course PDF format**, identified
by digest in the reference contract; the supplied PDF stays private and read-only.
The new report is **78 pages**: university cover, Chinese and English abstracts,
a checked two-page contents list, six main chapters, references and two specification
appendices. Chinese is the main text, with an English abstract and key technical terms.

All **SU-01—38 and SF-01** specifications, original AT-01—25 references and
19 original model figures are retained. Two historical UI observations are dated;
a current responsibility diagram and notification-overview capture are added.
The result contains **39 specifications, 55 numbered tables and 23 figures**.
Each main chapter ends with a mind map. All 48 contents entries agree with the PDF.
Long fields use repeated headers and explicit continuation where needed.

## Executed evidence and limits

R2.2 records **978 source/rule checks**, **1,145 real PostgreSQL/HTTP/concurrency
tests**, **32 live fault checks**, **869 isolated Chrome assertions**, a 20-check
independent financial oracle and an encrypted empty-target restore matching
**50** model/association fingerprints. Protected Mac verification passes **437**
authorized-read assertions and preserves **48** original durable fingerprints,
**70** original configurations, the original database volume and RC tag.

Runtime/browser/restore exercises ran at `ed7e10e`. Initial exact CI exposed
a legacy time-of-day-dependent row-cap fixture. Final application `02a9dbc`
changes that test, adds a midnight case and refreshes integrity files; the
22 previously tested source files and all runtime modules/configuration are
byte-identical. The final source passed the complete 1,145-test gate and exact CI,
and the Mac image/source/observer were verified at that final commit. This
relationship and the initial CI failure are retained in the evidence.

R1 capacity results remain dated **2026-10-15**: five clinics, twenty accounts and
thirty minutes. They do not establish the new full-R2 or twenty-clinic envelope.
R2.4 equivalent capacity/24-hour/security work and cloud
acceptance remain pending. The server has not been purchased. Original Windows-data
recovery remains unresolved. R2.2 operational files have a separate encrypted delivery snapshot. R2.3 format-2 backups include bounded private observation history, restored as historical bytes rather than live health.

This report replaces the current companion; the [frozen 63-page R5/RC1 report](../release_report/README.md),
original models, 30 migration files and RC tag preserve their historical bytes.
R2.2 adds no migration or business role.

## Sources and reproduction

`report_source.json` is editable text; `baseline.json` separately records R1/R2.1/R2.2 evidence and both R2.3 tool increments/digests. `build_report.py` reads the frozen
Word source only to retain models and full specifications, then generates Word in `课程报告/` and Markdown in this source directory. It needs Python with `python-docx`; it never accesses a database
or host credentials:

```sh
python docs/report-source/build_report.py
```

The responsibility-view PNG has a reproducible Pillow source in
`draw_operations_flow.py`, taking explicit output and font paths. The notification
capture is the sanitized current-clinic panel only. No private account guide,
CSV payload, dump, key or raw operational state is included.

Use `--output /absolute/output/folder` for an isolated draft. PDF export uses LibreOffice and Poppler. Fonts are Noto Serif CJK SC,
Noto Sans CJK SC and Liberation Serif; the PDF embeds its fonts.
[Official Noto CJK sources](https://github.com/notofonts/noto-cjk).
An editable Word rendering needs compatible fonts. After a new export, recheck
the rendered pages, update `toc_pages.json` from the Arabic page labels, rebuild
and repeat until the contents map is stable. Do not overwrite frozen RC files.

`validation.json` records the 78-page visual/structural/privacy review and source/
output hashes. The accepted application is updated separately; synchronizing this
documentation companion does not restart its five running services.

Mind map: retained case/specifications → current contracts → executed facts →
source and CI identity → readable course report → GitHub/Mac document synchronization.
