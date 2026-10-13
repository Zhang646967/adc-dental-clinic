"""Executed pure/structural tests, NOT database or HTTP acceptance."""
import ast
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
import unittest
from registry.directory_rules import *
from adc_core.read_only_policy import allowed_in_read_only
from adc_core.route_manifest import named_routes
ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026,10,8)
CLINIC = {'clinic_code':'NEW_A','name':'合成诊所','postal_address':'虚构地址','supervisor_name':'虚构主管',
          'phone':'00123','email':'test@example.invalid','area_sqm':'123.45'}
DENTIST = {'employee_no':'DR_NEW','name':'合成牙医','date_of_birth':'1990-01-02','home_address':'虚构联系地址',
           'phone':'000123','email':'dentist@example.invalid'}
QUAL = {'code':'Q_NEW','name':'合成资格类别'}
def payload(kind='dentist'):
    result = {'contract':CONTRACT,'actor':2,'context':'00000000-0000-0000-0000-000000000001','revision':1,
        'operation':'00000000-0000-0000-0000-000000000002','kind':kind,'action':'register',
        'values':dict(DENTIST),'reason_code':'SOURCE_RECORD'}
    if kind == 'association':
        result.update(action='attach',values={'dentist_id':1,'qualification_id':2},state='a'*64)
    return result

class DirectoryRulesTests(unittest.TestCase):
    def bad(self,kind,details):
        with self.assertRaises(DirectoryInputError):normalize_registration(kind,details,today=TODAY)
    def test_clinic_roundtrip(self):self.assertEqual(normalize_registration('clinic',CLINIC,today=TODAY),CLINIC)
    def test_dentist_roundtrip(self):self.assertEqual(normalize_registration('dentist',DENTIST,today=TODAY),DENTIST)
    def test_qualification_roundtrip(self):self.assertEqual(normalize_registration('qualification',QUAL,today=TODAY),QUAL)
    def test_phone_keeps_leading_zero(self):self.assertEqual(normalize_registration('dentist',DENTIST,today=TODAY)['phone'],'000123')
    def test_whitespace_trim_without_case_rewrite(self):self.assertEqual(clean_code('  A_1-2  '),'A_1-2')
    def test_lowercase_code_rejected(self):self.bad('qualification',QUAL|{'code':'new'})
    def test_nonascii_code_rejected(self):self.bad('qualification',QUAL|{'code':'新编号'})
    def test_empty_required_field(self):self.bad('clinic',CLINIC|{'supervisor_name':'   '})
    def test_control_characters_rejected(self):self.bad('dentist',DENTIST|{'name':'牙医\x00'})
    def test_hidden_format_controls_rejected(self):self.bad('dentist',DENTIST|{'name':'牙\u200b医'})
    def test_length_limits(self):self.bad('dentist',DENTIST|{'name':'名'*81})
    def test_no_extra_active_field(self):self.bad('dentist',DENTIST|{'is_active':False})
    def test_no_extra_privilege_field(self):self.bad('clinic',CLINIC|{'is_superuser':True})
    def test_missing_fields(self):self.bad('clinic',{k:v for k,v in CLINIC.items() if k!='phone'})
    def test_no_mutation_of_input(self):s=deepcopy(DENTIST);normalize_registration('dentist',s,today=TODAY);self.assertEqual(s,DENTIST)
    def test_birth_date_object(self):self.assertEqual(normalize_registration('dentist',DENTIST|{'date_of_birth':date(1990,1,2)},today=TODAY),DENTIST)
    def test_future_date_rejected(self):self.bad('dentist',DENTIST|{'date_of_birth':'2026-10-09'})
    def test_invalid_date_rejected(self):self.bad('dentist',DENTIST|{'date_of_birth':'2025-02-29'})
    def test_compact_date_not_silently_normalized(self):self.bad('dentist',DENTIST|{'date_of_birth':'19900102'})
    def test_datetime_is_not_a_birth_date(self):self.bad('dentist',DENTIST|{'date_of_birth':datetime(1990,1,2)})
    def test_area_integer_to_exact_decimal(self):self.assertEqual(normalize_registration('clinic',CLINIC|{'area_sqm':'50'},today=TODAY)['area_sqm'],'50.00')
    def test_decimal_area_accepted(self):self.assertEqual(normalize_registration('clinic',CLINIC|{'area_sqm':Decimal('50.25')},today=TODAY)['area_sqm'],'50.25')
    def test_area_zero_rejected(self):self.bad('clinic',CLINIC|{'area_sqm':'0'})
    def test_area_negative_rejected(self):self.bad('clinic',CLINIC|{'area_sqm':'-1'})
    def test_area_extra_decimals_rejected(self):self.bad('clinic',CLINIC|{'area_sqm':'1.234'})
    def test_area_nonfinite_rejected(self):self.bad('clinic',CLINIC|{'area_sqm':'NaN'})
    def test_area_exponent_rejected(self):self.bad('clinic',CLINIC|{'area_sqm':'1e3'})
    def test_area_float_rejected(self):self.bad('clinic',CLINIC|{'area_sqm':0.1})
    def test_area_above_model_range(self):self.bad('clinic',CLINIC|{'area_sqm':'100000000'})
    def test_values_are_for_escaping_not_html_execution(self):self.assertEqual(normalize_registration('qualification',QUAL|{'name':'<b>原样文本</b>'},today=TODAY)['name'],'<b>原样文本</b>')
    def test_rows_follow_whitelist(self):self.assertEqual(len(display_rows('clinic',CLINIC)),7)
    def test_new_link_transition(self):self.assertEqual(association_transition('attach',dentist_active=True,qualification_active=True,link_active=None),('ATTACH',True))
    def test_restore_transition(self):self.assertEqual(association_transition('attach',dentist_active=True,qualification_active=True,link_active=False),('RESTORE',True))
    def test_withdraw_transition(self):self.assertEqual(association_transition('withdraw',dentist_active=True,qualification_active=True,link_active=True),('WITHDRAW',False))
    def test_active_duplicate_rejected(self):
        with self.assertRaises(DirectoryInputError):association_transition('attach',dentist_active=True,qualification_active=True,link_active=True)
    def test_inactive_endpoint_blocks_attach(self):
        for da,qa in [(False,True),(True,False),(False,False)]:
            with self.subTest(da=da,qa=qa), self.assertRaises(DirectoryInputError):association_transition('attach',dentist_active=da,qualification_active=qa,link_active=None)
    def test_withdraw_can_correct_inactive_endpoint(self):self.assertEqual(association_transition('withdraw',dentist_active=False,qualification_active=False,link_active=True),('WITHDRAW',False))
    def test_nonexistent_link_cannot_withdraw(self):
        with self.assertRaises(DirectoryInputError):association_transition('withdraw',dentist_active=True,qualification_active=True,link_active=None)
    def test_unknown_action_rejected(self):
        with self.assertRaises(DirectoryInputError):association_transition('delete',dentist_active=True,qualification_active=True,link_active=True)
    def test_boolean_id_rejected(self):
        with self.assertRaises(DirectoryInputError):positive_id(True)
    def test_new_registration_reason_bounded(self):
        with self.assertRaises(DirectoryInputError):validate_reason('arbitrary PHI')
    def test_wrong_action_reason_rejected(self):
        with self.assertRaises(DirectoryInputError):validate_reason('SOURCE_RECORD',action='withdraw')
    def test_payload_registration_valid(self):self.assertEqual(validate_payload(payload()),payload())
    def test_payload_link_valid(self):self.assertEqual(validate_payload(payload('association')),payload('association'))
    def test_payload_unknown_fields_rejected(self):
        with self.assertRaises(DirectoryInputError):validate_payload(payload()|{'role':'SYSADMIN'})
    def test_payload_invalid_uuid_rejected(self):
        with self.assertRaises(DirectoryInputError):validate_payload(payload()|{'operation':'123'})
    def test_payload_wrong_contract_rejected(self):
        with self.assertRaises(DirectoryInputError):validate_payload(payload()|{'contract':'old'})
    def test_payload_boolean_revision_rejected(self):
        with self.assertRaises(DirectoryInputError):validate_payload(payload()|{'revision':True})
    def test_digest_changes_when_audit_cursor_changes(self):self.assertNotEqual(state_digest({'active':True,'cursor':1}),state_digest({'active':True,'cursor':3}))
    def test_digest_stable_to_key_order(self):self.assertEqual(state_digest({'a':1,'b':2}),state_digest({'b':2,'a':1}))

