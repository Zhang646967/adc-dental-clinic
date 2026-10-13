import unittest
from decimal import Decimal
from registry.catalog_rules import validate_price, validate_definition, validate_reason, CatalogInputError

class CataloguePureRules(unittest.TestCase):
    def test_valid_price(self):self.assertEqual(validate_price('12.30'),Decimal('12.30'))
    def test_zero_is_explicit(self):self.assertEqual(validate_price('0'),Decimal('0.00'))
    def test_negative_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price('-1')
    def test_nan_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price('NaN')
    def test_infinity_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price('Infinity')
    def test_float_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price(0.1)
    def test_bool_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price(True)
    def test_precision_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price('1.001')
    def test_overflow_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price('10000000000.00')
    def test_invalid_number_rejected(self):
        with self.assertRaises(CatalogInputError):validate_price('abc')
    def test_definition(self):self.assertEqual(validate_definition('CLEAN_1',' 洁治 ',' 每次 '),('CLEAN_1','洁治','每次'))
    def test_code_invalid(self):
        with self.assertRaises(CatalogInputError):validate_definition('../x','A','B')
    def test_empty_name(self):
        with self.assertRaises(CatalogInputError):validate_definition('A',' ','B')
    def test_reason_required(self):
        with self.assertRaises(CatalogInputError):validate_reason('')
    def test_reason_trim(self):self.assertEqual(validate_reason('  审核调整目录  '),'审核调整目录')
