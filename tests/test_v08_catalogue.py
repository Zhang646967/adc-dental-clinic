"""Authored integration tests; require real PostgreSQL, not part of pure-test results."""
from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from accounts.models import RoleAssignment
from adc_core.rules import RuleError
from care.models import AuditEvent
from registry.models import TreatmentType
from registry import catalog
from tests.test_v05 import V05Fixture

class CatalogueAcceptanceTests(V05Fixture,TransactionTestCase):
    def setUp(self):self.setup05()
    def create(self,actor=None,code='NEW1'):
        return catalog.create_item(actor=actor or self.fin,code=code,name='演示新增项目',unit='标准单位',price=Decimal('45.00'),reason='课程目录核对')
    def change(self,actor=None,token=None,amount='100.00'):
        self.service.refresh_from_db()
        return catalog.change_price(actor=actor or self.fin,item_id=self.service.pk,token=token or catalog.price_token(self.fin,self.service),price=Decimal(amount),reason='人工核对标准价')
    def test_finance_can_create(self):
        item=self.create();self.assertEqual(item.standard_unit_price,Decimal('45.00'))
        self.assertTrue(AuditEvent.objects.filter(event_type='CATALOG_ITEM_CREATED').exists())
    def test_hq_cannot_create(self):
        with self.assertRaises(PermissionDenied):self.create(self.hq)
    def test_doctor_cannot_write(self):
        with self.assertRaises(PermissionDenied):self.change(self.doctor)
    def test_tech_is_not_finance(self):
        with self.assertRaises(PermissionDenied):self.create(self.tech)
    def test_duplicate_code_rejected(self):
        self.create()
        with self.assertRaises(RuleError):self.create()
        self.assertEqual(TreatmentType.objects.filter(code='NEW1').count(),1)
    def test_old_token_rejected(self):
        token=catalog.price_token(self.fin,self.service);self.change(token=token)
        with self.assertRaises(RuleError):self.change(token=token,amount='110.00')
    def test_tampered_token_rejected(self):
        with self.assertRaises(RuleError):self.change(token='tampered')
    def test_revoked_finance_rejected(self):
        token=catalog.price_token(self.fin,self.service);RoleAssignment.objects.filter(user=self.fin).update(is_active=False)
        with self.assertRaises(PermissionDenied):self.change(token=token)
    def test_noop_rejected(self):
        with self.assertRaises(RuleError):self.change(amount='99.99')
    def test_inactive_item_rejected(self):
        self.service.is_active=False;self.service.save()
        with self.assertRaises(RuleError):self.change()
    @override_settings(ADC_READ_ONLY=True)
    def test_readonly_blocks_service(self):
        with self.assertRaises(PermissionDenied):self.create()
    def test_audit_failure_rolls_back_price(self):
        with patch('registry.catalog.emit',side_effect=RuntimeError('synthetic audit fault')):
            with self.assertRaises(RuntimeError):self.change()
        self.service.refresh_from_db();self.assertEqual(self.service.standard_unit_price,Decimal('99.99'))
    def test_published_bill_does_not_change(self):
        v,invoice=self.billed();version=invoice.current_record_version
        old_total=version.total_amount;old_lines=list(version.treatment_lines.values_list('unit_price','line_amount'))
        self.change(amount='125.50');version.refresh_from_db()
        self.assertEqual(version.total_amount,old_total)
        self.assertEqual(list(version.treatment_lines.values_list('unit_price','line_amount')),old_lines)
    def test_hq_read_page_and_no_edit_link(self):
        self.client.force_login(self.hq);response=self.client.get(reverse('catalogue_list'))
        self.assertEqual(response.status_code,200);self.assertNotContains(response,reverse('catalogue_create'))
    def test_patient_cannot_read_catalogue(self):
        self.client.force_login(self.pa);self.assertEqual(self.client.get(reverse('catalogue_list')).status_code,403)
    def test_form_requires_confirmation(self):
        self.client.force_login(self.fin)
        response=self.client.post(reverse('catalogue_create'),{'code':'TRY1','name':'测试','unit':'次','price':'1.00','reason':'测试缺少确认'})
        self.assertEqual(response.status_code,200);self.assertFalse(TreatmentType.objects.filter(code='TRY1').exists())
