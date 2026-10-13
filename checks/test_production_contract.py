"""Configuration decisions only. Does not start a web server or database."""
import unittest
from config.production_contract import validate_production_inputs

class ProductionContractTests(unittest.TestCase):
    def env(self,**kw):
        d={'ADC_DEPLOYMENT_STAGE':'staging','ADC_PUBLIC_HOST':'adc.example.test','DJANGO_SECRET_KEY':'test-only-value-'*5,'POSTGRES_DB':'adc_stage','POSTGRES_USER':'adc_web','POSTGRES_PASSWORD':'isolated-example-password-123','ADC_DATABASE_OWNER':'adc_owner','DB_HOST':'database.internal','DB_PORT':'5432','ADC_TRUST_PROXY_HEADERS':'1'}
        d.update(kw);return d
    def test_valid_configuration(self):self.assertEqual(validate_production_inputs(self.env()).host,'adc.example.test')
    def test_defaults_read_only(self):self.assertTrue(validate_production_inputs(self.env()).read_only)
    def test_explicit_writable(self):self.assertFalse(validate_production_inputs(self.env(ADC_READ_ONLY='0')).read_only)
    def test_absent_stage_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_DEPLOYMENT_STAGE=''))
    def test_wildcard_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_PUBLIC_HOST='*'))
    def test_scheme_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_PUBLIC_HOST='https://adc.example.test'))
    def test_host_list_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_PUBLIC_HOST='a.test,b.test'))
    def test_runtime_owner_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(POSTGRES_USER='adc_owner'))
    def test_postgres_user_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(POSTGRES_USER='postgres'))
    def test_db_without_tls_needs_private_ack(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_DB_SSLMODE='disable'))
    def test_private_network_exception_explicit(self):self.assertEqual(validate_production_inputs(self.env(ADC_DB_SSLMODE='disable',ADC_PRIVATE_DB_NETWORK_ACK='1')).sslmode,'disable')
    def test_proxy_trust_required(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_TRUST_PROXY_HEADERS='0'))
    def test_short_secret_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(DJANGO_SECRET_KEY='short'))
    def test_invalid_readonly_value_fails(self):
        with self.assertRaises(ValueError):validate_production_inputs(self.env(ADC_READ_ONLY='yes'))
