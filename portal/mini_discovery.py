from portal.mini_api import endpoint,result
from portal.discovery import discovery_data,service_discovery


@endpoint(public=True)
def listing(request):
    return result(request,discovery_data())


@endpoint(public=True)
def service(request,pk):
    return result(request,service_discovery(pk))
