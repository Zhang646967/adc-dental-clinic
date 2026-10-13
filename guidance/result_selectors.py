"""A narrow authorized read adapter; one SQL statement for related business facts."""
from django.db.models import FilteredRelation, Q
from coordination.policies import entries_for
from guidance.result_rules import VisitFact, OfferFact, WaitFact

# Do not select patient names, clinical notes, allergies, passwords, or model prompts.
FIELDS = ("id", "patient_id", "clinic_id", "state", "earliest", "latest",
    "relevant__id", "relevant__state", "relevant__slot__dentist_id", "relevant__slot__clinic_id",
    "relevant__starts_at", "relevant__ends_at", "relevant__expires_at", "relevant__visit_id",
    "relevant__visit__visit_no", "relevant__visit__patient_id", "relevant__visit__clinic_id",
    "relevant__visit__dentist_id", "relevant__visit__scheduled_start", "relevant__visit__scheduled_end",
    "relevant__visit__status")


def load_wait_fact(actor, pk):
    rows = list(entries_for(actor).filter(pk=pk).annotate(relevant=FilteredRelation(
        "offers", condition=Q(offers__state__in=("PENDING", "ACCEPTED"))))
        .order_by("relevant__id").values(*FIELDS)[:4])
    if not rows:
        return None
    r = rows[0]; offers = []
    for row in rows:
        if row["relevant__id"] is None:
            continue
        visit = None
        if row["relevant__visit_id"] is not None:
            visit = VisitFact(row["relevant__visit_id"], row["relevant__visit__visit_no"],
                row["relevant__visit__patient_id"], row["relevant__visit__clinic_id"],
                row["relevant__visit__dentist_id"], row["relevant__visit__scheduled_start"],
                row["relevant__visit__scheduled_end"], row["relevant__visit__status"])
        offers.append(OfferFact(row["relevant__id"], row["relevant__state"],
            row["relevant__slot__dentist_id"], row["relevant__slot__clinic_id"],
            row["relevant__starts_at"], row["relevant__ends_at"], row["relevant__expires_at"], visit))
    return WaitFact(r["id"], r["patient_id"], r["clinic_id"], r["state"], r["earliest"], r["latest"], tuple(offers))
