"""Patient-owned notice projection and explicit in-app acknowledgement."""
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.http import Http404
from django.utils import timezone

from accounts.policies import require_writable
from adc_core.snapshots import reporting_snapshot
from clinical.examination_access import filter_orders, filter_projects, require_project
from clinical.examination_models import ExaminationNotice, ExaminationOrder, ExaminationProject
from portal.policies import patient_access
from scheduling.models import Visit

SOURCE = 'event__order__source_record__encounter__visit'


def _has_inbox(access):
    if settings.ADC_CLINICAL_SYNTHETIC:
        return True
    clinics = Visit.objects.filter(patient_id=access.patient_id, clinic__is_active=True).values('clinic_id')
    projects = ExaminationProject.objects.filter(service__department__clinic_id__in=clinics)
    return filter_projects(projects).exists()


def _owned(access):
    rows = ExaminationNotice.objects.filter(**{SOURCE + '__patient_id': access.patient_id,
        SOURCE + '__clinic__is_active': True})
    return filter_orders(rows, prefix='event__order__')


def _current(rows):
    latest = ExaminationNotice.objects.filter(event__order_id=OuterRef('event__order_id')).order_by('-pk')
    return rows.filter(pk=Subquery(latest.values('pk')[:1]))


def unread_count(access):
    if access.delegated or not _has_inbox(access):
        return None
    return _current(_owned(access)).filter(read_at__isnull=True).count()


def listing(actor, page_number):
    with reporting_snapshot():
        access = patient_access(actor, self_only=True)
        if not _has_inbox(access):
            raise Http404
        rows = _current(_owned(access)).select_related(
            SOURCE + '__clinic__public_directory', 'event__report').order_by('-event__occurred_at', '-pk')
        page = Paginator(rows, 20).get_page(page_number)
        data = []
        for row in page:
            event = row.event
            visit = event.order.source_record.encounter.visit
            data.append(dict(id=row.pk, kind=row.kind, title=row.get_kind_display(), project=event.order.project_name,
                clinic=visit.clinic.public_contact['name'],
                occurred_at=event.occurred_at, read_at=row.read_at, visit_id=visit.pk, examination_id=event.order_id,
                revision=event.report.number if row.kind != ExaminationNotice.Kind.WITHDRAWN else None))
        return dict(rows=data, unread_count=rows.filter(read_at__isnull=True).count(), page=page.number,
            has_previous=page.has_previous(), has_next=page.has_next())


@transaction.atomic
def mark_read(actor, notice_id):
    require_writable(actor)
    access = patient_access(actor, lock=True, self_only=True)
    rows = _owned(access)
    source = rows.filter(pk=notice_id).values_list('event__order_id', SOURCE + '__clinic_id',
        'event__order__project_id').first()
    if source is None:
        raise Http404
    order_id, clinic_id, project_id = source
    require_project(clinic_id, project_id, lock=True)
    # A correction or withdrawal serializes with a click on the original notice.
    ExaminationOrder.objects.select_for_update().get(pk=order_id)
    row = _current(rows).filter(pk=notice_id).first()
    if row is None:
        raise Http404
    if row.read_at is None:
        row.read_at = timezone.now()
        row.save(update_fields=['read_at'])
    return dict(id=row.pk, read_at=row.read_at, unread_count=unread_count(access))
