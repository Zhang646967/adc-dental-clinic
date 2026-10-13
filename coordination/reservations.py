"""Advisory resource locks shared by ordinary bookings and temporary offers.
All HTTP/management writes must use the public booking/coordination services.
The owner of the DB is NOT prevented from bypassing this application protocol.
"""
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from adc_core.rules import OCCUPYING_STATUSES,RuleError

def lock_resources(patients=(),dentists=()):
    if not connection.in_atomic_block:raise RuntimeError('Resource locks need a transaction')
    # Fixed, collision-free namespaces for bigint ids without concatenating user SQL.
    keys=sorted({(7101,int(x)) for x in patients}|{(7102,int(x)) for x in dentists})
    with connection.cursor() as cur:
        for ns,key in keys:
            if not 0<key<2**31:raise RuleError('资源编号超出演示支持范围。')
            cur.execute('SELECT pg_advisory_xact_lock(%s,%s)',[ns,key])

def assert_free(patient_id,dentist_id,start,end,ignore_offer=None):
    from scheduling.models import Visit
    from coordination.models import WaitOffer
    if Visit.objects.filter(status__in=OCCUPYING_STATUSES,scheduled_start__lt=end,scheduled_end__gt=start).filter(
        Q(patient_id=patient_id)|Q(dentist_id=dentist_id)).exists():
        raise RuleError('患者或医生在该时间已经有预约。请重新选择。')
    holds=WaitOffer.objects.filter(state='PENDING',expires_at__gt=timezone.now(),starts_at__lt=end,ends_at__gt=start).filter(
        Q(request__patient_id=patient_id)|Q(slot__dentist_id=dentist_id))
    if ignore_offer is not None:holds=holds.exclude(pk=ignore_offer)
    if holds.exists():raise RuleError('该时间正在为候补邀约暂时保留；请换一个时间或等待邀约到期。')
