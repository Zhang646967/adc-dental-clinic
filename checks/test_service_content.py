"""Executable patient-content/availability rules, not PostgreSQL/HTTP evidence."""
from datetime import date, timedelta
from decimal import Decimal
import unittest
from portal.availability_search import future_options
from scheduling.service_content import (GUIDES, GUIDE_BY_KEY, CONTENT_LIMITS,
    validate_presentation, fee_label, positive_id, patient_request)


def content(**changes):
    data={key:'本店已核对的服务信息' for key in CONTENT_LIMITS}
    data.update(category='CHECKUP',fee_mode='ASSESSED',fee_amount=None,is_published=True)
    return dict(data,**changes)


class PresentationRulesTests(unittest.TestCase):
    def test_complete_published_content_is_valid(self):
        self.assertEqual(validate_presentation(content()),{})

    def test_each_missing_public_section_is_rejected(self):
        for key in CONTENT_LIMITS:
            with self.subTest(field=key):
                data=content();data[key]=' \n\t'
                self.assertIn(key,validate_presentation(data))

    def test_incomplete_draft_is_not_forced_to_publish(self):
        data=content();data.update({key:'' for key in CONTENT_LIMITS});data['is_published']=False
        self.assertEqual(validate_presentation(data),{})

    def test_content_length_limits_apply_to_drafts_too(self):
        for key,limit in CONTENT_LIMITS.items():
            with self.subTest(field=key):
                data=content();data[key]='字'*(limit+1);data['is_published']=False
                self.assertIn(key,validate_presentation(data))

    def test_unknown_fee_cannot_be_encoded_as_zero(self):
        for amount in (Decimal('0'),Decimal('100')):
            self.assertIn('fee_amount',validate_presentation(content(fee_amount=amount)))

    def test_known_zero_and_fixed_or_starting_fees_remain_distinct(self):
        for mode in ('FIXED','FROM'):
            self.assertFalse(validate_presentation(content(fee_mode=mode,fee_amount=Decimal('0'))))
        self.assertEqual(fee_label('FIXED',Decimal('0')),'¥0.00 / 本次服务')
        self.assertEqual(fee_label('FROM',Decimal('89.90')),'¥89.90 起')
        self.assertEqual(fee_label('ASSESSED',None),'评估后确认费用')

    def test_invalid_price_values_fail_closed(self):
        for value in (None,-1,'-0.01','0.001','NaN','sNaN','Infinity','1e50','10000000000',True,1.2,{},'not a price'):
            with self.subTest(value=value):
                self.assertIn('fee_amount',validate_presentation(content(fee_mode='FIXED',fee_amount=value)))

    def test_invalid_category_mode_and_publication_flags_are_rejected(self):
        for field in ('category','fee_mode'):
            for value in ('UNKNOWN','',None,[],{}):
                with self.subTest(field=field,value=value):
                    data=content();data[field]=value
                    self.assertIn(field,validate_presentation(data))
        self.assertIn('is_published',validate_presentation(content(is_published='yes')))

    def test_guides_have_independent_question_preparation_and_scope(self):
        self.assertEqual(len(GUIDES),8)
        self.assertEqual(len(GUIDE_BY_KEY),8)
        for guide in GUIDES:
            self.assertTrue(guide.question and guide.summary and guide.preparation and guide.boundary)
            self.assertEqual(len(guide.discussion),3)
        self.assertIn('代办',GUIDE_BY_KEY['CHILDREN'].boundary)

    def test_only_typed_positive_ids_can_be_used_as_booking_hints(self):
        for value in ('https://example.invalid','//example.invalid','-1','0',' 1','1/2','1?next=x','１',True,1,None,'9'*19):
            with self.subTest(value=value):self.assertIsNone(positive_id(value))
        self.assertEqual(positive_id('23'),23)

    def test_patient_request_preserves_text_without_diagnosis(self):
        self.assertEqual(patient_request('  想检查一下\n最近不舒服  '),'想检查一下\n最近不舒服')
        self.assertEqual(patient_request('  '),'')
        for value in ('字'*501,'hello\x00',True,None,{}):
            with self.subTest(value=value),self.assertRaises(ValueError):patient_request(value)


class AvailabilitySearchTests(unittest.TestCase):
    def setUp(self):self.today=date(2026,10,22)

    def test_empty_today_does_not_hide_future_options(self):
        days=[]
        def read(day):
            days.append(day)
            return [] if day==self.today else [(day,0)]
        rows=future_options(read,first_day=self.today)
        self.assertEqual(rows[0],(self.today+timedelta(days=1),0))
        self.assertEqual(len(days),15)
        self.assertEqual(days[-1],self.today+timedelta(days=14))

    def test_stops_reading_when_result_limit_is_reached(self):
        days=[]
        def read(day):days.append(day);return [(day,i) for i in range(60)]
        rows=future_options(read,first_day=self.today)
        self.assertEqual(len(rows),80)
        self.assertEqual(days,[self.today,self.today+timedelta(days=1)])
        self.assertEqual(rows[-1],(self.today+timedelta(days=1),19))

    def test_empty_search_is_bounded_and_chronological(self):
        days=[]
        self.assertEqual(future_options(lambda d:days.append(d) or [],first_day=self.today),[])
        self.assertEqual(days,[self.today+timedelta(days=i) for i in range(15)])

    def test_reader_errors_are_not_disguised_as_no_availability(self):
        def read(_):raise RuntimeError('Resource catalogue changed')
        with self.assertRaises(RuntimeError):future_options(read,first_day=self.today)

    def test_invalid_or_unbounded_search_parameters_are_rejected(self):
        for horizon in (-1,15,True,1.5,None):
            with self.subTest(horizon=horizon),self.assertRaises(ValueError):
                future_options(lambda _:[],first_day=self.today,horizon_days=horizon)
        for limit in (0,81,False,1.5,None):
            with self.subTest(limit=limit),self.assertRaises(ValueError):
                future_options(lambda _:[],first_day=self.today,limit=limit)


if __name__=='__main__':unittest.main()
