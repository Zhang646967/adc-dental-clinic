"""Additional real-connection races. Their presence is not evidence of execution."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections,connections
from django.test import TransactionTestCase
from accounts.models import UserAccount
from care.models import Invoice
from portal.models import BookingReceipt
from portal.services import confirm_booking
from care.services import complete_visit
from tests.test_v04 import V04Fixture

class V04ConcurrencyTests(V04Fixture,TransactionTestCase):
    def setUp(self): self.set_up_v04()
    def race(self,call):
        barrier=Barrier(2,timeout=15)
        def run(i):
            close_old_connections()
            try:
                barrier.wait();return call()
            finally: connections["default"].close()
        with ThreadPoolExecutor(max_workers=2) as pool: return list(pool.map(run,range(2)))
    def test_double_patient_confirmation_returns_one_receipt(self):
        token=self.token();uid=self.pa.pk
        def command(): return confirm_booking(actor=UserAccount.objects.get(pk=uid),token=token).pk
        result=self.race(command)
        self.assertEqual(result[0],result[1]);self.assertEqual(BookingReceipt.objects.count(),1)
    def test_double_complete_returns_one_invoice(self):
        v=self.arrived();self.review(v);self.line(v);v.refresh_from_db();uid=self.doctor.pk
        def command(): return complete_visit(actor=UserAccount.objects.get(pk=uid),visit_id=v.pk,expected_version=v.lock_version,outcome="TREATED").pk
        result=self.race(command)
        self.assertEqual(result[0],result[1]);self.assertEqual(Invoice.objects.count(),1)
