from portal.mini_api import endpoint,result
from portal.discovery import discovery_data,service_discovery
from scheduling.service_content import CATEGORY_CHOICES


@endpoint(public=True)
def listing(request):
    return result(request,discovery_data())


@endpoint(public=True)
def service(request,pk):
    return result(request,service_discovery(pk))


@endpoint(public=True)
def clinic(request,pk):
    from django.http import Http404
    row=next((x for x in discovery_data()['clinics'] if x['id']==pk),None)
    if not row:raise Http404
    return result(request,row)


@endpoint(public=True)
def dentists(request):
    from portal.service_views import doctor_filter
    from django.core.paginator import Paginator
    data=discovery_data();page=Paginator(doctor_filter(data,request.GET),12).get_page(request.GET.get('page'))
    return result(request,dict(rows=list(page),page=page.number,pages=page.paginator.num_pages,
        cities=sorted({c['city'] for c in data['clinics']}),
        categories=[dict(id=code,name=name) for code,name in CATEGORY_CHOICES]))


@endpoint(public=True)
def dentist(request,pk):
    from django.http import Http404
    data=discovery_data();doctor=next((x for x in data['dentists'] if x['id']==pk),None)
    if not doctor:raise Http404
    clinic_id=request.GET.get('clinic','')
    if clinic_id:
        local=next((d for c in data['clinics'] if str(c['id'])==str(clinic_id) for d in c['team'] if d['id']==pk),None)
        if not local:raise Http404
        doctor={**local,'clinics':doctor['clinics']}
    return result(request,doctor)
