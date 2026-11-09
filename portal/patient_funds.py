"""Web and mini-program reads share the existing self-only patient boundary."""
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from adc_core.snapshots import reporting_snapshot
from finance.patient_funds import statement
from portal.mini_api import endpoint, result
from portal.policies import patient_access


def _data(request):
    with reporting_snapshot():
        access = patient_access(request.user, self_only=True)
        return statement(access.patient_id, clinic=request.GET.get('clinic', ''), page=request.GET.get('page', '1'))


@login_required(login_url='portal_login')
@require_GET
@never_cache
def web(request):
    return render(request, 'portal/funds.html', _data(request))


@endpoint()
def mini(request):
    return result(request, _data(request))
