"""Collector recovery after a measured clock gap; no business database writes."""
from copy import deepcopy
import io
import os
from pathlib import Path
import tempfile
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from adc_core.operations import advance, fresh_state, status
from adc_core.operations_store import PrivateStore
from checks.test_operations import TARGET, moment, sample


class ObserverClockResumeTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'monitor'
        self.store = PrivateStore(self.directory)
        self.original = fresh_state(TARGET, moment())
        advance(self.original, sample(), TARGET, moment())
        advance(self.original, sample(30), TARGET, moment(30))
        self.store.write('monitor.json', self.original)
        self.env = patch.dict(os.environ, ADC_MONITOR_DIRECTORY=str(self.directory))
        self.env.start()
        self.addCleanup(self.env.stop)

    def observe(self, t, shift=600, target=TARGET):
        current = moment(t)
        current['mono'] -= shift
        observation = sample(t)
        observation['at'] = deepcopy(current)
        for key in ['at', 'last_success']:
            observation['worker'][key] = deepcopy(current)
        output = io.StringIO()
        with patch('adc_core.management.commands.observe_operations.identity', return_value=target), patch(
                'adc_core.management.commands.observe_operations.clock', return_value=current), patch(
                'adc_core.management.commands.observe_operations.collect_sample', return_value=observation):
            call_command('observe_operations', stdout=output)
        return current, output.getvalue()

    def test_clock_gap_archives_original_and_requires_two_fresh_samples(self):
        now, text = self.observe(1000)
        self.assertIn('operations.clock_discontinuity', text)
        self.assertEqual(self.store.read('previous-1.json'), self.original)
        first = self.store.read('monitor.json')
        self.assertEqual(status(first, TARGET, now)['state'], 'UNKNOWN')
        self.assertEqual(first['sequence'], 1)
        self.assertNotEqual(first['run'], self.original['run'])
        now, text = self.observe(1030)
        self.assertNotIn('clock_discontinuity', text)
        self.assertEqual(status(self.store.read('monitor.json'), TARGET, now)['state'], 'HEALTHY')
        self.assertEqual(self.store.read('previous-1.json'), self.original)

    def test_foreign_identity_is_preserved_and_never_auto_reset(self):
        before = (self.directory / 'monitor.json').read_bytes()
        with self.assertRaises(CommandError):
            self.observe(1000, target=TARGET | {'source': 'c' * 40})
        self.assertEqual((self.directory / 'monitor.json').read_bytes(), before)
        self.assertFalse((self.directory / 'previous-1.json').exists())
