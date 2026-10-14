"""Load acceptance math/target guards; no network or authentication is executed."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.g4_load import ACTORS, Client, assess, percentile, private_path, read_sessions
from scripts.g4_observe import memory_bytes, summarize


class CourseLoadTests(unittest.TestCase):
    def test_percentiles_use_nearest_rank_and_keep_tail_observations(self):
        self.assertEqual(percentile(list(range(100, 0, -1)), 95), 95)
        self.assertEqual(percentile([1, 2, 5000], 95), 5000)
        self.assertIsNone(percentile([], 95))

    def test_normal_capacity_cannot_pass_with_any_failed_or_dropped_request(self):
        self.assertTrue(assess(1000, 1000, 0, 0, 100, 2000, False))
        self.assertFalse(assess(1000, 999, 0, 1, 100, 2000, False))
        self.assertFalse(assess(1000, 999, 1, 0, 100, 2000, False))
        self.assertFalse(assess(1000, 1000, 0, 0, 2001, 2000, False))
        self.assertFalse(assess(0, 0, 0, 0, None, 2000, False))

    def test_overload_accepts_only_explicit_throttling_with_some_success(self):
        self.assertTrue(assess(100, 60, 0, 40, 100, 2000, True))
        self.assertFalse(assess(100, 59, 0, 40, 100, 2000, True))
        self.assertFalse(assess(100, 0, 0, 100, None, 2000, True))
        self.assertFalse(assess(100, 100, 0, 0, 100, 2000, True))

    def test_output_traversal_or_symlink_escape_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / '.g4'
            (bundle / 'private').mkdir(parents=True)
            for name in ('../credentials.json', '/tmp/result.json', 'result.txt'):
                with self.assertRaises(ValueError):
                    private_path(bundle, name)
            outside = Path(folder) / 'outside.json'
            outside.write_text('private fixture')
            (bundle / 'private/result.json').symlink_to(outside)
            with self.assertRaises(ValueError):
                private_path(bundle, 'result.json')

    def test_wrong_instance_unreviewed_route_and_public_sessions_are_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sessions.json'
            plan = {'host': 'demo.trycloudflare.com', 'project': 'adc_g4_123456abcdef'}
            doc = plan | {'sessions': [{'label': label, 'routes': list(routes),
                                      'cookies': {'sessionid': 'private-fixture'}}
                                     for _, label, _, routes in ACTORS]}
            def write(values, mode=0o600):
                path.write_text(json.dumps(values))
                path.chmod(mode)
            write(doc)
            self.assertEqual(len(read_sessions(path, plan)), 9)
            for change in ('host', 'project', 'route'):
                bad = copy.deepcopy(doc)
                if change == 'route':
                    bad['sessions'][0]['routes'].append('/patients/new/')
                else:
                    bad[change] = 'another-instance'
                write(bad)
                with self.assertRaises(ValueError):
                    read_sessions(path, plan)
            write(doc, 0o644)
            with self.assertRaises(ValueError):
                read_sessions(path, plan)

    def test_business_post_or_arbitrary_url_is_refused_before_connection(self):
        client = Client({'host': 'demo.trycloudflare.com', 'ports': [18020]}, 'origin')
        for method, route in (('POST', '/patients/new/'), ('GET', 'https://other.example/'),
                              ('GET', '/portal/book/confirm/'), ('DELETE', '/patients/')):
            with self.assertRaises(ValueError):
                client.request(method, route)
        self.assertIsNone(client.connection)

    def test_docker_memory_units_are_not_confused(self):
        self.assertEqual(memory_bytes('1.5MiB'), 1572864)
        self.assertEqual(memory_bytes('1.5MB'), 1500000)
        self.assertEqual(memory_bytes('512B'), 512)
        with self.assertRaises(ValueError):
            memory_bytes('--')

    def healthy_samples(self):
        return [{'origin_health': 'PASS', 'services': {
                    name: {'running': True, 'health': 'healthy', 'oom_killed': False,
                           'restart_count': 0, 'started_at': 'unchanged',
                           'memory_bytes': 100 * 1024**2, 'cpu_percent': 10}
                    for name in ('web', 'db', 'gateway')},
                 'database': {'app_connections': 3, 'max_connections': 100,
                              'idle_in_transaction': 0, 'waiting_locks': 0, 'worker_pids': [10, 11]}}
                for _ in range(4)]

    def test_stability_does_not_hide_oom_restart_db_wait_or_sampling_failure(self):
        self.assertTrue(summarize(self.healthy_samples())['passed'])
        self.assertFalse(summarize([{'sampling_error': 'TimeoutExpired'}])['passed'])
        for kind in ('oom', 'restart', 'unhealthy', 'db_wait', 'idle_transaction'):
            with self.subTest(kind=kind):
                rows = self.healthy_samples()
                if kind == 'oom': rows[-1]['services']['web']['oom_killed'] = True
                if kind == 'restart': rows[-1]['services']['web']['restart_count'] = 1
                if kind == 'unhealthy': rows[-1]['services']['db']['health'] = 'unhealthy'
                if kind == 'db_wait': rows[-1]['database']['waiting_locks'] = 1
                if kind == 'idle_transaction': rows[-1]['database']['idle_in_transaction'] = 1
                self.assertFalse(summarize(rows)['passed'])

    def test_worker_recycling_is_allowed_and_large_memory_growth_fails(self):
        rows = self.healthy_samples()
        rows[-1]['database']['worker_pids'] = [12, 13]
        self.assertTrue(summarize(rows)['worker_recycling_observed'])
        self.assertTrue(summarize(rows)['passed'])
        rows[-1]['services']['web']['memory_bytes'] += 65 * 1024**2
        self.assertFalse(summarize(rows)['passed'])
        self.assertFalse(summarize(rows)['memory_leak_absence_proven'])


if __name__ == '__main__':
    unittest.main()
