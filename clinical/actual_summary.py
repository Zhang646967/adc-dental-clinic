"""Minimal actual-work facts for care/financial projections, without chart text."""
from clinical.plan_models import PerformedProcedure


def actual_care_summary(visit_id):
    rows=list(PerformedProcedure.objects.filter(encounter__visit_id=visit_id,state='ACTIVE').only('pk','charge_mode','charge_snapshot','quantity'))
    stages=[]
    for row in rows:
        if row.charge_mode=='NO_CHARGE':
            q=row.charge_snapshot
            stages.append(dict(id=row.pk,name_snapshot=q['name'],unit_snapshot=q['unit'],quantity=str(row.quantity)))
    return dict(provided=bool(rows),stage_no_charge=bool(stages),no_charge_stages=stages)


def bind_performed_sources(lines):
    # The correction contract retains visit/line number; copies are bill versions,
    # not new actual procedures or a second charge source.
    visits={line.record_version.visit_id for line in lines}
    mapping={(visit,number):pk for visit,number,pk in PerformedProcedure.objects.filter(charge_line__record_version__visit_id__in=visits).values_list(
        'charge_line__record_version__visit_id','charge_line__line_no','pk')} if visits else {}
    for line in lines:line.performed_source_id=mapping.get((line.record_version.visit_id,line.line_no))
