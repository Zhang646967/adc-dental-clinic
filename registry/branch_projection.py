"""Public branch projection. Hours come from the actual resource calendar."""
from datetime import datetime,time,timedelta
from django.conf import settings
from django.utils import timezone
from registry.directory_models import ClinicDirectory
from scheduling.resource_models import DepartmentHours,ResourceBlock

DAYS=('周一','周二','周三','周四','周五','周六','周日')


def public_contact(clinic):
    try:row=clinic.public_directory
    except ClinicDirectory.DoesNotExist:row=None
    if row and row.is_published:
        return {'name':row.display_name,'address':row.address,'phone':row.public_phone,
            'synthetic':row.synthetic or settings.ADC_CLINICAL_SYNTHETIC}
    return {'name':clinic.name,'address':clinic.postal_address,'phone':clinic.phone,'synthetic':True}


def merge(intervals):
    result=[]
    for start,end in sorted(intervals):
        if result and start<=result[-1][1]:result[-1]=(result[-1][0],max(end,result[-1][1]))
        else:result.append((start,end))
    return result


def subtract(intervals,start,end):
    result=[]
    for a,b in intervals:
        if end<=a or start>=b:result.append((a,b));continue
        if a<start:result.append((a,min(start,b)))
        if end<b:result.append((max(end,a),b))
    return result


def label(intervals):
    return '、'.join(f'{a:%H:%M}—{b:%H:%M}' for a,b in intervals) or '休息'


def opening_data(clinic_id,*,now=None):
    now=timezone.localtime(now or timezone.now())
    hours=list(DepartmentHours.objects.filter(department__clinic_id=clinic_id,department__is_active=True))
    week=[{'day':DAYS[i],'hours':label(merge([(h.opens_at,h.closes_at) for h in hours if h.weekday==i]))} for i in range(7)]
    a=timezone.make_aware(datetime.combine(now.date(),time.min));b=a+timedelta(days=1)
    blocks=list(ResourceBlock.objects.filter(clinic_id=clinic_id,is_active=True,department_id__isnull=False,
        starts_at__lt=b,ends_at__gt=a))
    today=[]
    for h in hours:
        if h.weekday!=now.weekday():continue
        spans=[(h.opens_at,h.closes_at)]
        for block in blocks:
            if block.department_id!=h.department_id:continue
            x=max(timezone.localtime(block.starts_at),a);y=min(timezone.localtime(block.ends_at),b)
            spans=subtract(spans,x.time(),time.max if y==b else y.time())
        today.extend(spans)
    today=merge(today)
    state='UNKNOWN' if not hours else 'OPEN' if any(x<=now.time()<y for x,y in today) else 'CLOSED'
    return {'state':state,'state_label':{'OPEN':'营业中','CLOSED':'当前休息','UNKNOWN':'营业时间待核对'}[state],
        'today':label(today) if hours else '请联系前台核对','week':week,
        'notices':[{'start':x.starts_at.isoformat(),'end':x.ends_at.isoformat(),'text':x.public_notice}
            for x in ResourceBlock.objects.filter(clinic_id=clinic_id,is_active=True,public_notice__gt='',
                ends_at__gt=now,starts_at__lt=now+timedelta(days=14)).order_by('starts_at','pk')[:20]]}


def directory_data(row):
    return {'id':row.clinic_id,'name':row.display_name,'province':row.province,'city':row.city,'district':row.district,
        'address':row.address,'entrance':row.entrance,'phone':row.public_phone,'revision':row.revision,
        'latitude':float(row.latitude) if row.latitude is not None else None,
        'longitude':float(row.longitude) if row.longitude is not None else None,'coordinate_system':'WGS-84',
        'map_latitude':float(row.map_latitude) if row.map_latitude is not None else None,
        'map_longitude':float(row.map_longitude) if row.map_longitude is not None else None,'map_coordinate_system':'GCJ-02',
        'synthetic':row.synthetic or settings.ADC_CLINICAL_SYNTHETIC,'opening':opening_data(row.clinic_id)}


def public_directory(*,city=None):
    rows=ClinicDirectory.objects.filter(is_published=True,clinic__is_active=True).select_related('clinic')
    if city:rows=rows.filter(city=city)
    return [directory_data(row) for row in rows]
