from django.db.models import Q
from django.shortcuts import get_object_or_404
from adc_core.proposals import read_proposal
from workspaces.context import require_active
from django.core.exceptions import PermissionDenied
from clinical.plan_forms import ConfirmPlanActionForm
from portal import medical_proxies as svc
from portal.medical_forms import ProxyActionForm
from portal.medical_models import MedicalProxy
from portal.medical_projection import case_data
from portal.models import PatientAccess
from portal.mini_api import endpoint,result,validated


@endpoint(subject_optional=True)
def listing(request):
    from portal.account_access import account_context
    account_context(request)
    own=PatientAccess.objects.filter(user=request.user,is_active=True).values('patient_id')
    cases=MedicalProxy.objects.filter(Q(delegate=request.user)|Q(patient_id__in=own)).select_related('patient','clinic','delegate').order_by('-pk')[:50]
    return result(request,dict(rows=[case_data(request.user,c,account=True) for c in cases]))


@endpoint(subject_optional=True)
def detail(request,pk):
    from portal.account_access import account_context
    account_context(request)
    return result(request,case_data(request.user,get_object_or_404(MedicalProxy,pk=pk),account=True))


@endpoint(('POST',),subject_optional=True)
def preview(request,pk):
    require_active(request.user,('PATIENT',))
    case=get_object_or_404(MedicalProxy,pk=pk)
    d=validated(ProxyActionForm(request.POST,role='PATIENT',state=case.state))
    return result(request,svc.prepare_action(actor=request.user,case_id=pk,**d))


@endpoint(('POST',),subject_optional=True)
def confirm(request,pk):
    require_active(request.user,('PATIENT',))
    d=validated(ConfirmPlanActionForm(request.POST));p=read_proposal(request.user,svc.CONTRACT,('PATIENT',),d['proposal_token'])['data']
    if p['case']!=pk:raise PermissionDenied('请在原医疗授权事项确认。')
    row,replayed=svc.confirm(actor=request.user,**d)
    return result(request,dict(id=row.pk,state=row.state,replayed=replayed))
