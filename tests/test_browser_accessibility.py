"""Rendered-page regressions for failures observed during real G3 browser use."""
from collections import Counter
from html.parser import HTMLParser

from django.db import connection
from django.test import TransactionTestCase
from django.urls import reverse

from accounts.models import UserAccount, RoleAssignment
from care.models import TreatmentRecord
from finance.models import Quarter, DentistQuarterCost
from coordination.task_rules import ACTION_REASONS
from coordination.task_services import inspect_task, prepare_task, confirm_task
from tests.fixtures import FixtureMixin
from tests.test_v04 import V04Fixture
from workspaces.models import WorkspaceContext


class FormMarkup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.inputs = {}
        self.labels = []
        self.current_label = None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.ids.append(attrs['id'])
        if tag == 'input' and attrs.get('id'):
            self.inputs[attrs['id']] = attrs
        if tag == 'label':
            self.current_label = (attrs.get('for'), [])

    def handle_data(self, data):
        if self.current_label:
            self.current_label[1].append(data)

    def handle_endtag(self, tag):
        if tag == 'label' and self.current_label:
            target, text = self.current_label
            self.labels.append((target, ''.join(text)))
            self.current_label = None


class CareFormAccessibilityTests(V04Fixture, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.set_up_v04()
        self.visit = self.arrived()
        self.client.force_login(self.doctor)
        self.url = reverse('care_workspace', args=[self.visit.pk])

    def test_confirmation_labels_target_distinct_checkboxes_and_ids_are_unique(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        markup = FormMarkup(response.content.decode())
        self.assertEqual([key for key, count in Counter(markup.ids).items() if count > 1], [])
        targets = []
        for text in ('我已向患者复核上述信息', '我确认该项目已经实际提供'):
            labels = [(target, label) for target, label in markup.labels if text in label]
            self.assertEqual(len(labels), 1)
            target = labels[0][0]
            self.assertEqual(markup.inputs[target]['type'], 'checkbox')
            self.assertEqual(markup.inputs[target]['name'], 'confirmed')
            targets.append(target)
        self.assertNotEqual(*targets)

    def test_independent_confirmations_keep_native_post_names_and_version_checks(self):
        response = self.client.post(self.url, {
            'action': 'review', 'expected_version': self.visit.lock_version,
            'patient_version': self.p1.allergy_info_version,
            'status': 'UNKNOWN', 'confirmed': 'on',
        })
        self.assertEqual(response.status_code, 302)
        self.visit.refresh_from_db()
        data = {
            'action': 'add', 'expected_version': self.visit.lock_version,
            'treatment_id': self.service.pk, 'quantity': '2',
        }
        response = self.client.post(self.url, data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(TreatmentRecord.objects.exists())
        response = self.client.post(self.url, data | {'confirmed': 'on'})
        self.assertEqual(response.status_code, 302)
        line = TreatmentRecord.objects.get()
        self.assertEqual(str(line.line_amount), '199.98')
        self.visit.refresh_from_db()
        response = self.client.post(self.url, data | {'confirmed': 'on'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TreatmentRecord.objects.count(), 1)


class FinanceFormAccessibilityTests(V04Fixture, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.set_up_v04()
        self.finance = UserAccount.objects.create_user(username='browser_finance', password='test-only')
        RoleAssignment.objects.create(user=self.finance, role='FINANCE', scope_kind='CHAIN')
        self.quarter = Quarter.objects.create(year=2026, quarter_no=4)
        self.client.force_login(self.finance)
        self.url = reverse('quarter_detail', args=[self.quarter.pk])

    def assert_confirmations(self, response, names):
        self.assertEqual(response.status_code, 200)
        markup = FormMarkup(response.content.decode())
        self.assertEqual([key for key, count in Counter(markup.ids).items() if count > 1], [])
        targets = []
        for name in names:
            labels = [(target, label) for target, label in markup.labels if name in label]
            self.assertEqual(len(labels), 1)
            target = labels[0][0]
            self.assertEqual(markup.inputs[target]['type'], 'checkbox')
            self.assertEqual(markup.inputs[target]['name'], 'confirmed')
            targets.append(target)
        self.assertNotEqual(*targets)

    def test_roster_confirmations_have_unique_ids_and_action_specific_labels(self):
        self.assert_confirmations(self.client.get(self.url), (
            '我已核对本次纳入的牙医及季度',
            '我已核对完整纳入清单，包括有成本但无收入的牙医',
        ))

    def test_cost_draft_and_confirmation_have_unique_ids_and_action_specific_labels(self):
        cost = DentistQuarterCost.objects.create(
            quarter=self.quarter, dentist=self.d1, cost_status='DRAFT',
            supply_cost='0.00', operating_expense='0.00', notes='Synthetic draft',
        )
        url = reverse('quarter_cost', args=[self.quarter.pk, cost.pk])
        self.assert_confirmations(self.client.get(url), (
            '我已核对成本数字及录入依据（保存草稿）',
            '我已核对本条成本，确认将其纳入季度测算',
        ))

    def test_native_names_keep_member_roster_draft_and_cost_confirmation_separate(self):
        data = {'action': 'add', 'expected_version': self.quarter.lock_version, 'dentist_id': self.d1.pk}
        self.assertEqual(self.client.post(self.url, data).status_code, 200)
        self.assertFalse(DentistQuarterCost.objects.exists())
        self.assertEqual(self.client.post(self.url, data | {'confirmed': 'on'}).status_code, 302)
        self.quarter.refresh_from_db()
        self.assertEqual(self.client.post(self.url, {
            'action': 'confirm', 'expected_version': self.quarter.lock_version, 'confirmed': 'on',
        }).status_code, 302)
        self.quarter.refresh_from_db()
        self.assertEqual(self.quarter.roster_status, 'CONFIRMED')
        cost = DentistQuarterCost.objects.get()
        url = reverse('quarter_cost', args=[self.quarter.pk, cost.pk])
        self.assertEqual(self.client.post(url, {
            'action': 'save', 'expected_version': self.quarter.lock_version,
            'supply_cost': '10', 'operating_expense': '20',
            'notes': 'Synthetic browser regression', 'confirmed': 'on',
        }).status_code, 302)
        cost.refresh_from_db()
        self.assertEqual(cost.cost_status, 'DRAFT')
        self.quarter.refresh_from_db()
        self.assertEqual(self.client.post(url, {
            'action': 'confirm', 'expected_version': self.quarter.lock_version, 'confirmed': 'on',
        }).status_code, 302)
        cost.refresh_from_db()
        self.assertEqual(cost.cost_status, 'CONFIRMED')


class PermissionRecoveryTests(V04Fixture, TransactionTestCase):
    def test_denials_offer_safe_recovery_without_exposing_the_target(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.set_up_v04()
        visit = self.arrived()
        cases = (
            (self.front, reverse('front_coordination_detail', args=[self.slot2.pk])),
            (self.tech, reverse('care_workspace', args=[visit.pk])),
        )
        for actor, url in cases:
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                response = self.client.get(url)
                self.assertContains(response, '返回当前工作台', status_code=403)
                self.assertContains(response, 'role="alert"', status_code=403)
                for private_value in (self.p1.name, self.p1.patient_no, self.p2.patient_no,
                                      self.b.postal_address, visit.visit_no):
                    self.assertNotContains(response, private_value, status_code=403)


class TaskStatusWordingTests(FixtureMixin, TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.make_fixture()
        for actor, role in ((self.front, 'FRONT_DESK'), (self.manager, 'MANAGER')):
            actor._adc_workspace = WorkspaceContext.objects.create(
                user=actor, role=role, clinic=self.a, revision=1,
            )
        # Isolated data setup; real browser pause behavior has its own evidence.
        self.slot1.booking_paused = True
        self.slot1.save(update_fields=['booking_paused'])
        self.task_id = None
        self.command(self.manager, 'open')
        self.command(self.front, 'claim')
        self.command(self.front, 'submit')
        self.url = reverse('coordination_task_detail', args=[self.slot1.pk, self.task_id])

    def command(self, actor, action):
        _, state = inspect_task(actor=actor, slot_id=self.slot1.pk, task_id=self.task_id)
        preview = prepare_task(
            actor=actor, slot_id=self.slot1.pk, task_id=self.task_id,
            state_token=state, action=action, reason=ACTION_REASONS[action][0],
            purpose='REPLACE' if action == 'open' else '',
        )
        result = confirm_task(
            actor=actor, slot_id=self.slot1.pk, task_id=self.task_id,
            proposal_token=preview['proposal_token'], confirmed=True,
        )
        self.task_id = result.task_id

    def test_ready_owner_is_guided_to_independent_review_without_finished_wording(self):
        self.client.force_login(self.front)
        response = self.client.get(self.url)
        self.assertContains(response, '待主管复核')
        self.assertContains(response, '已提交主管复核')
        self.assertNotContains(response, '已结束任务保留历史')

    def test_closed_task_retains_finished_history_wording(self):
        self.command(self.manager, 'approve')
        self.client.force_login(self.front)
        response = self.client.get(self.url)
        self.assertContains(response, '协调核对已通过')
        self.assertContains(response, '已结束任务保留历史')
