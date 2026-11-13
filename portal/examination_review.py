"""Read only the release currently selected for the patient's own visit."""
from django.conf import settings
from django.db.models import Exists, F, OuterRef
from django.http import Http404

from clinical.examination_models import ExaminationEvent, ExaminationOrder

PUBLISH = ExaminationEvent.Action.PUBLISH


def _orders(visit):
    return ExaminationOrder.objects.filter(source_record__encounter__visit=visit)


def examination_summaries(visit, access):
    if access.delegated or not settings.ADC_CLINICAL_SYNTHETIC:
        return []
    published = ExaminationEvent.objects.filter(order_id=OuterRef('pk'), action=PUBLISH)
    rows = _orders(visit).annotate(ever_released=Exists(published)).order_by('requested_at', 'pk').values(
        'pk', 'number', 'project_name', 'requested_at', 'ever_released', 'active_release__report__number',
        'active_release__occurred_at',
    )
    result = []
    for row in rows:
        revision = row['active_release__report__number']
        if revision is not None:
            state, label = 'PUBLISHED', '检查报告可查阅'
        elif row['ever_released']:
            state, label = 'WITHDRAWN', '报告已撤回，请联系门店'
        else:
            state, label = 'PROCESSING', '检查办理中'
        result.append(dict(id=row['pk'], number=row['number'], project=row['project_name'],
            requested_at=row['requested_at'], state=state, label=label, revision=revision,
            released_at=row['active_release__occurred_at']))
    return result


def published_examination(visit, order_id, revision=None):
    if not settings.ADC_CLINICAL_SYNTHETIC:
        raise Http404
    rows = _orders(visit).filter(pk=order_id, active_release__action=PUBLISH, active_release__order=F('pk'),
        active_release__report__order=F('pk')).values(
        'pk', 'number', 'project_name', 'performed_at', 'active_release__report__number',
        'active_release__occurred_at', 'active_release__report__body',
    )
    row = rows.first()
    if row is None or (revision is not None and revision != str(row['active_release__report__number'])):
        raise Http404
    return dict(id=row['pk'], number=row['number'], project=row['project_name'], visit_id=visit.pk,
        visit_no=visit.visit_no, performed_at=row['performed_at'], revision=row['active_release__report__number'],
        released_at=row['active_release__occurred_at'], body=row['active_release__report__body'])
