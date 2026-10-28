"""Private collector, no external alerts and no business writes."""
import json
import os
import signal
import threading
import time
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections
from adc_core.operations import advance, clock, clock_discontinuity, fresh_state, identity, status
from adc_core.operations_sampling import collect_sample
from adc_core.operations_store import PrivateStore


class Command(BaseCommand):
    help = 'Collect private worker/backlog conditions; never change business records.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')

    def handle(self, *args, **options):
        target = identity()
        store = PrivateStore(os.environ.get('ADC_MONITOR_DIRECTORY', '/app/operations/monitor'))
        worker_directory = os.environ.get('ADC_WORKER_DIRECTORY', '/app/operations/worker')
        if threading.current_thread() is not threading.main_thread():
            raise CommandError('Observation requires a dedicated main-thread process.')
        stopping = False
        previous = {}

        def stop(signum, frame):
            nonlocal stopping
            stopping = True

        try:
            if options['watch']:
                for signum in (signal.SIGTERM, signal.SIGINT):
                    previous[signum] = signal.getsignal(signum)
                    signal.signal(signum, stop)
            with store.lock('collector.lock'):
                while not stopping:
                    loop_started = time.monotonic()
                    close_old_connections()
                    sample = collect_sample(target, worker_directory, store.directory)
                    now = clock()
                    with store.lock('state.lock'):
                        try:
                            state = store.read('monitor.json')
                        except FileNotFoundError:
                            state = fresh_state(target, now)
                        if clock_discontinuity(state, target, now):
                            # Host suspend/clock jumps must not make the observer
                            # fail forever. Preserve its complete prior state and
                            # incidents, then require two fresh successful samples.
                            store.archive_monitor()
                            state = fresh_state(target, now)
                            self.stdout.write(json.dumps({'v': 1, 'event': 'operations.clock_discontinuity',
                                'state': 'UNKNOWN', 'prior_observation_archived': True}))
                        state = advance(state, sample, target, now)
                        store.write('monitor.json', state)
                    result = status(state, target, now)
                    self.stdout.write(json.dumps({'v':1,'event':'operations.sampled','state':result['state']}))
                    if not options['watch']:
                        return
                    deadline = loop_started + 30
                    while not stopping and time.monotonic() < deadline:
                        time.sleep(min(.2, max(0, deadline-time.monotonic())))
        except (OSError, ValueError, TypeError, KeyError):
            # Keep the old sample (and incidents) intact; status will become UNKNOWN.
            raise CommandError('Operational observer unavailable; no current healthy result.') from None
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
            close_old_connections()
