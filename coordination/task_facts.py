"""Bounded task evidence, acquired while the caller holds the source-slot lock.
Only aggregate facts are projected to managers. No contact/clinical fields read.
"""
from dataclasses import dataclass, replace
from django.db import connection
from django.utils import timezone
from care.models import AuditEvent
from coordination.models import WaitOffer
from scheduling.models import Visit
from scheduling.availability_rules import MAX_RELATIONS, assess_relations, digest
from scheduling.front_coordination_rules import relation_anomalies
from coordination.task_rules import TaskError

@dataclass(frozen=True)
class TaskObservation:
    slot: dict
    impact: object
    digest: str
    observed_at: object
    visits: tuple
    offers: tuple


def _rows(qs, fields):
    return [{k:v.isoformat() if hasattr(v,'isoformat') else v for k,v in row.items()}
            for row in qs.values(*fields)[:MAX_RELATIONS+1]]


def observe_locked(slot):
    if not connection.in_atomic_block:
        raise RuntimeError('Task observation requires the source-slot transaction/lock protocol')
    now = timezone.now()
    facts = dict(slot_id=slot.pk,clinic_id=slot.clinic_id,dentist_id=slot.dentist_id,
        starts_at=slot.starts_at.isoformat(),ends_at=slot.ends_at.isoformat(),
        is_active=slot.is_active,booking_paused=slot.booking_paused,intake_revision=slot.intake_revision)
    vq = Visit.objects.filter(availability_slot_id=slot.pk).order_by('pk')
    oq = WaitOffer.objects.filter(slot_id=slot.pk).order_by('pk')
    vc,oc = vq.count(),oq.count()
    visits = _rows(vq,('id','availability_slot_id','clinic_id','dentist_id','patient_id',
        'scheduled_start','scheduled_end','status','lock_version'))
    offers = _rows(oq,('id','slot_id','request_id','request__clinic_id','request__patient_id',
        'request__state','starts_at','ends_at','expires_at','state','visit_id'))
    impact = assess_relations(slot=facts,visits=visits,offers=offers,now=now,visit_count=vc,offer_count=oc)
    impact = replace(impact,anomalies=impact.anomalies + relation_anomalies(slot_id=slot.pk,visits=visits,offers=offers))
    cursor = AuditEvent.objects.filter(subject_type='availabilityslot',subject_key=str(slot.pk)).order_by('-pk').values_list('pk',flat=True).first() or 0
    fingerprint = digest(dict(slot=facts,visits=visits,offers=offers,visit_count=vc,offer_count=oc,cursor=cursor))
    return TaskObservation(facts,impact,fingerprint,now,tuple(visits),tuple(offers))


def check_statement_target(observation, *, kind, target_id):
    if not kind and target_id is None: return
    if observation.impact.too_many or observation.impact.anomalies:
        raise TaskError('关联资料需受控核对，不能将声明附到可疑对象；可记录需要主管协助。')
    rows = observation.visits if kind == 'visit' else observation.offers if kind == 'offer' else ()
    if not any(row['id'] == target_id for row in rows):
        raise TaskError('声明对象不存在或不属于本出诊，请从本店出诊协调重新核对。')
