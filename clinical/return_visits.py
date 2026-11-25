"""Facts carried from an explicitly linked visit. No writes or clinical inference."""
from collections import defaultdict

from django.conf import settings
from django.db.models import Exists, F, OuterRef, Subquery

from clinical.authority import readable_assigned_visits, visit_service_id
from clinical.encounter_models import ClinicalRecordVersion, ToothFinding
from clinical.examination_followup import linked_instructions
from clinical.examination_models import ExaminationFollowup, ExaminationReport
from clinical.plan_locks import readable_services
from clinical.plan_models import NextVisitInstruction, PerformedProcedure, PlanStepVersion, PlanVersion
from clinical.tooth_rules import SURFACES

SOURCE = 'instruction__source_record'
ORIGIN = SOURCE + '__encounter__visit'
STEP = 'instruction__step_version'
RELEASE = 'report_followup__release'
ORDER = RELEASE + '__order'
VISIBLE_VISIT_STATES = {'SCHEDULED', 'CHECKED_IN', 'COMPLETED', 'CLOSED_NO_TREATMENT'}


def _links(visit, *, origins=None):
    if visit.status not in VISIBLE_VISIT_STATES:
        return []
    links = linked_instructions(visit).exclude(**{ORIGIN: visit.pk})
    if origins is not None:
        links = links.filter(**{ORIGIN + '__in': origins.values('pk')})
    head = ClinicalRecordVersion.objects.filter(encounter_id=OuterRef(SOURCE + '__encounter_id')).order_by('-revision')
    plan_head = PlanVersion.objects.filter(plan_id=OuterRef(STEP + '__version__plan_id')).order_by('-revision')
    decisions = ExaminationFollowup.objects.filter(release_id=OuterRef(ORDER + '__active_release_id')).order_by('-pk')
    # Reselecting an updated instruction after a reschedule supersedes its older
    # link. Independent instructions remain independent even for one original visit.
    return list(links.order_by('instruction_id', '-pk').distinct('instruction_id').values(
        'instruction_id', source_id=F(ORIGIN + '_id'), source_no=F(ORIGIN + '__visit_no'),
        record_pk=F('instruction__source_record_id'), record_revision=F(SOURCE + '__revision'),
        latest_record=Subquery(head.values('revision')[:1]),
        instruction_state=F('instruction__state'), recall_state=F('instruction__recall__state'),
        service_id=F('instruction__service_id'),
        service=F('instruction__service__name'), step_version=F('instruction__step_version_id'),
        plan_version=F(STEP + '__version_id'), current_plan=Subquery(plan_head.values('pk')[:1]),
        linked_release=F('report_followup__release_id'), live_release=F(ORDER + '__active_release_id'),
        release_action=F(RELEASE + '__action'), report_id=F(ORDER + '_id'), report_no=F(ORDER + '__number'),
        project=F(ORDER + '__project_name'), project_service=F(ORDER + '__project__service_id'),
        report_origin=F(ORDER + '__source_record__encounter__visit_id'),
        report_pk=F(RELEASE + '__report_id'), report_order=F(RELEASE + '__report__order_id'),
        report_revision=F(RELEASE + '__report__number'), bound_instruction=F('report_followup__instruction_id'),
        current_instruction=Subquery(decisions.values('instruction_id')[:1]),
        has_report=Exists(ExaminationFollowup.objects.filter(instruction_id=OuterRef('instruction_id')))))


def _patient_fields(row, visit_service):
    current = (row['instruction_state'] == 'OPEN' and row['recall_state'] not in ('REVIEW', 'WITHDRAWN')
               and row['service_id'] == visit_service
               and row['record_revision'] == row['latest_record'] and row['plan_version'] == row['current_plan'])
    report = None
    if row['has_report'] or row['linked_release']:
        current = bool(current and settings.ADC_CLINICAL_SYNTHETIC and row['linked_release']
                       and row['linked_release'] == row['live_release'] and row['release_action'] == 'PUBLISH'
                       and row['report_origin'] == row['source_id'] and row['report_order'] == row['report_id']
                       and row['bound_instruction'] == row['current_instruction'] == row['instruction_id'])
        if current:
            report = dict(id=row['report_id'], number=row['report_no'], project=row['project'], revision=row['report_revision'])
    return dict(source_visit_id=row['source_id'], source_visit_no=row['source_no'], service=row['service'],
                state='CURRENT' if current else 'CONTACT',
                label='已关联原就诊' if current else '复诊依据有变化，请联系原门店核对。', report=report)


