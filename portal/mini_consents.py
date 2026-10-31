"""Patient-only medical decision transport, sharing website commands."""
from django.core.exceptions import PermissionDenied
from django.views.decorators.debug import sensitive_post_parameters
from adc_core.proposals import read_proposal
from clinical import consents
from clinical.consent_forms import ConsentActionForm
from clinical.consent_selectors import details
from clinical.plan_forms import ConfirmPlanActionForm
from portal.mini_api import endpoint, result, validated


@endpoint()
def detail(request, step_id):
    return result(request, details(request.user, step_id, revision=request.GET.get('revision'))['data'])


@sensitive_post_parameters()
@endpoint(('POST',))
def preview(request, step_id):
    form = ConsentActionForm(request.POST);validated(form);action, version, fields = form.values()
    p = consents.prepare(actor=request.user, action=action, step_id=step_id, version_id=version, fields=fields)
    return result(request, dict(proposal_token=p['proposal_token'], **p['data']))


@sensitive_post_parameters()
@endpoint(('POST',))
def confirm(request, step_id):
    values = validated(ConfirmPlanActionForm(request.POST))
    data = read_proposal(request.user, consents.CONTRACT, ('PATIENT',), values['proposal_token'])['data']
    if data['step'] != step_id or data['visit'] is not None:raise PermissionDenied('请核对本人原步骤的决定。')
    row, replay = consents.confirm(actor=request.user, **values)
    return result(request, dict(event=row.pk, action=row.action, version=row.version_id, replayed=replay))
