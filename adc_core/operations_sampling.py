"""Read-only bounded observations. This module cannot dispatch or retry a notice."""
import json
import os
import shutil
from urllib.error import URLError
from urllib.request import Request, urlopen
from django.db import connection, transaction, DatabaseError
from django.db.models import Count, Min
from django.db.models.functions import Greatest
from django.utils import timezone
from adc_core.operations import clock, worker_condition
from adc_core.operations_store import PrivateStore
from notifications.models import NotificationOutbox


def database_sample():
    if connection.vendor != 'postgresql' or connection.in_atomic_block:
        raise ValueError('Use an independent PostgreSQL read-only observation.')
    # These statements apply to this transaction only, never the business session.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cursor.execute("SET LOCAL statement_timeout = '3000ms'")
            cursor.execute("SET LOCAL lock_timeout = '300ms'")
            cursor.execute('SELECT CURRENT_TIMESTAMP')
            now = cursor.fetchone()[0]
        if abs((timezone.now() - now).total_seconds()) > 300:
            raise ValueError('Database clock differs.')
        counts = dict(NotificationOutbox.objects.values('state').annotate(n=Count('pk')).values_list('state','n'))
        due = NotificationOutbox.objects.filter(state='PENDING', next_attempt_at__lte=now).aggregate(
            n=Count('pk'), oldest=Min(Greatest('occurred_at', 'next_attempt_at')))
    return {'due': due['n'], 'oldest_due_seconds': max(0, (now-due['oldest']).total_seconds()) if due['oldest'] else 0,
            'pending': counts.get('PENDING',0), 'failed': counts.get('FAILED',0),
            'delivered': counts.get('DELIVERED',0), 'no_recipients': counts.get('NO_RECIPIENTS',0)}


def web_sample():
    # A fixed private endpoint, never an operator-supplied URL or remote payload.
    headers = {'Host': os.environ.get('ADC_PUBLIC_HOST') or 'localhost',
               'X-Forwarded-Proto': 'https'}
    try:
        request = Request('http://web:8000/health/', headers=headers)
        with urlopen(request, timeout=3) as response:
            raw = response.read(1025)
            return (response.status == 200 and len(raw) <= 1024 and
                    json.loads(raw).get('status') == 'ok')
    except (OSError, URLError, ValueError, AttributeError):
        return False


def collect_sample(target, worker_directory, monitor_directory):
    try:
        database = database_sample()
    except (DatabaseError, ValueError):
        connection.close()
        database = None
    try:
        worker = PrivateStore(worker_directory).read('heartbeat.json')
    except (OSError, ValueError, TypeError):
        worker = None
    if worker_condition(worker, target, clock())[1] == 'WORKER_OBSERVATION_INVALID':
        worker = None
    usage = shutil.disk_usage(monitor_directory)
    web = web_sample()
    return {'v': 1, 'kind': 'sample', 'identity': target, 'at': clock(),
            'database': database, 'worker': worker, 'web': web,
            'storage': {'total': usage.total, 'free': usage.free}}
