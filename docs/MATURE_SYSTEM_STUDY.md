# Mature systems study and ADC development 成熟系统学习与开发路线

Requirements → business continuity → evidence and responsibility → operational
quality → measured expansion. The selected target is one chain with 5–20 clinics.
International workflows inform the design; the present implementation continues
with synthetic CNY data and Asia/Shanghai business dates.

## Learning from the course notes

The supplied `note__3.pdf` separates requirements from design and connects goals
and constraints to code. Its requirements criteria and abstract-model approach
support a trace from actor and observable behavior to invariants, preconditions,
postconditions and tests. `note__5.pdf` adds separation of concerns, simplicity,
restricted visibility and information hiding. These principles favor clear
module ownership and explicit operations as the system grows.

This release applies those principles to payment evidence. The internal cash
ledger owns posted money; the evidence module owns versions and correspondence.
Importing or matching evidence cannot silently become a cash command. Cross-module
effects, such as invalidating a match after a new evidence version, have explicit
transactional contracts. These clinic-specific rules are project decisions rather
than requirements prescribed by the lecture.

Mind map: requirement → actor → observable result → invariant → module operation
→ adverse case → acceptance evidence.

## Reference capabilities and current gaps

The references establish documented capabilities, not measured performance or
security comparisons. The gaps below are the project's assessment of ADC's
implemented behavior at the start of R1.

| Capability | Reference behavior | ADC development direction |
|---|---|---|
| Clinical continuity | Open Dental retains treatment plans, procedures and patient signatures, and tracks recall dates/status | Extend existing single-visit care with plan revisions, actual execution and follow-up responsibilities |
| Patient financial account | Open Dental payment splits allocate funds to procedures and support prepayments | Preserve current reviewed cash while designing future bill allocation and prepayments |
| Statement reconciliation | Odoo matches transaction evidence to business records and retains unmatched differences | R1 adds scoped evidence, private CSV import and independently reviewed exact matches |
| Resource scheduling | Dentrix Ascend combines authorized locations, operatories and providers | Introduce resource definitions and explicit reservation/maintenance coordination after the clinical contract |
| Equipment operations | Odoo tracks preventive/corrective maintenance, teams and schedules | Extend existing accountable repair cases with recurring plans, parts/vendors and resource linkage |
| Sustained operation | Google SRE connects monitoring and service objectives to reliability decisions | Add continuous operational visibility, useful alerts, incident responsibility and recovery exercises |
| Security assurance | OWASP ASVS provides versioned, testable technical requirements | Assess authentication, sensitive reads, retention and operational security beyond existing business authorization tests |

References:

- [Open Dental treatment plans](https://www.opendental.com/manual/treatmentplan.html),
  [recall](https://www.opendental.com/manual/recall.html), and
  [payments](https://www.opendental.com/manual/payment.html).
- [Odoo statement reconciliation](https://www.odoo.com/documentation/19.0/applications/finance/accounting/bank/reconciliation.html)
  and [maintenance requests](https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/maintenance/maintenance_requests.html).
- [Dentrix Ascend multi-location scheduling](https://learn.dentrixascend.com/multi-location-scheduling/).
- [Google SRE service objectives](https://sre.google/workbook/implementing-slos/),
  [monitoring](https://sre.google/workbook/monitoring/),
  [AWS reliability principles](https://docs.aws.amazon.com/wellarchitected/latest/framework/rel-dp.html),
  and [OWASP ASVS](https://owasp.org/projects/asvs).

Mind map: continuity → patient plans; evidence → allocations/reconciliation;
resources → schedule/maintenance; operation → service objectives/security/recovery.

## Ordered increments

| Increment | Intended result | Gate |
|---|---|---|
| R1 financial evidence | Retained payment references, import evidence, exact correspondence and differences | [R1 contract](FINANCIAL_EVIDENCE_RECONCILIATION.md), full regression, browser/load/oracles, recovery and protected Mac update |
| R2 operational assurance | Diagnose affected workflows, monitor worker/backup freshness and recover a known version | Fault exercises and security gap register; actual host acceptance after server provisioning |
| R3 treatment continuity | Plan revisions, recorded patient acceptance, actual multi-visit execution and follow-up | Synthetic multi-visit scenario; bills only from completed actual treatments |
| R4 resource coordination | Preventive maintenance with explicit chair/room/equipment scheduling | Concurrent reservation/maintenance cases preserve protected appointments |
| R5 expansion validation | Measured envelope for twenty clinics | Representative clinical/financial/scheduling contention and independent-host recovery |

Keep the modular Django/PostgreSQL application and current worker while developing
module contracts. Revisit service extraction when a measured scaling, independent
deployment or ownership need justifies its distributed consistency and operational
costs. [Microservice trade-offs](https://martinfowler.com/articles/microservice-trade-offs.html)

R1 is the implemented increment; R2–R5 require their own detailed business
contracts before implementation. Twenty-clinic operation, separate customer
tenancy, international currency/timezone deployment, real payment/insurance
integration and real patient use are separate acceptance targets. The five-clinic
local baseline remains a bounded workload result. Cloud hosting still awaits a
server; original Windows-data recovery remains unresolved.

Mind map: owned module rules → R1 money evidence → R2 operation → R3 care journey
→ R4 physical resources → R5 measured growth → independently accepted deployment.
