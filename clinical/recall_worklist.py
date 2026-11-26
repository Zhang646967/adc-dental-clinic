"""Read-only, pageable follow-up work. Confirmations use the original clinical commands."""
from datetime import datetime, time, timedelta

from django.db.models import BooleanField, Exists, F, Func, IntegerField, OuterRef, Q, Subquery
from django.db.models.functions import Cast
from django.utils import timezone

from accounts.models import RoleAssignment
from clinical.continuity_models import RecallEvent
from clinical.examination_models import ExaminationFollowup
from clinical.plan_models import PlanVersion


class CoveredInstruction(Func):
    """An explicit appointment, its current successor, or qualifying actual care covers the goal.

    This correlated PostgreSQL expression keeps counting, ordering and paging in the database.
    Its clinical predicates mirror recall.completion_candidates; equivalence is tested on PG.
    """
    output_field = BooleanField()
    template = """EXISTS (
      WITH RECURSIVE chain(id, status) AS (
        SELECT v.id, v.status FROM adc_plan_appointment l JOIN adc_visit v ON v.id = l.visit_id
        WHERE l.instruction_id = %(expressions)s
        UNION
        SELECT v.id, v.status FROM chain c JOIN adc_visit v ON v.replaces_visit_id = c.id
        WHERE c.status = 'RESCHEDULED'
      )
      SELECT 1 FROM chain c
      JOIN adc_visit v ON v.id = c.id
      JOIN adc_next_visit_instruction i ON i.id = %(expressions)s
      JOIN adc_clinical_record_version src ON src.id = i.source_record_id
      JOIN adc_clinical_encounter encounter ON encounter.id = src.encounter_id
      JOIN adc_visit origin ON origin.id = encounter.visit_id
      WHERE v.patient_id = origin.patient_id AND v.clinic_id = origin.clinic_id
      AND (c.status IN ('SCHEDULED','CHECKED_IN') OR
        (c.status IN ('COMPLETED','CLOSED_NO_TREATMENT') AND
          (i.completion_rule = 'UNSPECIFIED' OR
           (v.id <> origin.id AND EXISTS (
              SELECT 1 FROM adc_resource_plan rp WHERE rp.visit_id = v.id AND rp.is_current AND rp.service_id = i.service_id
            ) AND EXISTS (
              SELECT 1 FROM adc_clinical_encounter e WHERE e.visit_id = v.id AND (
                (i.completion_rule = 'EXAM_CONFIRMED' AND (
                  SELECT (r.observed_at AT TIME ZONE 'Asia/Shanghai')::date FROM adc_clinical_record_version r
                  WHERE r.encounter_id = e.id AND r.observed_at >= i.recorded_at ORDER BY r.revision DESC LIMIT 1
                ) >= i.earliest_on) OR
                (i.completion_rule = 'STEP_COMPLETED' AND EXISTS (
                  SELECT 1 FROM adc_performed_procedure p WHERE p.encounter_id = e.id
                  AND p.step_version_id = i.step_version_id AND p.state = 'ACTIVE' AND p.progress = 'COMPLETE'
                  AND p.observed_at >= i.recorded_at AND (p.observed_at AT TIME ZONE 'Asia/Shanghai')::date >= i.earliest_on
                ))
              )
            ))
          )
        )
      )
    )"""


def available_instructions(rows, *, ordinary_only=False):
    rows = rows.filter(state='OPEN').filter(Q(recall__isnull=True) | Q(recall__state='OPEN'))
    reports = ExaminationFollowup.objects.filter(instruction_id=OuterRef('pk'))
    current_plan = PlanVersion.objects.filter(plan_id=OuterRef('step_version__version__plan_id')).order_by('-revision')
    rows = rows.filter(Q(step_version__isnull=True) | Q(step_version__version_id=Subquery(current_plan.values('pk')[:1])))
    if ordinary_only:
        rows = rows.filter(~Exists(reports))
    else:
        latest = ExaminationFollowup.objects.filter(release_id=OuterRef('release_id')).order_by('-pk')
        current = reports.filter(release_id=F('release__order__active_release_id'), release__action='PUBLISH',
            pk=Subquery(latest.values('pk')[:1]))
        rows = rows.filter(~Exists(reports) | Exists(current))
    return rows.filter(~CoveredInstruction(F('pk')))


def due_tomorrow(now):
    return datetime.combine(timezone.localdate(now) + timedelta(days=1), time.min, tzinfo=timezone.get_default_timezone())


CONTACT_LABELS = {'REACHED': '已接通', 'NO_ANSWER': '未接通', 'DECLINED': '本人暂缓', 'COORDINATION': '内部协调'}
DECISIONS = {'HOLD': '继续暂缓，由患者主动联系', 'COORDINATE': '门店内部核对后续安排'}


def review_facts(rows):
    """Match a review to this decline and instruction version, including after a later pause."""
    events = RecallEvent.objects.filter(episode_id=OuterRef('recall__pk')).order_by('-pk')
    declines = events.filter(action='CONTACT', snapshot__outcome='DECLINED')
    reviews = events.filter(action='DENTIST_REVIEW').annotate(
        evidence_revision=Cast('snapshot__instruction_revision', IntegerField())).filter(evidence_revision=OuterRef('revision'))
    return rows.annotate(decline_id=Subquery(declines.values('pk')[:1]),
        review_event_id=Subquery(reviews.values('pk')[:1]),
        review_decision=Subquery(reviews.values('snapshot__decision')[:1]))


def front_page(rows):
    front = RoleAssignment.objects.filter(user_id=OuterRef('recall__owner_id'), user__is_active=True,
        role='FRONT_DESK', scope_kind='CLINIC', clinic_id=OuterRef('source_record__encounter__visit__clinic_id'), is_active=True)
    contacts = RecallEvent.objects.filter(episode_id=OuterRef('recall__pk'), action='CONTACT').exclude(
        snapshot__outcome='COORDINATION').order_by('-pk')
    return review_facts(rows).annotate(front_available=Exists(front), goal_covered=CoveredInstruction(F('pk')),
        contact_result=Subquery(contacts.values('snapshot__outcome')[:1]), contact_at=Subquery(contacts.values('recorded_at')[:1]))


def review_label(row):
    if row.review_event_id and row.decline_id and row.review_event_id > row.decline_id:
        return DECISIONS.get(row.review_decision, '')
    return ''
