"""Pure, executable tests for fixes. These do not stand in for PostgreSQL tests."""
import ast
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from coordination.windows import validate_wait_window, window_bounds, WindowError
from workspaces.selection import sole_role

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,9,27,7,20,31,tzinfo=timezone.utc)

class WindowPolicyTests(unittest.TestCase):
    def err(self,start,end,code,field):
        with self.assertRaises(WindowError) as ctx:validate_wait_window(start,end,now=NOW)
        self.assertEqual(ctx.exception.code,code);self.assertEqual(ctx.exception.field,field)
    def test_valid_half_hour(self):
        t=NOW+timedelta(hours=1);self.assertEqual(validate_wait_window(t,t+timedelta(minutes=30),now=NOW),(t,t+timedelta(minutes=30)))
    def test_end_before_start(self):self.err(NOW+timedelta(days=2),NOW+timedelta(days=1),'order','latest')
    def test_equal_end(self):self.err(NOW+timedelta(hours=1),NOW+timedelta(hours=1),'order','latest')
    def test_short_window(self):self.err(NOW+timedelta(hours=1),NOW+timedelta(hours=1,minutes=29),'duration','latest')
    def test_past_start(self):self.err(NOW-timedelta(hours=1),NOW+timedelta(hours=1),'past','earliest')
    def test_start_at_now(self):self.err(NOW,NOW+timedelta(minutes=30),'past','earliest')
    def test_horizon_end(self):self.err(NOW+timedelta(days=1),NOW+timedelta(days=14,seconds=1),'horizon','latest')
    def test_exact_horizon_accepted(self):validate_wait_window(NOW+timedelta(days=1),NOW+timedelta(days=14),now=NOW)
    def test_timezone_required(self):self.err(datetime(2026,9,28),NOW+timedelta(days=2),'timezone','earliest')
    def test_equivalent_timezones(self):
        a=(NOW+timedelta(hours=1)).astimezone(ZoneInfo('Asia/Shanghai'))
        b=(NOW+timedelta(hours=2)).astimezone(ZoneInfo('America/Chicago'))
        validate_wait_window(a,b,now=NOW)
    def test_exact_non_grid_preference_preserved(self):
        a=NOW.replace(second=0)+timedelta(days=1,minutes=3);b=a+timedelta(hours=2)
        self.assertEqual(validate_wait_window(a,b,now=NOW),(a,b))
    def test_bounds_start_after_now(self):self.assertGreater(window_bounds(NOW).min_start,NOW)
    def test_exact_minute_start_still_future(self):
        n=NOW.replace(second=0);self.assertEqual(window_bounds(n).min_start,n+timedelta(minutes=1))
    def test_upper_has_room_for_half_hour(self):
        b=window_bounds(NOW);self.assertEqual(b.max_end-b.max_start,timedelta(minutes=30))
    def test_payload_is_beijing(self):
        self.assertEqual(window_bounds(NOW).as_dict()['min_start'],'2026-09-27T15:21')
    def test_midnight_rollover(self):
        n=datetime(2026,9,27,15,59,50,tzinfo=timezone.utc)
        self.assertEqual(window_bounds(n).as_dict()['min_start'],'2026-09-28T00:00')
    def test_ui_upper_does_not_exceed_authority(self):self.assertLessEqual(window_bounds(NOW).max_end,NOW+timedelta(days=14))
    def test_old_message_removed_from_service(self):self.assertNotIn('候补范围须在未来14天内，至少连续30分钟',(ROOT/'coordination/services.py').read_text())
    def test_validation_stays_in_service(self):self.assertIn('validate_wait_window(earliest, latest, now=timezone.now())',(ROOT/'coordination/services.py').read_text())

