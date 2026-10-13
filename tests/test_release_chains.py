"""Cross-module PostgreSQL acceptance definitions for the frozen RC.
Fixture identities are synthetic setup, not evidence that every UI route works.
Actual execution status lives in docs/TEST_REPORT.md.
"""
from datetime import datetime,timedelta,date,timezone as dtz
from decimal import Decimal as D
from unittest.mock import patch
from django.db import connection
from django.test import TransactionTestCase
from django.utils import timezone
from django.urls import reverse
from tests.test_v05 import V05Fixture
from tests.fixtures import FixtureMixin
from workspaces.models import WorkspaceContext
from care.models import Invoice
from care.corrections import request_line_correction,review_correction
from finance.selectors import quarter_report
from finance import services as fs
from operations.selectors import operation_report
from scheduling.services import change_appointment
from scheduling.intake_services import inspect_intake,prepare_intake,confirm_intake
from scheduling.availability_services import inspect_availability,prepare_availability_change,confirm_availability_change
from coordination.task_services import inspect_task,prepare_task,confirm_task
from coordination.task_rules import ACTION_REASONS
from coordination.models import CoordinationTask
from notifications.models import NotificationOutbox,InboxMessage
from notifications.dispatcher import dispatch_batch


def activate(actor,role,clinic=None):
    actor._adc_workspace=WorkspaceContext.objects.create(user=actor,role=role,clinic=clinic,revision=1)


class ReleaseFinancialChainTests(V05Fixture,TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql')
        self.clock=patch('django.utils.timezone.now',return_value=datetime(2031,5,12,2,tzinfo=dtz.utc))
        self.clock.start();self.addCleanup(self.clock.stop);self.setup05()
        for actor,role,clinic in ((self.front,'FRONT_DESK',self.a),(self.doctor,'DENTIST',None),
                                   (self.fin,'FINANCE',None),(self.hq,'HQ',None),(self.manager,'MANAGER',self.a)):
            activate(actor,role,clinic)
    def costs(self):
        q=self.make_quarter()
        for dentist,a,b in ((self.d1,'10','20'),(self.d2,'50','50')):
            c=self.member(q,dentist);self.savecost(q,c,a,b);self.confirmcost(q,c)
        self.roster(q);return q
    def test_service_chain_bill_catalogue_correction_and_quarter_restatement(self):
        v,invoice=self.billed();original=invoice.current_record_version
        self.assertEqual(original.total_amount,D('199.98'))
        q=self.costs();before=quarter_report(self.fin,q.pk)
        self.assertEqual((before.result.income,before.result.profit,before.result.fund),(D('199.98'),D('69.98'),D('7.00')))
        # Catalogue change is fixture setup. Historical line price must not follow it.
        self.service.standard_unit_price=D('250');self.service.save(update_fields=['standard_unit_price'])
        invoice.refresh_from_db();self.assertEqual(invoice.current_record_version.total_amount,D('199.98'))
        v.refresh_from_db();line=original.treatment_lines.get()
        req=request_line_correction(actor=self.doctor,visit_id=v.pk,expected_version=v.lock_version,
            line_id=line.pk,quantity=D('1'),unit_price=D('99.99'),reason='合成演示：数量误录更正')
        review_correction(actor=self.fin,request_id=req.pk,decision='approve',reason='合成演示：独立核对')
        after=quarter_report(self.fin,q.pk)
        self.assertEqual((after.result.income,after.result.profit,after.result.fund),(D('99.99'),D('-30.01'),None))
        original.refresh_from_db();self.assertEqual(original.total_amount,D('199.98'))
        self.assertEqual(Invoice.objects.filter(visit=v).count(),1)
    def test_selector_missing_cost_then_confirmed_zero(self):
        self.billed();q=self.make_quarter();c=self.member(q);self.roster(q)
        self.assertFalse(quarter_report(self.fin,q.pk).result.ready)
        self.savecost(q,c,'0','0');self.confirmcost(q,c)
        r=quarter_report(self.fin,q.pk);self.assertTrue(r.result.ready)
        self.assertEqual(r.result.profit,D('199.98'));self.assertEqual(r.result.fund,D('20.00'))
    def test_real_selector_maturity_and_cancellation_party(self):
        a=self.book();b=self.book(patient_no=self.p2.patient_no,start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2))
        change_appointment(actor=self.front,visit_id=a.pk,expected_version=0,action='cancel',party='PATIENT',reason='合成本人取消')
        change_appointment(actor=self.front,visit_id=b.pk,expected_version=0,action='cancel',party='CLINIC',reason='合成诊所取消')
        # Before end: future rows do not enter the denominator.
        day=self.t.astimezone(timezone.get_current_timezone()).date()
        self.assertEqual(operation_report(self.manager,day,day,self.a.pk)['metrics'].denominator,0)
        with patch('django.utils.timezone.now',return_value=self.t+timedelta(hours=5)):
            r=operation_report(self.manager,day,day,self.a.pk)
        self.assertEqual((r['metrics'].denominator,r['metrics'].cancel_rate,r['metrics'].clinic_cancel),(1,D('100.00'),1))
    def test_postgres_income_quarter_boundary(self):
        from care.ledger import income_by_dentist
        from adc_core.snapshots import reporting_snapshot
        from adc_core.rules import quarter_bounds
        # Book under the fixture clock, then close visits across the UTC+8 boundary.
        v=self.arrived();self.review(v);self.line(v,D('2'))
        with patch('django.utils.timezone.now',return_value=datetime(2031,6,30,15,59,59,tzinfo=dtz.utc)):
            self.finish(v)
        second=self.book(patient_no=self.p2.patient_no,start=self.t+timedelta(hours=1),end=self.t+timedelta(hours=2))
        second=change_appointment(actor=self.front,visit_id=second.pk,expected_version=0,action='check_in')
        self.review(second);self.line(second,D('2'))
        with patch('django.utils.timezone.now',return_value=datetime(2031,6,30,16,0,0,tzinfo=dtz.utc)):
            self.finish(second)
        asof=datetime(2031,7,2,tzinfo=dtz.utc)
        with reporting_snapshot():
            q2=income_by_dentist(*quarter_bounds(2031,2),asof);q3=income_by_dentist(*quarter_bounds(2031,3),asof)
        self.assertEqual(sum(r.amount for r in q2),D('199.98'))
        self.assertEqual(sum(r.amount for r in q3),D('199.98'))



