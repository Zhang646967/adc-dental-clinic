"""Coordination projections exclude clinical notes; management receives counts."""
from django.core.exceptions import PermissionDenied
from django.db.models import Q,Count
from django.shortcuts import get_object_or_404
from django.utils import timezone
from accounts.policies import bindings,require_clinic
from adc_core.snapshots import reporting_snapshot
from clinical.continuity_models import RecallEpisode,LabCase
from clinical.continuity_rules import available_front
from clinical.encounter_selectors import encounter_details
from clinical.next_visits import instruction_booking_projection,current_promise
from clinical.plan_models import NextVisitInstruction
from clinical.plan_locks import readable_services
from clinical import recall,laboratory,recall_worklist
from registry.models import Clinic
from workspaces.context import require_active


def recall_instructions(actor,queue='active'):
    rows=recall.scoped_instructions(actor).select_related('recall__owner')
    if queue=='active':rows=rows.filter(Q(state='OPEN',recall__isnull=True)|Q(recall__state__in=['OPEN','REVIEW']))
    elif queue=='unclaimed':rows=rows.filter(state='OPEN',recall__isnull=True)
    elif queue=='overdue':rows=rows.filter(recall__state__in=['OPEN','REVIEW'],recall__followup_due_at__lt=timezone.now())
    elif queue=='past_unbooked':
        rows=recall_worklist.available_instructions(rows).filter(latest_on__lt=timezone.localdate())
    elif queue in ('mine','later'):
        rows=recall_worklist.available_instructions(rows).filter(recall__owner=actor)
        tomorrow=recall_worklist.due_tomorrow(timezone.now())
        if queue=='mine':
            return rows.filter(recall__followup_due_at__lt=tomorrow).order_by('recall__followup_due_at','pk')
        return rows.filter(recall__followup_due_at__gte=tomorrow).order_by('recall__followup_due_at','pk')
    elif queue=='review':rows=rows.filter(state='OPEN',recall__state='REVIEW')
    elif queue=='completed':rows=rows.filter(recall__state='COMPLETED')
    elif queue=='withdrawn':rows=rows.filter(recall__state='WITHDRAWN')
    return rows.order_by('latest_on','pk')


def past_unbooked(data, episode):
    return (data['overdue'] and data['needs_booking'] and not data['report_review']
        and (episode is None or episode.state=='OPEN'))


def recall_projection(instruction):
    data=instruction_booking_projection(instruction)
    try:episode=instruction.recall
    except RecallEpisode.DoesNotExist:episode=None
    source=instruction.source_record.encounter.visit
    data.update(completion_rule=instruction.completion_rule,completion_label=instruction.get_completion_rule_display(),episode=episode,
        past_unbooked=past_unbooked(data,episode),
        owner_available=available_front(episode.owner_id,source.clinic_id) if episode else False,
        contact_overdue=bool(episode and episode.state in ('OPEN','REVIEW') and episode.followup_due_at<timezone.now()),
        evidence=recall.completion_candidates(instruction))
    return data


def recall_page_rows(page):
    from clinical.plan_models import PlanAppointment
    from scheduling.models import Visit
    rows=list(page)
    appointments={}
    sources={r.pk:r.source_record.encounter.visit for r in rows}
    links=PlanAppointment.objects.filter(instruction_id__in=sources).select_related('visit').order_by('-pk')
    pending=[(link.instruction_id,link.visit) for link in links]
    seen=set()
    while pending:
        rescheduled={}
        for instruction_id,current in pending:
            source=sources[instruction_id]
            key=instruction_id,current.pk
            if key in seen or (source.patient_id,source.clinic_id)!=(current.patient_id,current.clinic_id):
                continue
            seen.add(key)
            if current.status in ('SCHEDULED','CHECKED_IN'):
                appointments.setdefault(instruction_id,current)
            elif current.status=='RESCHEDULED':
                rescheduled.setdefault(current.pk,[]).append(instruction_id)
        pending=[(instruction_id,v) for v in Visit.objects.filter(replaces_visit_id__in=rescheduled)
            for instruction_id in rescheduled[v.replaces_visit_id]]
    for row in rows:
        episode=getattr(row,'recall',None)
        yield dict(id=row.pk,patient=row.source_record.encounter.visit.patient,service=row.service,
            earliest_on=row.earliest_on,latest_on=row.latest_on,episode=episode,completion_rule=row.completion_rule,
            booking_note=row.booking_note,completion_label=row.get_completion_rule_display(),owner_available=row.front_available,
            last_contact=recall_worklist.CONTACT_LABELS.get(row.contact_result),contact_at=row.contact_at,
            review_label=recall_worklist.review_label(row),appointment=appointments.get(row.pk),
            completion_available=row.goal_covered and row.pk not in appointments and row.completion_rule!='UNSPECIFIED')