def patient_sources(visit, access):
    from portal.service_catalogue import complete, published_profiles
    if access.delegated or access.patient_id != visit.patient_id:
        return []
    rows = _links(visit)
    if not rows:
        return []
    offerings = published_profiles().filter(service_id__in={row['service_id'] for row in rows})
    titles = {p.service_id: p.title for p in offerings if complete(p)}
    service_id = visit_service_id(visit)
    return [dict(_patient_fields(row, service_id), service=titles.get(row['service_id'], row['service'])) for row in rows]


def location(tooth, surface):
    if tooth is None:
        return '未指定牙位'
    faces = '、'.join(SURFACES.get(code, code) for code in surface)
    return f'{tooth} 牙 · {faces}' if faces else f'{tooth} 牙 · 牙面未指定'


def chairside_sources(actor, visit):
    """The caller has verified strict READ on this visit inside its snapshot."""
    origins = readable_assigned_visits(actor, actor.dentist_id, strict=True)
    rows = _links(visit, origins=origins)
    if not rows:
        return []
    scopes = readable_services(actor, visit.clinic_id)
    service_id = visit_service_id(visit)
    rows = [row for row in rows if row['service_id'] in scopes]
    instructions = NextVisitInstruction.objects.filter(pk__in=[r['instruction_id'] for r in rows]).select_related(
        'step_version__version__plan__origin_encounter__visit')
    steps = {i.pk: i.step_version for i in instructions}
    unreadable_plans = set(PlanStepVersion.objects.filter(
        version_id__in={step.version_id for step in steps.values() if step}
    ).exclude(service_id__in=scopes).values_list('version_id', flat=True))
    findings = defaultdict(list)
    for finding in ToothFinding.objects.filter(record_id__in={row['record_pk'] for row in rows
            if row['record_revision'] == row['latest_record']}).only('record_id', 'tooth', 'surface', 'kind'):
        findings[finding.record_id].append(f'{location(finding.tooth, finding.surface)} · {finding.get_kind_display()}')
    # The last execution is read from its originating encounter and the stable
    # step identity. Voided rows, similar teeth and unrelated procedures never match.
    procedures = PerformedProcedure.objects.filter(
        encounter__visit_id__in={r['source_id'] for r in rows}, state='ACTIVE',
        step_version__step_id__in={step.step_id for step in steps.values() if step}
    ).order_by('encounter__visit_id', 'step_version__step_id', '-observed_at', '-pk').distinct(
        'encounter__visit_id', 'step_version__step_id').values(
            'encounter__visit_id', 'step_version__step_id', 'step_version__service_id', 'tooth', 'surface', 'progress')
    actual = {(p['encounter__visit_id'], p['step_version__step_id']): p for p in procedures
              if p['step_version__service_id'] in scopes}
    result = []
    report_keys = []
    for row in rows:
        entry = _patient_fields(row, service_id)
        step = steps.get(row['instruction_id'])
        if step:
            origin = step.version.plan.origin_encounter.visit
            if (origin.patient_id, origin.clinic_id) != (visit.patient_id, visit.clinic_id) or step.version_id in unreadable_plans:
                continue
        p = actual.get((row['source_id'], step.step_id)) if step else None
        entry.update(record_revision=row['record_revision'], latest_record=row['latest_record'],
                     plan_revision=step.version.revision if step else None,
                     location=location(step.tooth, step.surface) if step else '复诊指示未指定牙位',
                     stage=step.description if step else '', findings=findings[row['record_pk']], actual=None)
        if p:
            entry['actual'] = dict(location=location(p['tooth'], p['surface']),
                                   label=dict(PerformedProcedure._meta.get_field('progress').choices)[p['progress']])
        if entry['report'] and row['project_service'] in scopes:
            report_keys.append((row['report_pk'], entry['report']))
        else:
            entry['report'] = None
        result.append(entry)
    bodies = dict(ExaminationReport.objects.filter(pk__in=[pk for pk, _ in report_keys]).values_list('pk', 'body'))
    for pk, report in report_keys:
        report['body'] = bodies[pk]
    return result