class ReleaseCoordinationChainTests(FixtureMixin,TransactionTestCase):
    def setUp(self):
        self.assertEqual(connection.vendor,'postgresql');self.make_fixture()
        activate(self.manager,'MANAGER',self.a);activate(self.front,'FRONT_DESK',self.a)
    def task(self,actor,action,t=None):
        _,s=inspect_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None)
        p=prepare_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None,state_token=s,
            action=action,reason=ACTION_REASONS[action][0],purpose='DEACTIVATE' if action=='open' else '')
        result=confirm_task(actor=actor,slot_id=self.slot1.pk,task_id=t.pk if t else None,
            proposal_token=p['proposal_token'],confirmed=True)
        return CoordinationTask.objects.get(pk=result.task_id)
    def pause(self):
        _,s=inspect_intake(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_intake(actor=self.manager,slot_id=self.slot1.pk,state_token=s,action='pause',reason='COORDINATION')
        confirm_intake(actor=self.manager,slot_id=self.slot1.pk,proposal_token=p['proposal_token'],confirmed=True)
    def test_pause_task_real_cancellation_notifications_review_and_deactivate(self):
        visit=self.book();self.pause();task=self.task(self.manager,'open')
        self.assertTrue(NotificationOutbox.objects.exists());self.assertFalse(InboxMessage.objects.exists())
        dispatch_batch(25);self.assertTrue(InboxMessage.objects.filter(recipient=self.front).exists())
        task=self.task(self.front,'claim',task)
        # Original appointment service, not a "mark done" shortcut.
        change_appointment(actor=self.front,visit_id=visit.pk,expected_version=0,action='cancel',
            party='PATIENT',reason='合成场景：已单独核对患者取消意愿')
        task=self.task(self.front,'submit',task);task=self.task(self.manager,'approve',task)
        self.assertEqual(task.state,'CLOSED');self.slot1.refresh_from_db();self.assertTrue(self.slot1.is_active)
        _,s=inspect_availability(actor=self.manager,slot_id=self.slot1.pk)
        p=prepare_availability_change(actor=self.manager,slot_id=self.slot1.pk,state_token=s,
            action='deactivate',reason_code='PLAN_CHANGED')
        confirm_availability_change(actor=self.manager,slot_id=self.slot1.pk,proposal_token=p.proposal_token,confirmed=True)
        self.slot1.refresh_from_db();self.assertFalse(self.slot1.is_active)
        visit.refresh_from_db();self.assertEqual(visit.status,'CANCELLED')
        dispatch_batch(25);n=InboxMessage.objects.count();dispatch_batch(25);self.assertEqual(InboxMessage.objects.count(),n)
    def test_task_cannot_replace_real_booking_resolution(self):
        from adc_core.rules import RuleError
        visit=self.book();self.pause();task=self.task(self.manager,'open');task=self.task(self.front,'claim',task)
        with self.assertRaises(RuleError):self.task(self.front,'submit',task)
        visit.refresh_from_db();self.assertEqual(visit.status,'SCHEDULED')
    def test_message_generation_does_not_claim_task(self):
        self.pause();task=self.task(self.manager,'open');dispatch_batch(25)
        task.refresh_from_db();self.assertEqual(task.state,'OPEN');self.assertIsNone(task.assignee_id)
