from datetime import timezone as dt_timezone
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from assistants.models import UsageBucket

class RateLimited(Exception): pass

@transaction.atomic
def consume(user_id):
    now=timezone.now().astimezone(dt_timezone.utc)
    limits={f"global:day:{now:%Y%m%d}":settings.AI_GLOBAL_DAILY_LIMIT,
        f"user:{user_id}:day:{now:%Y%m%d}":settings.AI_USER_DAILY_LIMIT,
        f"user:{user_id}:minute:{now:%Y%m%d%H%M}":settings.AI_USER_MINUTE_LIMIT}
    locked=[]
    for key,limit in sorted(limits.items()):
        UsageBucket.objects.get_or_create(key=key)
        row=UsageBucket.objects.select_for_update().get(key=key)
        if row.used>=limit: raise RateLimited()
        locked.append(row)
    for row in locked:
        row.used+=1;row.save(update_fields=["used"])
