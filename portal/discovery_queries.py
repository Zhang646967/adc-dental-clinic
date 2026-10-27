"""Shared public selection and compact mobile reads. No booking effects."""
from collections import Counter
from datetime import timedelta
from django.core.paginator import Paginator
from django.db.models import Min
from django.http import Http404
from django.utils import timezone
from scheduling.models import AvailabilitySlot
from scheduling.service_content import CATEGORY_CHOICES, positive_id
from portal.discovery import discovery_data
from portal.service_catalogue import public_profiles
from portal.service_projection import service_data


def clinic_index():
    # Keep the legacy full endpoint for installed older clients. The current
    # client downloads the complete *small* index before sorting locally by GPS.
    data=discovery_data(include_shifts=False)
    now=timezone.now()
    upcoming={r['clinic_id']:timezone.localtime(r['next']).date().isoformat()
        for r in AvailabilitySlot.objects.filter(clinic_id__in=[c['id'] for c in data['clinics']],
            is_active=True,booking_paused=False,dentist__is_active=True,ends_at__gt=now,
            starts_at__lt=now+timedelta(days=15)).values('clinic_id').annotate(next=Min('starts_at'))}
    rows=[]
    for c in data['clinics']:
        row={k:c[k] for k in ('id','name','city','district','address','phone','latitude','longitude',
            'synthetic','summary','profile_version','online_booking')}
        row['opening']={k:c['opening'][k] for k in ('state','state_label','today')}
        row['images']=c['images'][:1]
        row['services']=[{k:s[k] for k in ('id','name','category','duration')} for s in c['services']]
        row['service_categories']=sorted({s['category'] for s in c['services']})
        row['team_count']=len(c['team'])
        row['team']=[{k:d[k] for k in ('id','name','title')} for d in c['team'][:3]]
        row['next_shift_day']=upcoming.get(c['id'])
        row['booking_state']='NO_SCHEDULE' if row['services'] and not row['next_shift_day'] else 'OFFERED' if row['services'] else 'NOT_OFFERED'
        rows.append(row)
    categories=[dict(id=key,name=name) for key,name in CATEGORY_CHOICES]
    return dict(clinics=rows,categories=categories,business_timezone='Asia/Shanghai',
        environment_label=data['environment_label'],read_only=data['read_only'],
        filter_index={'clinics':[{k:c[k] for k in ('id','name','city','district','latitude','longitude','online_booking','services')} for c in rows],
            'offerings':[dict(category=c['id'],category_label=c['name']) for c in categories]})


def catalogue_selection(params):
    """One filter contract for website and mini-program, including alternatives."""
    category=str(params.get('category',''));raw_clinic=str(params.get('clinic',''))
    clinic=positive_id(raw_clinic) if raw_clinic else None
    if (category and category not in dict(CATEGORY_CHOICES)) or (raw_clinic and not clinic):raise Http404
    index=clinic_index();branches=index['clinics'];by_id={c['id']:c for c in branches}
    if clinic and clinic not in by_id:raise Http404
    city=str(params.get('city',''))[:40];q=str(params.get('q','')).strip()[:80]
    profiles=public_profiles()
    local=[p for p in profiles if (not clinic or p.service.department.clinic_id==clinic)
        and (not city or by_id.get(p.service.department.clinic_id,{}).get('city')==city)]
    selected=[p for p in local if (not category or p.category==category)
        and (not q or q.casefold() in (p.title+' '+p.summary+' '+p.suitable_for).casefold())]
    page=Paginator(selected,12).get_page(params.get('page'))
    target_city=city or (by_id[clinic]['city'] if clinic else '')
    alternatives=[c for c in branches if c['id']!=clinic and (not target_city or c['city']==target_city)
        and (not category or category in c['service_categories']) and c['services']]
    status='READY' if selected else 'NOT_OFFERED' if clinic and category and category not in by_id[clinic]['service_categories'] else 'NO_MATCH'
    message=('本店尚未开放此项服务，可选择下方实际提供该服务的门店。' if status=='NOT_OFFERED' else
        '没有找到符合条件的服务，请调整筛选或查看下方门店。') if not selected else ''
    if not selected and target_city and not alternatives:message+=' 当前城市暂无符合条件的其他门店，可更换城市或联系前台。'
    counts=Counter(p.category for p in local)
    return dict(profiles=list(page),page=page,index=index,selected_category=category,selected_clinic=clinic,
        categories=[dict(id=k,name=n,count=counts[k]) for k,n in CATEGORY_CHOICES],
        clinic_choices=[dict(id=c['id'],name=c['name'],count=sum(1 for p in profiles
            if p.service.department.clinic_id==c['id'] and (not category or p.category==category)))
            for c in branches if not city or c['city']==city or c['id']==clinic],
        alternatives=alternatives,message=message,status=status,count=len(selected),city=city,q=q)


def service_listing(params):
    selection=catalogue_selection(params)
    fields=('id','name','clinic','clinic_name','category','category_label','summary','duration','fee_label','self_booking')
    offerings=[{k:v for k,v in service_data(p).items() if k in fields} for p in selection['profiles']]
    return dict(offerings=offerings,clinics=[{k:c[k] for k in ('id','name','city','district')} for c in selection['index']['clinics']],
        categories=selection['categories'],clinic_choices=selection['clinic_choices'],
        alternatives=[{k:c[k] for k in ('id','name','city','district','latitude','longitude','next_shift_day')}
            for c in selection['alternatives']] if not offerings else [],status=selection['status'],message=selection['message'],
        page=selection['page'].number,pages=selection['page'].paginator.num_pages,count=selection['count'],
        selected_category=selection['selected_category'],selected_clinic=selection['selected_clinic'])


def doctor_listing_data():
    """Lists need a next day, not every published interval for sixty doctors."""
    data=discovery_data(include_shifts=False);now=timezone.now()
    next_days={(r['clinic_id'],r['dentist_id']):timezone.localtime(r['next']).date().isoformat()
        for r in AvailabilitySlot.objects.filter(clinic_id__in=[c['id'] for c in data['clinics']],is_active=True,
            booking_paused=False,ends_at__gt=now,starts_at__lt=now+timedelta(days=15))
            .values('clinic_id','dentist_id').annotate(next=Min('starts_at'))}
    for doctor in data['dentists']:
        for branch in doctor['clinics']:
            day=next_days.get((branch['id'],doctor['id']))
            branch['shifts']=[{'day':day}] if day else []
    return data
