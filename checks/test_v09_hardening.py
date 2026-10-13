"""Pure capability decisions and structural review; not ORM/HTTP proof."""
import ast
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from adc_core.read_only_policy import allowed_in_read_only, READ_ONLY_POST_CONTRACTS
ROOT=Path(__file__).resolve().parents[1]

class ReadOnlyPolicyTests(unittest.TestCase):
    def test_safe_methods(self):
        for m in ('GET','HEAD','OPTIONS'):
            self.assertTrue(allowed_in_read_only(m,'unknown'))
    def test_result_post_allowed(self):self.assertTrue(allowed_in_read_only('POST','guide_result_wait'))
    def test_write_post_denied(self):
        for n in ('visit_create','wait_offer','account_manage_change','catalogue_price','schedule_plans'):
            self.assertFalse(allowed_in_read_only('POST',n))
    def test_session_routes_allowed(self):
        for n in ('login','portal_login','logout','activate_role','activate_clinic'):
            self.assertTrue(allowed_in_read_only('POST',n))
    def test_assistant_is_bounded_exception(self):self.assertTrue(allowed_in_read_only('POST','assistant_api'))
    def test_no_unknown_post(self):self.assertFalse(allowed_in_read_only('POST','new_query'))
    def test_unresolved_fails_closed(self):self.assertFalse(allowed_in_read_only('POST',None))
    def test_no_substring_match(self):self.assertFalse(allowed_in_read_only('POST','guide_result_wait_delete'))
    def test_namespace_is_exact(self):self.assertFalse(allowed_in_read_only('POST','unreviewed:guide_result_wait'))
    def test_put_to_query_not_allowed(self):self.assertFalse(allowed_in_read_only('PUT','guide_result_wait'))
    def test_delete_to_session_not_allowed(self):self.assertFalse(allowed_in_read_only('DELETE','login'))
    def test_registry_immutable(self):
        with self.assertRaises(TypeError):READ_ONLY_POST_CONTRACTS['anything']='query'

class MiddlewareBranchTests(unittest.TestCase):
    def branch(self,enabled,name,method='POST'):
        conf=types.ModuleType('django.conf');conf.settings=types.SimpleNamespace(ADC_READ_ONLY=enabled)
        http=types.ModuleType('django.http');http.HttpResponseForbidden=lambda text: types.SimpleNamespace(status_code=403,body=text)
        spec=importlib.util.spec_from_file_location('_adc_read_only_review',ROOT/'adc_core/middleware.py')
        mod=importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules,{'django.conf':conf,'django.http':http}):spec.loader.exec_module(mod)
        mw=mod.ReadOnlyDemoMiddleware(lambda req:'downstream')
        request=types.SimpleNamespace(method=method,resolver_match=types.SimpleNamespace(view_name=name),path='/fake/')
        return mw.process_view(request,None,[],{})
    def test_readonly_query_reaches_handler(self):self.assertIsNone(self.branch(True,'guide_result_wait'))
    def test_readonly_write_rejected(self):self.assertEqual(self.branch(True,'wait_offer').status_code,403)
    def test_normal_mode_unchanged(self):self.assertIsNone(self.branch(False,'wait_offer'))
    def test_path_spelling_does_not_grant(self):self.assertEqual(self.branch(True,'unknown').status_code,403)

class SecuritySuspensionStructureTests(unittest.TestCase):
    def setUp(self):self.s=(ROOT/'accounts/governance.py').read_text()
    def branch(self,action):
        tree=ast.parse(self.s)
        for n in ast.walk(tree):
            if isinstance(n,ast.If) and ast.unparse(n.test)==f"action == '{action}'":
                return '\n'.join(ast.unparse(x) for x in n.body)
        self.fail('missing action')
    def test_security_action_registered(self):self.assertIn("'security_suspend'",self.s)
    def test_suspend_does_not_query_pending_work(self):self.assertNotIn('pending_work',self.branch('security_suspend'))
    def test_suspend_invalidates_password(self):self.assertIn('set_unusable_password()',self.branch('security_suspend'))
    def test_suspend_blocks_login(self):self.assertIn('target.is_active = False',self.branch('security_suspend'))
    def test_suspend_no_business_write(self):
        branch=self.branch('security_suspend')
        for name in ('Visit.','WaitRequest.','PatientAccess.','RoleAssignment.','delete('):self.assertNotIn(name,branch)
    def test_regular_disable_still_checks_work(self):self.assertIn('pending_work',self.branch('disable'))
    def test_enable_requires_reset(self):self.assertIn('has_usable_password()',self.branch('enable'))
    def test_existing_atomic_boundary(self):self.assertIn('@transaction.atomic\ndef change_account',self.s)
    def test_audit_and_context_invalidation_remain(self):
        self.assertIn('invalidate_contexts(target)',self.s);self.assertIn("emit(actor,'ACCOUNT_GOVERNED'",self.s)
    def test_extra_confirmation_control(self):self.assertIn('security_confirmed',(ROOT/'accounts/governance_forms.py').read_text())
    def test_http_action_not_csrf_exempt(self):self.assertNotIn('csrf_exempt',(ROOT/'accounts/governance_views.py').read_text())
    def test_shared_write_guard_retained(self):self.assertIn('settings.ADC_READ_ONLY',(ROOT/'accounts/policies.py').read_text())
