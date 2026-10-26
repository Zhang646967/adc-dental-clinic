"""Allowlisted public profile projection, shared by web and the native client."""
from collections import defaultdict
from datetime import timedelta
from django.db.models import Q
from django.utils import timezone
from registry.profile_models import PublicProfile,DentistClinicAffiliation,ProfileMedia
from scheduling.models import AvailabilitySlot
from scheduling.service_content import CATEGORY_CHOICES

DOCTOR_FIELDS=('title','summary','biography','practicing_since','languages','education','specialties')
CLINIC_FIELDS=('summary','biography','transport','parking','accessibility','accessibility_note','fee_note')


def enrich_discovery(data):
    ids=[r['id'] for r in data['clinics']];today=timezone.localdate();now=timezone.now();last=now+timedelta(days=15)
    profiles={p.clinic_id:p for p in PublicProfile.objects.filter(clinic_id__in=ids,published_version__isnull=False)
        .select_related('published_version')}
    affiliations=list(DentistClinicAffiliation.objects.filter(clinic_id__in=ids,state='ACTIVE',listing_published=True,
        published_version__isnull=False,dentist__is_active=True,starts_on__lte=today)
        .filter(Q(ends_on__isnull=True)|Q(ends_on__gte=today))
        .select_related('dentist','published_version','clinic__public_directory').order_by('dentist__employee_no','clinic_id'))
    contents=[p.published_version.content for p in profiles.values()]+[a.published_version.content for a in affiliations]
    media_ids={i for c in contents for i in c.get('media_ids',[])}
    media={m.pk:dict(id=m.pk,url='/profiles/media/'+str(m.pk)+'/',alt=m.alt_text,width=m.width,height=m.height)
        for m in ProfileMedia.objects.filter(pk__in=media_ids).defer('image')}
    shifts=defaultdict(list)
    for slot in AvailabilitySlot.objects.filter(clinic_id__in=ids,is_active=True,booking_paused=False,
        ends_at__gt=now,starts_at__lt=last).order_by('starts_at','pk'):
        shifts[slot.clinic_id,slot.dentist_id].append(dict(start=slot.starts_at.isoformat(),end=slot.ends_at.isoformat(),
            day=timezone.localtime(slot.starts_at).date().isoformat()))
    services=defaultdict(list)
    for offering in data['offerings']:
        choice={k:offering[k] for k in ('id','name','clinic','category','duration','fee_label','self_booking')}
        for dentist in offering['dentists']:services[offering['clinic'],dentist['id']].append(choice)
    teams=defaultdict(list);doctors={}
    for a in affiliations:
        c=a.published_version.content
        public={key:c.get(key) for key in DOCTOR_FIELDS}
        public.update(id=a.dentist_id,name=a.dentist.name,version=a.published_version_id,
            credential_status='申报资料；机构已审核介绍，职称未作独立认证',
            specialty_labels=[dict(CATEGORY_CHOICES).get(k,k) for k in c.get('specialties',[])],
            images=[media[i] for i in c.get('media_ids',[]) if i in media],clinics=[])
        since=c.get('practicing_since')
        if since:
            from datetime import date
            d=date.fromisoformat(since);public['experience_years']=max(0,today.year-d.year-((today.month,today.day)<(d.month,d.day)))
        else:public['experience_years']=None
        current=doctors.setdefault(a.dentist_id,public)
        branch=next(r for r in data['clinics'] if r['id']==a.clinic_id)
        branch_data=dict(id=a.clinic_id,name=branch['name'],city=branch['city'],district=branch['district'],
            kind=a.get_kind_display(),version=a.published_version_id,services=services[a.clinic_id,a.dentist_id],
            shifts=shifts[a.clinic_id,a.dentist_id],ends_on=a.ends_on.isoformat() if a.ends_on else None)
        current['clinics'].append(branch_data)
        # Each clinic displays the specific version it reviewed, not another clinic's version.
        teams[a.clinic_id].append({**public,'clinics':[branch_data]})
    from equipment.models import EquipmentAsset
    equipment=defaultdict(lambda:defaultdict(int))
    for category,clinic in EquipmentAsset.objects.filter(clinic_id__in=ids,state='IN_SERVICE').values_list('category','clinic_id'):
        equipment[clinic][category]+=1
    from insurance.models import ClinicArrangement
    insurance={x['clinic_id'] for x in ClinicArrangement.objects.filter(clinic_id__in=ids,state='CONFIRMED',
        starts_on__lte=today,ends_on__gte=today).values('clinic_id')}
    for row in data['clinics']:
        profile=profiles.get(row['id']);content=profile.published_version.content if profile else {}
        row.update({key:content.get(key,'') for key in CLINIC_FIELDS})
        row.update(images=[media[i] for i in content.get('media_ids',[]) if i in media],
            team=teams[row['id']],profile_version=profile.published_version_id if profile else None,
            equipment=dict(equipment[row['id']]),online_booking=bool(row['services']),
            insurance_status=('本地模拟结算已配置' if row['synthetic'] else '本店医保安排已配置，请核对具体项目')
                if row['id'] in insurance else '医保安排待核对',
            schedule_note='出诊日期供参考，登录后按服务、就诊人及资源核对余位。')
    data['dentists']=list(doctors.values())
    data['filter_index']={'clinics':[{k:r[k] for k in ('id','name','city','district','latitude','longitude','online_booking')}|
        {'services':[{'category':s['category']} for s in r['services']]} for r in data['clinics']],
        'offerings':[{'category':s['category'],'category_label':s['category_label']} for s in data['offerings']]}
    return data
