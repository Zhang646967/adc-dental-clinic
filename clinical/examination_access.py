"""Scope examination operations to their installation, project and source clinic."""
from django.conf import settings
from django.db.models import F
from django.http import Http404

from clinical.examination_models import ExaminationProject


def _mode():
    return (ExaminationProject.Mode.REHEARSAL if settings.ADC_CLINICAL_SYNTHETIC
            else ExaminationProject.Mode.SITE)


def filter_projects(rows):
    return rows.filter(operating_mode=_mode())


def filter_orders(rows, prefix=''):
    project = prefix + 'project__'
    return rows.filter(**{
        project + 'operating_mode': _mode(),
        project + 'service__department__clinic_id': F(prefix + 'source_record__encounter__visit__clinic_id'),
    })


def require_project(clinic_id, project_id, *, lock=False):
    rows = filter_projects(ExaminationProject.objects.all()).filter(pk=project_id,
        service__department__clinic_id=clinic_id)
    if lock:
        rows = rows.filter(service__department__clinic__is_active=True).select_for_update(of=('self',))
    project = rows.first()
    if project is None:
        raise Http404('该检查项目当前不可办理。')
    return project


def workflows_available(clinic_id=None):
    if settings.ADC_CLINICAL_SYNTHETIC:
        return True  # Existing rehearsal pages also support an empty queue.
    rows = filter_projects(ExaminationProject.objects.all())
    if clinic_id is not None:
        rows = rows.filter(service__department__clinic_id=clinic_id)
    return rows.exists()
