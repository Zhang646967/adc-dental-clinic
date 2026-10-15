import unittest
from finance.statement_csv import parse, unique_rows, MAX_BYTES, MAX_ROWS
from adc_core.rules import RuleError

HEADER=b'transaction_id,booked_on,direction,amount,currency,reference\n'
ROW=b'T-1,2026-10-15,IN,100.00,CNY,R-1\n'

class StatementCSVTests(unittest.TestCase):
    def test_valid_bom_and_crlf_preserve_reference_case(self):
        got=parse(b'\xef\xbb\xbf'+HEADER.replace(b'\n',b'\r\n')+ROW.replace(b'R-1',b'Ref-a').replace(b'\n',b'\r\n'))
        self.assertEqual(got[0]['reference'],'Ref-a')
    def test_exact_duplicates_are_retained_and_classifiable(self):
        rows=parse(HEADER+ROW*2);self.assertEqual(len(rows),2);self.assertEqual(len(unique_rows(rows)),1)
    def test_conflicting_id_in_file_rejected(self):
        with self.assertRaises(RuleError):parse(HEADER+ROW+ROW.replace(b'100.00',b'100.01'))
    def test_header_cannot_select_clinic_or_cash_identity(self):
        for header in (HEADER.replace(b'reference',b'clinic_id'),HEADER+b'extra,header\n'):
            with self.assertRaises(RuleError):parse(header+ROW)
    def test_invalid_amounts_not_coerced(self):
        for amount in (b'0.00',b'-1.00',b'1',b'1.001',b'NaN',b'1e2',b'999999999999999.99'):
            with self.subTest(amount=amount),self.assertRaises(RuleError):parse(HEADER+ROW.replace(b'100.00',amount))
    def test_direction_and_currency_are_strict(self):
        for row in (ROW.replace(b'IN',b'in'),ROW.replace(b'CNY',b'cny'),ROW.replace(b'CNY',b'CN')):
            with self.assertRaises(RuleError):parse(HEADER+row)
    def test_bad_date_rejected(self):
        for day in (b'2026-02-30',b'20261015',b'15/10/2026'):
            with self.assertRaises(RuleError):parse(HEADER+ROW.replace(b'2026-10-15',day))
    def test_oversize_and_row_count_bounded(self):
        with self.assertRaises(RuleError):parse(b'x'*(MAX_BYTES+1))
        with self.assertRaises(RuleError):parse(HEADER+ROW*(MAX_ROWS+1))
        self.assertEqual(len(parse(HEADER+ROW*MAX_ROWS)),MAX_ROWS)
    def test_bad_encoding_controls_and_quotes_rejected(self):
        for source in (HEADER+ROW+b'\xff',HEADER+ROW.replace(b'R-1',b'R\x00x'),HEADER+b'"unfinished'):
            with self.assertRaises(RuleError):parse(source)
    def test_empty_and_extra_columns_rejected(self):
        for source in (HEADER,b'',HEADER+ROW.replace(b'R-1',b'R-1,extra')):
            with self.assertRaises(RuleError):parse(source)
    def test_long_identifier_rejected_but_empty_reference_is_unmatched_evidence(self):
        with self.assertRaises(RuleError):parse(HEADER+ROW.replace(b'T-1',b'x'*81))
        self.assertEqual(parse(HEADER+ROW.replace(b'R-1',b''))[0]['reference'],'')
