"""Patient-self disclosure controls. Appointment delegates have no clinical scope."""
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from portal.mini_api import endpoint,result,validated
from portal.policies import patient_access
from clinical import referrals
from clinical.forms import ConfirmForm
from adc_core.proposals import read_proposal
from adc_core.rules import RuleError


def row_data(row):
    return dict(id=row.pk,source=row.source_clinic.name,destination=row.destination_clinic.name,
        receiver=row.receiver.dentist.name,valid_until=row.valid_until.isoformat(),status=row.state,
        status_label=row.get_state_display(),can_stop=row.state in ('REQUESTED','IDENTITY_CONFIRMED','IDENTITY_DISPUTED','ACCEPTED'))


@endpoint()
def listing(request):
    patient_access(request.user,self_only=True)
    qs=referrals.visible_referrals(request.user).select_related('receiver__dentist').order_by('-created_at')
    page=Paginator(qs,20).get_page(request.GET.get('page'))
    return result(request,{'rows':[row_data(r) for r in page],'page':page.number,'pages':page.paginator.num_pages})


@endpoint(('POST',))
def stop_preview(request,pk):
    patient_access(request.user,self_only=True)
    row=referrals.visible_referrals(request.user).get(pk=pk)
    action='REVOKE' if row.state=='ACCEPTED' else 'WITHDRAW'
    p=referrals.prepare_referral(actor=request.user,action=action,referral_id=pk,
        fields={'note':'患者本人通过患者入口明确请求终止本次转诊披露'})
    return result(request,{'referral':row_data(row),'proposal_token':p['proposal_token']})


@endpoint(('POST',))
def stop_confirm(request,pk):
    patient_access(request.user,self_only=True)
    data=validated(ConfirmForm(request.POST))
    p=read_proposal(request.user,referrals.CONTRACT,referrals.ROLES,data['proposal_token'])
    if p['data'].get('referral_id')!=pk or p['data'].get('action') not in ('REVOKE','WITHDRAW'):
        raise RuleError('核对内容与此转诊不一致，请重新办理。')
    row,replay=referrals.confirm_referral(actor=request.user,**data)
    return result(request,{'referral':row_data(row),'replayed':replay})
