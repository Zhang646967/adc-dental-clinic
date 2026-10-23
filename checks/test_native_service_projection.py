"""Executable projection/privacy contracts, independent of Django/PostgreSQL."""
from decimal import Decimal
from types import SimpleNamespace as Obj
import unittest
from portal.service_projection import service_data
from scheduling.service_content import draft_from_guide


def profile(**changes):
    clinic=Obj(pk=2,name='已配置门店',postal_address='门店地址',phone='配置电话',private_key='NEVER-PROJECT')
    department=Obj(clinic=clinic,name='综合科')
    service=Obj(pk=7,department=department,duration_minutes=30,acquisition_cost='NEVER-PROJECT',
        public_dentists=[Obj(pk=3,name='接诊医师',home_address='NEVER-PROJECT')])
    return Obj(service=service,**dict(draft_from_guide('CHECKUP'),is_published=True,**changes))


class NativeServiceProjectionTests(unittest.TestCase):
    def test_only_explicit_public_fields_are_projected(self):
        row=service_data(profile())
        self.assertNotIn('NEVER-PROJECT',str(row))
        self.assertEqual(row['dentists'],[{'id':3,'name':'接诊医师'}])
        self.assertEqual((row['id'],row['clinic'],row['duration']),(7,2,30))
        self.assertNotIn('is_published',row)

    def test_unknown_fee_is_null_and_not_a_free_price(self):
        row=service_data(profile())
        self.assertIsNone(row['fee_amount'])
        self.assertEqual(row['fee_label'],'评估后确认费用')

    def test_zero_and_starting_fee_are_decimal_strings(self):
        zero=service_data(profile(fee_mode='FIXED',fee_amount=Decimal('0.00')))
        start=service_data(profile(fee_mode='FROM',fee_amount=Decimal('99.90')))
        self.assertEqual((zero['fee_amount'],zero['fee_label']),('0.00','¥0.00 / 本次服务'))
        self.assertEqual((start['fee_amount'],start['fee_label']),('99.90','¥99.90 起'))

    def test_child_service_requires_front_desk_in_projection(self):
        self.assertFalse(service_data(profile(category='CHILDREN'))['self_booking'])
        self.assertTrue(service_data(profile())['self_booking'])

    def test_content_is_preserved_as_plain_text_without_diagnostic_inference(self):
        row=service_data(profile(visit_content='先核对需求\n再讨论安排',preparation='携带已有资料'))
        self.assertEqual(row['visit_content'],'先核对需求\n再讨论安排')
        self.assertEqual(row['preparation'],'携带已有资料')
        self.assertNotIn('diagnosis',row)


if __name__=='__main__':unittest.main()