class DirectoryStructureTests(unittest.TestCase):
    def test_all_named_routes_present(self):
        routes=named_routes(ROOT)
        for name in ('directory_home','directory_list','directory_detail','directory_create','directory_confirm','directory_attach','directory_withdraw_preview'):self.assertIn(name,routes)
    def test_route_roles_are_exact_technical_set(self):
        tree=ast.parse((ROOT/'workspaces/middleware.py').read_text())
        v=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ROUTES' for t in n.targets))
        rolemap={k.value:ast.literal_eval(val) for k,val in zip(v.keys,v.values) if isinstance(k,ast.Constant) and k.value.startswith('directory_')}
        self.assertEqual(len(rolemap),7);self.assertTrue(all(r=={'SYSADMIN'} for r in rolemap.values()))
    def test_directory_posts_not_readonly_exceptions(self):
        for n in ('directory_create','directory_confirm','directory_attach','directory_withdraw_preview'):self.assertFalse(allowed_in_read_only('POST',n))
    def test_command_is_atomic_and_password_rechecked(self):
        s=(ROOT/'registry/directory_services.py').read_text();self.assertIn('@transaction.atomic',s);self.assertIn('lock_operator(actor, operator_password)',s)
    def test_no_business_models_imported(self):
        s=(ROOT/'registry/directory_services.py').read_text()
        self.assertNotIn('from scheduling.models',s);self.assertNotIn('from patients.models',s);self.assertNotIn('from portal.models',s)
    def test_no_delete_or_bulk_update_in_directory_command(self):
        s=(ROOT/'registry/directory_services.py').read_text();self.assertNotIn('.delete(',s);self.assertNotIn('.update(',s)
    def test_password_not_serialized_in_proposal(self):
        tree=ast.parse((ROOT/'registry/directory_services.py').read_text())
        for n in ast.walk(tree):
            if isinstance(n,ast.Dict):self.assertNotIn('operator_password',[x.value for x in n.keys if isinstance(x,ast.Constant)])
    def test_guides_only_technical(self):
        from guidance.catalog import GUIDES
        for key in ('technical-directory','technical-qualifications'):self.assertEqual(GUIDES[key].roles,('SYSADMIN',))
    def test_decorators_mark_post_values_sensitive(self):
        s=(ROOT/'registry/directory_views.py').read_text();self.assertGreaterEqual(s.count('@sensitive_post_parameters()'),4)
    def test_confirmation_has_bound_workspace_and_explicit_action(self):
        s=(ROOT/'templates/registry/directory_confirm.html').read_text();self.assertIn('{% workspace_token %}',s);self.assertIn("{% url 'directory_confirm' %}",s);self.assertIn('尚未保存',s)