def lab_projection(case):
    source=case.source_record.encounter.visit;step=case.step_version
    events=list(case.events.select_related('actor').order_by('-pk'))
    delay=next((e for e in events if e.action=='DELAY'),None)
    instruction_rows=NextVisitInstruction.objects.filter(source_record__encounter__visit__patient_id=source.patient_id,
        source_record__encounter__visit__clinic_id=source.clinic_id,step_version__step_id=step.step_id).order_by('pk')
    promises=[];seen=set()
    for instruction in instruction_rows:
        for link in instruction.appointment_links.select_related('visit'):
            visit=current_promise(link.visit)
            if visit.pk not in seen:
                promises.append(visit);seen.add(visit.pk)
    return dict(id=case.pk,case_no=case.case_no,patient=source.patient,service=step.service,state=case.state,state_label=case.get_state_display(),
        work_label=case.get_work_kind_display(),vendor=case.vendor_name,logistics_note=case.logistics_note,needed_on=case.needed_on,cycle=case.cycle,revision=case.revision,
        owner=case.coordinator,owner_available=available_front(case.coordinator_id,source.clinic_id) if case.coordinator_id else False,
        followup_due_at=case.followup_due_at,contact_overdue=bool(case.followup_due_at and case.followup_due_at<timezone.now() and case.state not in ('ACCEPTED','WITHDRAWN')),
        preparation_overdue=case.needed_on<timezone.localdate() and case.state not in ('ACCEPTED','WITHDRAWN'),
        expected_on=delay.snapshot.get('expected_on') if delay else None,has_delay=delay is not None,promises=promises,
        events=[dict(action=e.action,actor=e.actor.username,at=e.recorded_at,note=e.note,snapshot=e.snapshot) for e in events])


def clinician_cases(actor,visit_id):
    d=encounter_details(actor,visit_id);visit=d['visit']
    rows=LabCase.objects.filter(source_record__encounter__visit__patient_id=visit.patient_id,
        source_record__encounter__visit__clinic_id=visit.clinic_id,step_version__service_id__in=readable_services(actor,visit.clinic_id)).select_related('step_version__version','step_version__service','coordinator').order_by('-pk')
    return d,rows


def doctor_lab_queue(actor):
    require_active(actor,('DENTIST',))
    from clinical.authority import readable_assigned_visits
    sources=readable_assigned_visits(actor,actor.dentist_id,strict=True)
    return LabCase.objects.filter(source_record__encounter__visit_id__in=sources.values('pk'),step_version__service_id__in=readable_services(actor)).select_related(
        'source_record__encounter__visit__patient','source_record__encounter__visit__clinic','step_version__service').order_by('needed_on','pk')


def coordination_counts(actor):
    clinic=actor._adc_workspace.clinic_id
    require_active(actor,('FRONT_DESK',));require_clinic(actor,clinic)
    return dict(my_recalls=recall_instructions(actor,'mine').count(),review_recalls=recall_instructions(actor,'review').count(),
        unclaimed_recalls=recall_instructions(actor,'unclaimed').count(),
        overdue_recalls=recall_instructions(actor,'overdue').count(),
        unclaimed_lab=laboratory.front_cases(actor).filter(coordinator__isnull=True,state='REQUESTED').count(),
        lab_to_review=laboratory.front_cases(actor).filter(state='RECEIVED').count(),
        lab_pending=laboratory.front_cases(actor).filter(state__in=['REQUESTED','DISPATCHED','REWORK','RECEIVED']).count())


def coordination_summary(actor):
    require_active(actor,('MANAGER','HQ'));role=actor._adc_workspace.role
    if role=='MANAGER':
        clinic=actor._adc_workspace.clinic_id;require_clinic(actor,clinic,roles=('MANAGER',));clinics=Clinic.objects.filter(pk=clinic)
    else:
        if not bindings(actor).filter(role='HQ',scope_kind='CHAIN').exists():raise PermissionDenied('需要总部汇总范围。')
        clinics=Clinic.objects.all()
    with reporting_snapshot():
        rows=[];now=timezone.now()
        for clinic in clinics.order_by('clinic_code'):
            episodes=RecallEpisode.objects.filter(instruction__source_record__encounter__visit__clinic=clinic)
            instructions=NextVisitInstruction.objects.filter(source_record__encounter__visit__clinic=clinic)
            cases=LabCase.objects.filter(source_record__encounter__visit__clinic=clinic)
            rows.append(dict(clinic=clinic.name,recall_states=list(episodes.values('state').annotate(n=Count('pk')).order_by('state')),
                recall_overdue=episodes.filter(state__in=['OPEN','REVIEW'],followup_due_at__lt=now).count(),
                unclaimed=instructions.filter(state='OPEN',recall__isnull=True).count(),unspecified=instructions.filter(state='OPEN',completion_rule='UNSPECIFIED').count(),
                lab_states=list(cases.values('state').annotate(n=Count('pk')).order_by('state')),
                lab_overdue=cases.exclude(state__in=['ACCEPTED','WITHDRAWN']).filter(needed_on__lt=timezone.localdate(now)).count()))
        recall_labels=dict(RecallEpisode._meta.get_field('state').choices);lab_labels=dict(LabCase._meta.get_field('state').choices)
        for row in rows:
            for s in row['recall_states']:s['label']=recall_labels[s['state']]
            for s in row['lab_states']:s['label']=lab_labels[s['state']]
        return rows
