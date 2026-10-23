"""Publication and navigation rules; no framework/database execution claimed."""
import unittest
from portal.booking_intent_rules import selected_service
from scheduling.service_content import (CONTENT_LIMITS, GUIDES, draft_from_guide,
    operational_blockers, publication_readiness)


class PublicationReadinessTests(unittest.TestCase):
    def content(self, **changes):
        values=draft_from_guide('CHECKUP');values.update(changes);return values

    def test_missing_description_is_a_visible_owner_task(self):
        result=publication_readiness(None)
        self.assertEqual(result['code'],'MISSING')
        self.assertFalse(result['visible']);self.assertFalse(result['can_publish'])
        self.assertTrue(result['blockers'])

    def test_complete_draft_requires_explicit_publication(self):
        result=publication_readiness(self.content())
        self.assertEqual(result['code'],'DRAFT')
        self.assertTrue(result['can_publish']);self.assertFalse(result['visible'])

    def test_public_content_is_hidden_when_any_required_section_is_blank(self):
        for field in CONTENT_LIMITS:
            with self.subTest(field=field):
                data=self.content(is_published=True);data[field]=' '
                result=publication_readiness(data)
                self.assertEqual(result['code'],'HIDDEN')
                self.assertFalse(result['visible']);self.assertFalse(result['can_publish'])

    def test_operational_block_prevents_publication_without_altering_the_draft(self):
        values=self.content(is_published=True)
        result=publication_readiness(values,operational_issues=('本店接诊资源配置尚未启用',))
        self.assertEqual(result['code'],'HIDDEN')
        self.assertTrue(result['content_ready']);self.assertFalse(result['visible'])
        self.assertTrue(values['is_published'])

    def test_children_can_be_public_without_claiming_self_service_delegation(self):
        result=publication_readiness(self.content(category='CHILDREN',is_published=True))
        self.assertTrue(result['visible']);self.assertFalse(result['self_booking'])
        self.assertTrue(publication_readiness(self.content(is_published=True))['self_booking'])

    def test_readiness_does_not_treat_zero_as_unknown_fee(self):
        result=publication_readiness(self.content(is_published=True,fee_amount=0))
        self.assertFalse(result['visible'])
        self.assertIn('费用金额',result['blockers'][0])

    def test_each_operational_precondition_is_independent_and_typed(self):
        fields=dict(clinic_active=True,department_active=True,service_active=True,has_dentists=True,policy_enabled=True)
        self.assertEqual(operational_blockers(**fields),())
        for key in fields:
            for bad in (False,None,1,'ENABLED'):
                with self.subTest(key=key,bad=bad):
                    values=dict(fields);values[key]=bad
                    self.assertEqual(len(operational_blockers(**values)),1)

    def test_templates_never_create_or_publish_a_clinic_service_or_invent_a_price(self):
        for guide in GUIDES:
            with self.subTest(category=guide.key):
                values=draft_from_guide(guide.key)
                self.assertFalse(values['is_published']);self.assertIsNone(values['fee_amount'])
                self.assertNotIn('service',values)
                self.assertTrue(publication_readiness(values)['content_ready'])
        self.assertEqual(draft_from_guide('unknown'),{})

    def test_editing_one_template_does_not_overwrite_other_drafts(self):
        first=draft_from_guide('CHECKUP');first['summary']='本店自己的说明'
        self.assertNotEqual(draft_from_guide('CHECKUP')['summary'],first['summary'])


class BookingIntentRulesTests(unittest.TestCase):
    def setUp(self):
        self.ctx='f913a3eb-d79b-459a-8edc-f57ee545b590'
        self.data={'uid':12,'workspace':self.ctx,'service':9}

    def choose(self,data):
        return selected_service(data,user_id=12,workspace_id=self.ctx)

    def test_same_user_and_workspace_can_resume_only_a_typed_service(self):
        self.assertEqual(self.choose(self.data),9)

    def test_selection_cannot_be_reused_by_another_user_or_login_workspace(self):
        self.assertIsNone(selected_service(self.data,user_id=13,workspace_id=self.ctx))
        self.assertIsNone(selected_service(self.data,user_id=12,workspace_id='another-login'))

    def test_redirect_urls_roles_and_scope_fields_are_not_navigation_authority(self):
        for extra in ({'next':'https://evil.invalid'},{'role':'SYSADMIN'},{'clinic':42}):
            self.assertIsNone(self.choose(dict(self.data,**extra)))

    def test_malformed_payloads_are_rejected(self):
        for bad in (None,[],{},'https://evil.invalid',{'uid':12,'service':9}):
            with self.subTest(payload=bad):self.assertIsNone(self.choose(bad))
        self.assertIsNone(self.choose(dict(self.data,uid=True)))

    def test_service_ids_are_bounded_integers_not_boolean_or_external_paths(self):
        for value in (True,0,-1,10**18,'9','/portal/slots/','https://evil.invalid',{},9.0):
            with self.subTest(value=value):self.assertIsNone(self.choose(dict(self.data,service=value)))


if __name__=='__main__':unittest.main()
