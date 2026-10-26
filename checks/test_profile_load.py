import unittest
from collections import Counter
from scripts.profile_load import summary,write_request
from finance.management_policy import allocate_cost,month_bounds
from decimal import Decimal


class ProfileLoadPolicyTests(unittest.TestCase):
    def test_percentile_uses_percent_not_fraction(self):
        value=summary([{'seconds':i,'ok':True} for i in range(1,101)])
        self.assertGreaterEqual(value['p95_seconds'],95)
        self.assertLess(value['p95_seconds'],97)
        self.assertEqual(value['max_seconds'],100)

    def test_twenty_accounts_all_write_with_exact_eighty_twenty(self):
        counts=Counter(i%20 for i in range(9000) if write_request(i))
        self.assertEqual(len(counts),20);self.assertEqual(set(counts.values()),{90})
        self.assertEqual(sum(counts.values()),1800)

    def test_failed_requests_are_not_filtered_from_latency(self):
        value=summary([{'seconds':1,'ok':True},{'seconds':9,'ok':False}])
        self.assertEqual(value['failures'],1);self.assertEqual(value['max_seconds'],9)

    def test_zero_work_does_not_create_balancing_cost(self):
        shares,left=allocate_cost('99.99',{'A':0,'B':0})
        self.assertEqual(left,Decimal('99.99'));self.assertEqual(sum(shares.values()),0)

    def test_leap_year_month_and_business_timezone(self):
        start,end=month_bounds(2028,2)
        self.assertEqual((end-start).days,29);self.assertEqual(start.utcoffset().total_seconds(),8*3600)
