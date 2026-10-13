
"""SU-26 pure policy tests. No Django/HTTP/database execution is implied."""
import ast
import copy
from pathlib import Path
import unittest
from uuid import uuid4
from patients.contact_rules import (CONTACT_FIELDS, CONTACT_LABELS, CONTRACT, ContactInputError,
                                   normalize_details, differences, state_digest, validate_proposal, validate_reason)
from scripts.verify_isolated import validate_configuration, compose_command

ROOT=Path(__file__).resolve().parents[1]

def details():
    return dict(phone='000-1234',email='course@example.invalid',billing_address='虚构课程地址',
                emergency_name='演示联系人',emergency_phone='000-9876')

class ContactRulesTests(unittest.TestCase):
    def test_five_bounded_fields(self):
        self.assertEqual(set(CONTACT_FIELDS),{'phone','email','billing_address','emergency_name','emergency_phone'})
    def test_normal_values(self):self.assertEqual(normalize_details(details()),details())
    def test_trim_is_explicit(self):
        v=details();v['phone']=' 000 ';self.assertEqual(normalize_details(v)['phone'],'000')
    def test_optional_email_clear(self):
        v=details();v['email']='';self.assertEqual(normalize_details(v)['email'],'')
    def test_missing_field(self):
        v=details();del v['phone']
        with self.assertRaises(ContactInputError):normalize_details(v)
    def test_identity_mass_assignment(self):
        for key in ('name','is_active','allergy_status','date_of_birth','patient_no','created_in_clinic'):
            with self.subTest(key=key),self.assertRaises(ContactInputError):normalize_details(details()|{key:'x'})
    def test_non_mapping(self):
        with self.assertRaises(ContactInputError):normalize_details([])
    def test_no_numeric_coercion(self):
        for value in (True,123,None,{},[]):
            with self.subTest(value=value),self.assertRaises(ContactInputError):normalize_details(details()|{'phone':value})
    def test_required_field_empty(self):
        for key in set(CONTACT_FIELDS)-{'email'}:
            with self.subTest(key=key),self.assertRaises(ContactInputError):normalize_details(details()|{key:' '})
    def test_length_boundaries(self):
        for key,limit in [('phone',32),('email',254),('billing_address',255),('emergency_name',80),('emergency_phone',32)]:
            with self.subTest(key=key):
                self.assertEqual(len(normalize_details(details()|{key:'a'*limit})[key]),limit)
                with self.assertRaises(ContactInputError):normalize_details(details()|{key:'a'*(limit+1)})
    def test_controls_rejected_not_deleted(self):
        for value in ('000\n','000\r','\t000','a\u202eb','a\u200bb','a\x00b','a\u2028b','a\ud800b'):
            with self.subTest(value=repr(value)),self.assertRaises(ContactInputError):normalize_details(details()|{'phone':value})
    def test_international_number_not_forced_into_china_mobile_regex(self):
        v='+44 (0)20 0000 0000';self.assertEqual(normalize_details(details()|{'phone':v})['phone'],v)
    def test_noop_has_no_differences(self):self.assertEqual(differences(details(),details()),())
    def test_only_changed_field(self):
        rows=differences(details(),details()|{'phone':'111'});self.assertEqual([x.field for x in rows],['phone'])
    def test_original_not_mutated(self):
        original=details();v=normalize_details(original);v['phone']='x';self.assertEqual(original,details())
    def test_state_stable_for_field_order(self):
        a=state_digest(patient_id=1,values=details(),audit_cursor=0)
        b=state_digest(patient_id=1,values=dict(reversed(list(details().items()))),audit_cursor=0)
        self.assertEqual(a,b)
    def test_state_target_bound(self):
        self.assertNotEqual(state_digest(patient_id=1,values=details(),audit_cursor=0),state_digest(patient_id=2,values=details(),audit_cursor=0))
    def test_audit_cursor_catches_aba(self):
        self.assertNotEqual(state_digest(patient_id=1,values=details(),audit_cursor=8),state_digest(patient_id=1,values=details(),audit_cursor=10))
    def test_state_changes_on_each_contact_field(self):
        original=state_digest(patient_id=1,values=details(),audit_cursor=0)
        for field in CONTACT_FIELDS:
            with self.subTest(field=field):self.assertNotEqual(original,state_digest(patient_id=1,values=details()|{field:'other'},audit_cursor=0))
    def test_reason_is_enum_not_free_text(self):
        self.assertEqual(validate_reason('ENTRY_CORRECTION'),'ENTRY_CORRECTION')
        with self.assertRaises(ContactInputError):validate_reason('患者电话123密码456')
    def payload(self):
        return dict(contract=CONTRACT,actor=1,patient=2,clinic=3,context=str(uuid4()),revision=4,
                    state='a'*64,operation=str(uuid4()),values=details(),reason_code='PATIENT_UPDATE')
    def test_proposal_shape(self):self.assertEqual(validate_proposal(self.payload())['contract'],CONTRACT)
    def test_proposal_rejects_extra_key(self):
        with self.assertRaises(ContactInputError):validate_proposal(self.payload()|{'is_admin':True})
    def test_proposal_rejects_missing_key(self):
        p=self.payload();del p['operation']
        with self.assertRaises(ContactInputError):validate_proposal(p)
    def test_proposal_rejects_type_confusion(self):
        for field,value in [('actor',True),('revision',False),('patient',0),('state','z'*64),('operation',''),('context',5)]:
            with self.subTest(field=field),self.assertRaises(ContactInputError):validate_proposal(self.payload()|{field:value})
    def test_proposal_rejects_old_contract(self):
        with self.assertRaises(ContactInputError):validate_proposal(self.payload()|{'contract':'old'})
    def test_proposal_requires_exact_preview_values(self):
        p=self.payload();p['values']['phone']=' 000 '
        with self.assertRaises(ContactInputError):validate_proposal(p)
    def test_labels_are_immutable(self):
        with self.assertRaises(TypeError):CONTACT_LABELS['name']='姓名'

