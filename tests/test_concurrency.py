"""Actual independent database connections; do not replace with an in-memory model."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch
from django.db import connections, close_old_connections, transaction, IntegrityError, OperationalError
from django.test import TransactionTestCase
from tests.fixtures import FixtureMixin
from scheduling.models import Visit

class DatabaseConcurrencyTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.make_fixture()
    def race(self, attempts):
        barrier=Barrier(2,timeout=15)
        def insert(values):
            close_old_connections()
            try:
                barrier.wait()
                try:
                    with transaction.atomic():
                        with connections['default'].cursor() as cur:
                            cur.execute("SET LOCAL lock_timeout = '10s'")
                        Visit.objects.create(**values)
                    return 'committed'
                except IntegrityError as exc:
                    if getattr(getattr(exc.__cause__,'diag',None),'constraint_name',None) in ('visit_dentist_no_overlap','visit_patient_no_overlap'):
                        return 'conflict'
                    raise
                except OperationalError as exc:
                    # Direct inserts can deadlock while arbitrating two GiST
                    # exclusion constraints. PostgreSQL aborts the loser; the
                    # one-commit/one-row assertions below must still hold.
                    if getattr(exc.__cause__, 'sqlstate', None) == '40P01':
                        return 'conflict'
                    raise
            finally:
                connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return sorted(pool.map(insert,attempts))
    def values(self,patient,slot):
        return dict(patient_id=patient.pk,dentist_id=slot.dentist_id,clinic_id=slot.clinic_id,
                    availability_slot_id=slot.pk,scheduled_start=self.t,scheduled_end=self.t+timedelta(hours=1))
    def test_same_dentist_race_only_one_commit(self):
        self.assertEqual(self.race([self.values(self.p1,self.slot1),self.values(self.p2,self.slot1)]),['committed','conflict'])
        self.assertEqual(Visit.objects.count(),1)
    def test_same_patient_across_dentists_only_one_commit(self):
        self.assertEqual(self.race([self.values(self.p1,self.slot1),self.values(self.p1,self.slot2)]),['committed','conflict'])
        self.assertEqual(Visit.objects.count(),1)
    def test_connection_failure_is_not_counted_as_an_overlap_conflict(self):
        from psycopg.errors import ConnectionFailure
        def unavailable(**values):
            error = OperationalError('Synthetic connection failure')
            error.__cause__ = ConnectionFailure('Synthetic connection failure')
            raise error
        with patch.object(Visit.objects, 'create', side_effect=unavailable), self.assertRaises(OperationalError):
            self.race([self.values(self.p1,self.slot1),self.values(self.p1,self.slot2)])
        self.assertEqual(Visit.objects.count(),0)
