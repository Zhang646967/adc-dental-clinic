"""Explicit observation reset; no database access or business restoration."""
import json
import os
from django.core.management.base import BaseCommand, CommandError
from adc_core.operations import clock, fresh_state, identity
from adc_core.operations_store import PrivateStore


class Command(BaseCommand):
    help = 'While collector is stopped, archive old observations and begin UNKNOWN.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm-reset-observations', action='store_true', required=True)

    def handle(self, *args, **options):
        try:
            target = identity()
            store = PrivateStore(os.environ.get('ADC_MONITOR_DIRECTORY', '/app/operations/monitor'))
            with store.lock('collector.lock'), store.lock('state.lock'):
                store.archive_monitor()
                store.write('monitor.json', fresh_state(target, clock()))
        except (OSError, ValueError, TypeError, KeyError):
            raise CommandError('Observation reset refused; preserve evidence and stop the collector first.') from None
        self.stdout.write(json.dumps({'v':1,'event':'operations.observations_reset','state':'UNKNOWN',
                                      'business_records_changed':False,'prior_archives_limit':3}))