class ContactArchitectureTests(unittest.TestCase):
    def test_commands_have_atomic_boundary_and_shared_guard(self):
        src=(ROOT/'patients/contact_services.py').read_text();tree=ast.parse(src)
        for name in ('prepare_contact_change','confirm_contact_change'):
            fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==name)
            self.assertIn('transaction.atomic',[ast.unparse(d) for d in fn.decorator_list])
            self.assertIn('lock_clinic_grant',ast.unparse(fn))
    def test_only_contact_fields_saved(self):
        text=(ROOT/'patients/contact_services.py').read_text()
        self.assertIn('save(update_fields=list(CONTACT_FIELDS))',text)
        for bad in ('Invoice.objects','PatientAccess.objects','set_password(','update_allergies('):self.assertNotIn(bad,text)
    def test_preview_does_not_emit_or_save(self):
        tree=ast.parse((ROOT/'patients/contact_services.py').read_text())
        fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name=='prepare_contact_change')
        text=ast.unparse(fn);self.assertNotIn('.save(',text);self.assertNotIn('emit(',text)
    def test_audit_contains_field_names_not_values(self):
        tree=ast.parse((ROOT/'patients/contact_services.py').read_text())
        call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='emit')
        summary=next(k.value for k in call.keywords if k.arg=='summary')
        self.assertEqual({k.value for k in summary.keys},{'operation','fields','clinic_id','reason_code','contract'})
    def test_contact_post_not_allowed_in_readonly(self):
        from adc_core.read_only_policy import allowed_in_read_only
        self.assertFalse(allowed_in_read_only('POST','patient_contact_edit'))
        self.assertFalse(allowed_in_read_only('POST','patient_contact_confirm'))
    def test_contact_guide_is_frontdesk_only(self):
        from guidance.catalog import GUIDES
        self.assertEqual(GUIDES['front-contact'].roles,('FRONT_DESK',))
    def test_contact_keywords_choose_only_frontdesk_guide(self):
        from guidance.catalog import choose_guide
        self.assertEqual(choose_guide('FRONT_DESK','correction','我要更正患者电话'),'front-contact')
        self.assertNotEqual(choose_guide('DENTIST','correction','我要更正患者电话'),'front-contact')
        self.assertIsNone(choose_guide('FRONT_DESK','clinical','修改电话后诊断牙痛'))
    def test_sensitive_post_and_no_cache(self):
        s=(ROOT/'patients/contact_views.py').read_text()
        self.assertEqual(s.count('@never_cache'),2);self.assertEqual(s.count('@sensitive_post_parameters()'),2)
        self.assertNotIn('csrf_exempt',s)

class IsolatedVerificationContractTests(unittest.TestCase):
    def config(self):
        return {'services':{'verify':{'environment':{'DB_HOST':'verify-db','POSTGRES_DB':'adc_verify',
            'DJANGO_SETTINGS_MODULE':'config.settings.test','AI_MODE':'disabled','AI_API_KEY':'','OPENAI_API_KEY':''},
            'volumes':[{'type':'bind','source':str(ROOT/'evidence/verification'),'target':'/evidence'}]},
            'verify-db':{'tmpfs':['/var/lib/postgresql/data'],'environment':{'POSTGRES_DB':'adc_verify'}}}}
    def test_expected_config(self):self.assertTrue(validate_configuration(self.config()))
    def test_port_exposure_rejected(self):
        c=self.config();c['services']['verify']['ports']=['8000:8000']
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_existing_volume_rejected(self):
        c=self.config();c['volumes']={'adc_data':{'external':True}}
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_prod_db_host_rejected(self):
        c=self.config();c['services']['verify']['environment']['DB_HOST']='existing-db'
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_key_rejected(self):
        c=self.config();c['services']['verify']['environment']['AI_API_KEY']='secret'
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_extra_mount_rejected(self):
        c=self.config();c['services']['verify']['volumes'].append({'source':'/.env','target':'/.env'})
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_db_mount_rejected(self):
        c=self.config();c['services']['verify-db']['volumes']=['prod:/data']
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_unknown_service_rejected(self):
        c=self.config();c['services']['web']={}
        with self.assertRaises(ValueError):validate_configuration(c)
    def test_command_requires_isolated_project(self):
        with self.assertRaises(ValueError):compose_command('adc_production','test.env')
    def test_command_never_uses_default_compose(self):
        cmd=compose_command('adc_verify_test','empty.env');self.assertIn('--env-file',cmd)
        self.assertTrue(cmd[-1].endswith('compose.verify.yaml'));self.assertNotIn('compose.yaml',cmd)

class WindowsRunnerTests(unittest.TestCase):
    def test_windows_paths_validate_inside_linux_container(self):
        from scripts.verify_isolated import normalized_host_path
        self.assertEqual(normalized_host_path('D:/Users/Zhang/ADC/evidence/verification'),
                         normalized_host_path(r'D:\Users\Zhang\ADC\evidence\verification'))
    def test_cmd_needs_docker_not_host_python(self):
        s=(ROOT/'VERIFY_ISOLATED_WINDOWS.cmd').read_text()
        self.assertNotIn('where python',s)
        self.assertIn('run --rm --no-deps verify python scripts/verify_isolated.py',s)
        self.assertNotIn('down -v',s)
        self.assertIn('-f compose.verify.yaml',s)
