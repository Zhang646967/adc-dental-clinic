# C2.2 treatment continuity — source and isolated acceptance

Confirmed examination → retained plan version → exact patient decision → actual execution → unique charge source → independently reviewed settlement and next appointment.

## Business ownership

The clinical module owns the plan, stable step lineage, retained step versions, patient decisions, performed procedures and next-visit instruction. Patient/clinic identity is derived through the originating encounter and Visit, avoiding a second inconsistent identity pair. Scheduling owns every appointment, replacement chain and physical claim. Care owns published bill versions; finance owns reviewed cash. No estimate, plan decision or instruction posts money.

Every new professional operation requires the assigned visit's exact clinic/service/action authority, including synthetic preactivation. New plan steps additionally require that step's own service scope. Patient discussion content is released by confirming a version; working drafts are private. Website/native decisions are self-only. Appointment delegation grants no plan, history, financial or clinical-consent authority. Seven roles remain unchanged.

Mind map: module owner → defined operation → one patient/clinic → retained fact; clinical discussion, booking, billing and cash retain separate meanings.

## Plans and actual care

- One server-held draft per plan. Publishing appends an immutable version and its ordered steps. Amendments retain the previous version and require an explicit basis. Stable step identity preserves the connection to prior actual work.
- Decisions append ACCEPTED, DEFERRED or DECLINED against an exact step version. Manual recording needs the responsible clinician and a source reference. A revised version needs its own decision. Only one alternative in a mutual-exclusion group can be accepted at once; changing choice requires explicit disposition of the former choice.
- Unknown fees remain NULL. Base estimates and alternative options are separate; no invented combined total. Estimates never create a TreatmentRecord or invoice.
- Actual execution requires actual check-in, a confirmed current clinical source, an explicit mapped service and current professional scope. A planned execution also needs exact current-version acceptance and matching service/project/tooth/surface. Unplanned work needs an explicit reason.
- Each chargeable performed event calls the existing care operation and retains one typed original charge-line link and immutable snapshot in the same transaction. A completed stable step cannot be recharged merely by creating another plan version. Independent bill corrections retain original actual facts and original charges; the existing visit/line-number correction contract links copied bill versions without creating another performed event.
- PER_EXECUTION charges actual provided projects. ON_COMPLETION permits an explicitly explained PARTIAL stage without a charge line; the final COMPLETE execution charges the actual catalogue item. This provides no general doctor fee-waiver privilege. Zero-price approved catalogue projects retain their existing reason rule.
- A non-charged actual stage is TREATED care with a zero-total invoice, never NO_TREATMENT. Allergy review and original confirmation/total rules remain required. The additive final-care function admits only a typed stage; actual sources are also checked at commit. Old migration bytes and published financial history remain intact.
- Before publication, an explicit reasoned void retains the actual event and original snapshot and removes only its unpublished current line. Published actual sources cannot be voided here; clinical document lifecycle and wider terminal correction remain C3 work. No automatic refund or cash reversal occurs.

Discussion acceptance is not a qualified signature or procedure-specific informed consent. Synthetic software tests do not establish clinical suitability.

Mind map: exact version → explicit decision → actual provided event → original typed charge; partial, completed, zero-charge, estimate and financial correction stay distinct.

## Next-visit coordination

The responsible clinician specifies service, date window, clinical purpose and a separate minimal front-desk arrangement note. Source and dates are retained; changing the clinical instruction requires a new instruction and explicit disposition of the old one. Front desk can explicitly link a real same-patient/same-clinic/same-service future appointment within the window. No appointment is fabricated from a phone number or an instruction.

Original links remain immutable. Views follow the existing unique rescheduling chain; cancellation returns an actionable pending arrangement. Linking an appointment does not close clinical follow-up. Front-desk projections exclude examination, clinical purpose, plan estimates and tooth findings. HQ receives no new chart endpoint. C2.3 adds attributed recall work and defined actual-care completion, rather than treating contact or booking as completion.

Mind map: physician service/window → front-desk arrangement → retained appointment link → explicit reschedule/cancellation → continued clinical follow-up.

## Executed and remaining gates

This is an isolated C2.2 source candidate, not an installed release. C2.1 remains the installed application until the protected C2.2–C2.3 acceptance completes. The 45 previous migration files remain unchanged; two additive migrations introduce the ten owned tables and extend the final-care invariant. The 2026-10-24 isolated PostgreSQL observation has96 tables,264 SQL foreign keys,67 application triggers and95 ORM models; it is kept separately from the installed C2.1 ER snapshot.

Executed initial C2.2 gates: 50 PostgreSQL/website/native HTTP scenarios, all 1,104 prior source rules, 158 native source/transport checks, 45 mocked Page scenarios (36 prior plus 9 new), and official offline syntax compilation of 16 WXML pages. These are distinct from a real browser journey, final exact-version CI, WeChat runtime/device/experience, populated encrypted restore, protected installation and the new 30-minute capacity workload.

The final combined acceptance includes C2.3 recall/lab readiness, a five-clinic browser/native journey, the complete regression, exact implementation CI, observed ER/catalogues, populated independent restore and original-data/configuration comparison. Report and original installation are updated after those gates. Professional, real supplier, cloud, 24-hour and WeChat platform acceptance remain separate. Historical Windows data recovery remains UNRESOLVED.

Mind map: initial source evidence → real journey → dependent follow-up/readiness → full regression and capacity → observed ER → encrypted restore → exact CI → protected delivery.
