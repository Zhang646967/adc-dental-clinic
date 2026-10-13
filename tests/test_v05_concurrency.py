"""Real PostgreSQL concurrency, pending execution in local Docker."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from django.db import close_old_connections,connections
from django.test import TransactionTestCase
from accounts.models import UserAccount
from adc_core.rules import RuleError
from finance.services import save_cost
from care.corrections import review_correction
from care.models import Invoice,VisitRecordVersion
from tests.test_v05 import V05Fixture

class V05ConcurrencyTests(V05Fixture,TransactionTestCase):
    def setUp(self):self.setup05()
    def race(self,call):
        b=Barrier(2,timeout=15)
        def run(i):
            close_old_connections()
            try:b.wait();return call(i)
            finally:connections['default'].close()
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(run,range(2)))
    def test_competing_cost_updates_only_one_revision(self):
        q=self.make_quarter();c=self.member(q);q.refresh_from_db();revision=q.lock_version;uid=self.fin.pk
        def command(i):
            try:
                save_cost(actor=UserAccount.objects.get(pk=uid),quarter_id=q.pk,cost_id=c.pk,expected_version=revision,supply_cost=Decimal(10+i),operating_expense=Decimal('20'),notes='并发合成测试');return 'ok'
            except RuleError:return 'stale'
        self.assertEqual(sorted(self.race(command)),['ok','stale'])
    def test_duplicate_approval_only_one_publication(self):
        v,i,r=self.correction();uid=self.fin.pk
        def command(n):return review_correction(actor=UserAccount.objects.get(pk=uid),request_id=r.pk,decision='approve',reason='并发合成审核').pk
        result=self.race(command);self.assertEqual(result[0],result[1]);self.assertEqual(Invoice.objects.count(),1);self.assertEqual(VisitRecordVersion.objects.filter(state='PUBLISHED').count(),2)
