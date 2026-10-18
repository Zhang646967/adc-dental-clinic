"""Independent reader: no DB or observer process is required to detect staleness."""
import json
import os
from django.core.management.base import BaseCommand
from adc_core.operations import clock, identity, status
from adc_core.operations_store import PrivateStore


class Command(BaseCommand):
    help = 'Private condition status, exit 0/1/2/3 for healthy/warning/critical/unknown.'

    def handle(self, *args, **options):
        try:
            target = identity()
            store = PrivateStore(os.environ.get('ADC_MONITOR_DIRECTORY', '/app/operations/monitor'))
            result = status(store.read('monitor.json'), target, clock())
        except (OSError, ValueError, TypeError, KeyError):
            result = {'v':1,'state':'UNKNOWN','code':3,'reason':'OBSERVER_UNAVAILABLE'}
        self.stdout.write(json.dumps(result, sort_keys=True))
        if result['code']:
            raise SystemExit(result['code'])
