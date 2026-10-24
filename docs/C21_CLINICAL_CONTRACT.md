# C2.1 clinical encounter contract and ADR

Status: C2.1 locally delivered as synthetic software. Exact application CI, same-image business acceptance, populated encrypted recovery, original-copy upgrade and protected installation passed. The host-only safe-projection repair passed separate exact CI/install; retained UNKNOWN history is not erased. Detailed source/image and professional/platform limits are in the release record.
This is synthetic software verification, not a professionally approved clinical template.

Patient-reported history → attributed professional review → actual encounter →
versioned tooth/surface findings → safe draft/confirmation → clinical worklist.

- Scheduling owns Visit, patient and resource inventory; clinical never creates an encounter from a cancelled/unattended appointment.
- Clinical owns reported history versions, actual encounter identity, bounded drafts and confirmed record versions. Existing care owns published billing records and money. No chart or estimate automatically creates treatment or money.
- Keep the seven roles. Patient self may report history; appointment delegates cannot report/review clinical history. Assigned dentist requires current RECORD for the exact clinic/service on every mutation and READ on sensitive projections. All C2 operations always enforce scope, including synthetic clinics before legacy activation.
- Retain submitted and professionally reviewed facts separately. Unknown allergy remains unknown; the new history never replaces the existing explicit allergy review.
- One encounter per actually checked-in Visit. Patient and clinic derive from Visit; author, actual opening and recorded timestamps remain attributable. No historical encounters are fabricated by migration.
- Reported history and confirmed encounter versions are append-only. Drafts are bounded, server-saved with explicit revision and patient/encounter binding. Conflict responses retain entered work and identify the current saved revision. No browser persistent storage of clinical text.
- FDI permanent and primary tooth identifiers, explicit dentition and surface combinations use one validator for graphical buttons and keyboard selection. Unassessed, missing and negative observations are distinct. Clinical terminology and professional use await qualified review.
- Confirmed findings/notes retain the exact reported-history version and assessment/discrepancy, author, observation and recording times. Amendments append a new version with reason; C3 qualified signing/archive is separate.
- Worklist shows only authorized assigned encounters with draft/current-state and next action. Front desk/HQ get no clinical text.
- Website and native self-history share backend commands, subject selection and audit. No REST inventory fork.

Acceptance: report/review discrepancy retained; graph/keyboard same fact; primary/permanent/surface validation; unknown preserved; stale/two-tab/subject switch/revocation rejected without data loss; no second encounter or version on retry; clinic and seven-role rejection; browser 390px/keyboard; independent facts and actual ER; full PostgreSQL/exact CI; nonempty encrypted restoration and protected update.

Mind map: source claim → actual encounter → professional assessment → versioned finding → explicit confirmation → retained history; billing remains a separate actual-care bridge in C2.2.


Implemented design decisions (migration and business evidence are separate):

- Six owned tables: ClinicalHistoryVersion, ClinicalEncounter, ClinicalDraft, ClinicalRecordVersion, ToothFinding and ClinicalRecordEvent. Patient/clinic identity derives from the protected Visit. Existing care money records are not rewritten.
- Reported history is an explicit, confirmed append with expected patient-history revision and operation ID. Unknown/positive/reported-negative statuses are separately captured. It does not update Patient allergy facts. Only patient self or an authorized clinician interviewing this exact attended patient may submit.
- Draft notes and tooth rows are edited through ordinary bounded forms, not a JSON editor. A single shared server validator receives both chart-button and keyboard choices. At most 104 observations per version; absent findings remain unassessed. Whole-mouth narrative remains available for unsupported structured locations.
- Record confirmation signs only server-held draft digest, actor/encounter revision and current history cursor. It never trusts clinical values in hidden confirmation fields. New reported history after preview requires rechecking without discarding the existing draft.
- Draft changes and explicit discard have immutable operation events; confirmed records and findings are append-only. An amendment starts an explicit new working version with reason and preserves the original. Qualified signatures/archive are C3, not a saved-status flag.
- Share one public clinical lock operation with the old care commands: user/context/grant and current authority, existing sorted slot locks, visit, patient, encounter/draft. C2 always requires strict authority; legacy synthetic behavior remains explicitly bounded.
- Add an optional typed source-clinical-record reference to the existing referral. Exactly one legacy or structured published source can be selected. Receiving/identity/termination contracts are unchanged; no broader chain-chart search.
- The isolated PostgreSQL migration observed 86 tables, 225 SQL foreign keys, 56 application triggers and 45 migration files. All44 prior migration bytes, all80 prior tables, all749 actual prior SQL columns and all50 prior trigger definitions are unchanged. The actual ER/DBML/catalogue validates805 ORM columns, plus the framework migration journal.


## Executed workflow and remaining gates

- Website and native Page handlers use the same self-history commands. Graphical and keyboard tooth entry use the same server validator. Conflicted notes and self-history can compare current facts and retain entered work before explicit resubmission; there is no automatic overwrite or browser persistent draft storage.
- The five-clinic browser scenarios retained ten clinical versions and thirty tooth findings before explicit actual-treatment work. Ten original booking/care/financial table fingerprints and CNY50,000 invoice/CNY50,000 posted-cash totals were unchanged by the clinical input itself.
- Explicit allergy review, actual treatment and closure then used the original care commands. Selected historical structured records passed the existing identity/consent/named-receiver/termination flow; later versions were not substituted into the selected disclosure.
- Detailed execution, counts and final version identity are in `docs/evidence_c21/`. No qualified reviewer participation, WeChat runtime/device/experience, independent hosting, 24-hour operation or commercial clinical qualification is inferred. The new multi-visit capacity workload remains due with the C2.2–C2.3 final acceptance.

Mind map: own report + clinic interview → attributed assessment → actual encounter → bounded draft → explicit confirmed version → retained amendment; actual execution, money and qualified signature remain separate responsibilities.
