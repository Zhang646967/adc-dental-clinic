"""Anonymous service and location reads. No patient/workspace selection or writes."""
from datetime import datetime,time,timedelta
from django.conf import settings
from django.utils import timezone
from registry.directory_models import ClinicDirectory
from registry.branch_projection import public_directory,public_contact,opening_data
from portal.service_catalogue import public_profiles,public_profile
from portal.service_projection import service_data
from scheduling.models import AvailabilitySlot


def discovery_data(*,clinic_id=None,include_shifts=True,dentist_id=None):
    clinic_ids=[clinic_id] if clinic_id else None
    if dentist_id and clinic_ids is None:
        from registry.profile_models import DentistClinicAffiliation
        clinic_ids=list(DentistClinicAffiliation.objects.filter(dentist_id=dentist_id,state='ACTIVE',listing_published=True)
            .values_list('clinic_id',flat=True))
    profiles=public_profiles(clinic_ids=clinic_ids)
    branches=public_directory(clinic_ids=clinic_ids)
    by_id={r['id']:r for r in branches}
    # Legacy published services stay readable until explicitly prepared. Draft
    # branch records suppress their public offerings at the catalogue boundary.
    for profile in profiles:
        clinic=profile.service.department.clinic
        if clinic.pk not in by_id:
            c=public_contact(clinic)
            by_id[clinic.pk]={'id':clinic.pk,**c,'province':'','city':'待核对城市','district':'',
                'entrance':'请联系前台核对入口','latitude':None,'longitude':None,'map_latitude':None,'map_longitude':None,
                'coordinate_system':'WGS-84','map_coordinate_system':'GCJ-02','revision':0,
                'opening':opening_data(clinic.pk)}
    for row in by_id.values():
        row['services']=[service_data(p) for p in profiles if p.service.department.clinic_id==row['id']]
    result={'clinics':sorted(by_id.values(),key=lambda r:(r['city'],r['name'],r['id'])),
        'offerings':[service_data(p) for p in profiles],'environment_label':settings.ADC_PUBLIC_ENVIRONMENT_LABEL,
        'read_only':settings.ADC_READ_ONLY,'business_timezone':'Asia/Shanghai'}
    from registry.profile_projection import enrich_discovery
    return enrich_discovery(result,include_shifts=include_shifts,dentist_id=dentist_id)


def service_discovery(service_id,*,dentist_id=None,actor=None):
    profile=public_profile(service_id)
    data=service_data(profile,actor=actor)
    if dentist_id and dentist_id not in {d['id'] for d in data['dentists']}:
        from django.http import Http404
        raise Http404('该医师当前不接收所选服务。')
    today=timezone.localdate();last=today+timedelta(days=14)
    slots=AvailabilitySlot.objects.filter(clinic_id=data['clinic'],is_active=True,booking_paused=False,
        dentist_id__in=[d['id'] for d in data['dentists']],dentist__is_active=True,
        starts_at__lt=timezone.make_aware(datetime.combine(last+timedelta(days=1),time.min)),
        ends_at__gt=timezone.now()).order_by('starts_at','pk')
    if dentist_id:slots=slots.filter(dentist_id=dentist_id)
    days=set()
    for slot in slots:
        a=max(today,timezone.localtime(slot.starts_at).date());b=min(last,timezone.localtime(slot.ends_at-timedelta(microseconds=1)).date())
        while a<=b:days.add(a.isoformat());a+=timedelta(days=1)
    data['schedule_days']=sorted(days)
    data['default_day']=data['schedule_days'][0] if days else None
    data['schedule_note']='已发布出诊日期参考，余位及就诊人冲突请登录后核对。'
    data['opening']=opening_data(data['clinic'])
    return data