class ShortcutTests(unittest.TestCase):
    def test_zero(self):self.assertIsNone(sole_role([]))
    def test_patient(self):self.assertEqual(sole_role(['PATIENT']),'PATIENT')
    def test_doctor(self):self.assertEqual(sole_role(['DENTIST']),'DENTIST')
    def test_two_clinics_one_role(self):self.assertEqual(sole_role(['MANAGER','MANAGER']),'MANAGER')
    def test_multi_role(self):self.assertIsNone(sole_role(['MANAGER','DENTIST']))
    def test_unknown_role_rejected(self):
        with self.assertRaises(ValueError):sole_role(['ADMIN_ANYTHING'])
    def test_activation_clears_old_scope(self):self.assertIn('ctx.clinic = None',(ROOT/'workspaces/activation.py').read_text())
    def test_both_shells_condition_switch_button(self):
        for f in ('templates/base.html','templates/portal/base.html'):
            self.assertIn("{% if workspace_can_switch_role %}<a",(ROOT/f).read_text())
    def test_activation_is_database_backed(self):
        s=(ROOT/'workspaces/activation.py').read_text();self.assertIn('select_for_update()',s);self.assertIn('available_roles',s);self.assertIn('ctx.revision += 1',s)

class V08PackagingChecks(unittest.TestCase):
    def test_manager_cta_is_navigation_not_write(self):
        text=(ROOT/'templates/coordination/waitlist.html').read_text()
        self.assertIn("{% if may_plan %}",text);self.assertIn("href=\"{% url 'schedule_plans' %}\"",text)
    def test_expiry_empty_state(self):self.assertIn('{% if expired_count %}',(ROOT/'templates/coordination/waitlist.html').read_text())
    def test_plan_shows_real_offer_expiry(self):self.assertIn('r.offer.expires_at',(ROOT/'templates/coordination/plan.html').read_text())
    def test_accepted_offer_has_history_label(self):self.assertIn('原邀约截止（历史信息）',(ROOT/'templates/coordination/waitlist.html').read_text())
    def test_account_management_not_modeladmin(self):
        s=(ROOT/'accounts/governance.py').read_text();self.assertIn('require_technical',s);self.assertNotIn('admin.site',s)
    def test_no_password_fields_in_success_templates(self):
        for f in ('manage_list.html','manage_detail.html'):
            self.assertNotIn('.password',(ROOT/'templates/accounts'/f).read_text())
    def test_sensitive_fields_decorated(self):self.assertIn('@sensitive_post_parameters',(ROOT/'accounts/governance_views.py').read_text())
    def test_target_state_and_authority_rechecked(self):
        s=(ROOT/'accounts/governance.py').read_text();self.assertIn('verify_target(actor,target,token)',s);self.assertIn('check_password(operator_password)',s)
    def test_no_dangerous_seed_on_patch(self):
        s=(ROOT/'accounts/governance.py').read_text();self.assertNotIn('flush',s);self.assertNotIn('raw_password',s)
    def test_new_route_names_in_gateway(self):
        s=(ROOT/'workspaces/middleware.py').read_text()
        for n in ('account_manage_list','account_manage_detail','account_manage_create','account_manage_change','own_password_change'):self.assertIn(n,s)
    def test_every_admin_post_has_workspace_and_csrf(self):
        s=(ROOT/'templates/accounts/manage_form.html').read_text();self.assertIn('{% workspace_token %}',s);self.assertIn('{% csrf_token %}',s)
    def test_stable_context_gateway_not_removed(self):
        s=(ROOT/'workspaces/middleware.py').read_text();self.assertIn('check_token',s);self.assertIn('valid_context',s)

class GuideScopeTests(unittest.TestCase):
    def test_recording_and_closing_are_separate(self):
        from guidance.catalog import GUIDES
        self.assertIn('doctor-close',GUIDES)
        self.assertNotIn('生成结算单',GUIDES['doctor-care'].title)
    def test_billing_maps_to_close_guide(self):
        from guidance.catalog import choose_guide
        self.assertEqual(choose_guide('DENTIST','billing_policy'),'doctor-close')
    def test_care_maps_to_recording_guide(self):
        from guidance.catalog import choose_guide
        self.assertEqual(choose_guide('DENTIST','care_help'),'doctor-care')
    def test_guide_session_checks_catalog_version(self):
        self.assertIn("state.get('catalog_version')!=VERSION",(ROOT/'guidance/context.py').read_text())
