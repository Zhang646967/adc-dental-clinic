"""Two independent DB connections; authored, pending actual PostgreSQL gate."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime
from django.db import close_old_connections,connection
from django.test import TransactionTestCase
from accounts.models import UserAccount
from adc_core.rules import RuleError
from scheduling.models import Visit
from coordination.models import WaitOffer
from coordination import services as co
from scheduling.services import create_appointment
from tests.test_v07 import V07Fixture

class V07ConcurrencyTests(V07Fixture,TransactionTestCase):
 def setUp(self):self.setup07()
 def race(self,functions):
  barrier=Barrier(2)
  def worker(fn):
   close_old_connections()
   try:
    with connection.cursor() as cursor:cursor.execute("SET lock_timeout='8s'")
    barrier.wait(timeout=8)
    try:return ('ok',fn())
    except RuleError:return ('conflict',None)
   finally:connection.close()
  with ThreadPoolExecutor(max_workers=2) as pool:
   futures=[pool.submit(worker,fn) for fn in functions]
   return [f.result(timeout=25) for f in futures]
 def test_two_confirmers_produce_one_booking(self):
  e,p,o=self.offered()
  def confirm(uid):return co.answer_offer(actor=UserAccount.objects.get(pk=uid),offer_id=o.pk,accept=True).visit_id
  rows=self.race([lambda:confirm(self.pa.pk),lambda:confirm(self.front.pk)])
  self.assertEqual([r[0] for r in rows],['ok','ok']);self.assertEqual(rows[0][1],rows[1][1]);self.assertEqual(Visit.objects.count(),1)
 def test_regular_booking_and_offer_cannot_both_take_time(self):
  self.join();plan=co.create_plan(actor=self.front,clinic_id=self.a.pk);r=plan.suggestions[0]
  def publish():return co.publish_plan(actor=UserAccount.objects.get(pk=self.front2.pk),plan_id=plan.pk).pk
  def booking():return create_appointment(actor=UserAccount.objects.get(pk=self.front.pk),patient_no=self.p2.patient_no,slot_id=r['slot_id'],start=datetime.fromisoformat(r['start']),end=datetime.fromisoformat(r['end'])).pk
  rows=self.race([publish,booking]);self.assertEqual(sum(x[0]=='ok' for x in rows),1)
  self.assertEqual(Visit.objects.count()+WaitOffer.objects.filter(state='PENDING').count(),1)
