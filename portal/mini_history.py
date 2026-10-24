"""Own submitted history; appointment delegates cannot enter clinical reporting."""
import uuid
from django.core.paginator import Paginator
from django.views.decorators.debug import sensitive_post_parameters
from clinical.encounter_forms import HistoryForm
from clinical.clinical_payload import HISTORY_KEYS
from clinical.models import ClinicalHistoryVersion
from clinical.encounters import submit_history
from portal.mini_api import endpoint,result,validated
from portal.policies import patient_access


def history_data(row):
    return dict(id=row.pk,revision=row.revision,recorded_at=row.recorded_at.isoformat(),
        **{field:getattr(row,field) for field in HISTORY_KEYS})


@endpoint()
def listing(request):
    access=patient_access(request.user,self_only=True)
    rows=ClinicalHistoryVersion.objects.filter(patient_id=access.patient_id,source='SELF').order_by('-revision')
    latest=rows.first();page=Paginator(rows,20).get_page(request.GET.get('page'))
    return result(request,dict(rows=[history_data(r) for r in page],page=page.number,pages=page.paginator.num_pages,
        current_revision=latest.revision if latest else 0,latest=history_data(latest) if latest else None,operation_id=str(uuid.uuid4())))


@sensitive_post_parameters()
@endpoint(('POST',))
def submit(request):
    access=patient_access(request.user,self_only=True)
    data=validated(HistoryForm(request.POST));expected=data.pop('expected_revision');op=data.pop('operation_id');confirmed=data.pop('confirmed');data.pop('patient_binding',None)
    row,replay=submit_history(actor=request.user,fields=data,expected_revision=expected,operation_id=op,confirmed=confirmed)
    latest=ClinicalHistoryVersion.objects.filter(patient_id=access.patient_id,source='SELF').order_by('-revision').first()
    return result(request,dict(row=history_data(row),replayed=replay,current_revision=latest.revision,operation_id=str(uuid.uuid4())))
