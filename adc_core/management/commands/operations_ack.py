import json
import os
from django.core.management.base import BaseCommand, CommandError
from adc_core.operations import acknowledge, clock, identity
from adc_core.operations_store import PrivateStore


class Command(BaseCommand):
    help = 'Acknowledge a private incident; never clear its condition or retry business work.'

    def add_arguments(self, parser):
        parser.add_argument('incident')
        parser.add_argument('--operator-code', required=True)

    def handle(self, *args, **options):
        try:
            target = identity()
            store = PrivateStore(os.environ.get('ADC_MONITOR_DIRECTORY', '/app/operations/monitor'))
            with store.lock('state.lock'):
                state = acknowledge(store.read('monitor.json'), target, options['incident'],
                                    options['operator_code'], clock())
                store.write('monitor.json', state)
        except (OSError, ValueError, TypeError, KeyError):
            raise CommandError('Private acknowledgement refused; inspect current status.') from None
        self.stdout.write(json.dumps({'v':1,'event':'operations.acknowledged','condition_not_cleared':True}))
