"""Cross-role handoff. All command, permission, concurrency and cost checks use PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from adc_core.rules import RuleError
from care.services import complete_visit
from clinical import recall, recall_reviews
from clinical.continuity_models import RecallEpisode, RecallEvent
from clinical.continuity_selectors import recall_instructions, recall_page_rows
from clinical.examination_followup import current_decision
from clinical.plan_models import NextVisitInstruction
from clinical.recall_worklist import available_instructions, front_page
from portal.patient_dashboard import ordinary_followup
from portal.policies import patient_access
from tests.test_chairside_return import ChairsideFixture
from tests.test_recall_laboratory import ContinuityFixture


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class RecallHandoffTests(ChairsideFixture, ContinuityFixture, TransactionTestCase):
    def setUp(self):
        self.setup_examinations()
        self.followup_number = 0

    def close_origin(self):
        self.v.refresh_from_db()
        complete_visit(actor=self.doc,visit_id=self.v.pk,expected_version=self.v.lock_version,
            outcome='NO_TREATMENT', reason='已完成合成检查')

    def test_ordinary_due_beijing_boundary_and_role_specific_navigation(self):
        now=timezone.now()
        today=timezone.localdate(now)
        first=self.instruction(earliest_on=today-timedelta(days=1),latest_on=today-timedelta(days=1))
        boundary=self.instruction(earliest_on=today,latest_on=today)
        future=self.instruction(earliest_on=today+timedelta(days=2),latest_on=today+timedelta(days=3))
        self.close_origin()
        action=self.mini.get(reverse('mini_overview')).json()['data']['primary_action']
        self.assertEqual((action['kind'],action['followup']),('VISIT_FOLLOWUP',{'visit_id':self.v.pk,'instruction_id':first.pk}))
        self.assertContains(self.web.get(reverse('portal_home')),reverse('portal_visit',args=[self.v.pk])+'#followup-'+str(first.pk))
        response=self.web.get(reverse('portal_visit',args=[self.v.pk]))
        for item in (first,boundary,future):
            self.assertContains(response,'id="followup-'+str(item.pk)+'"')
        self.assertEqual(list(recall_instructions(self.front,'past_unbooked').values_list('pk',flat=True)),[first.pk])
        self.v.refresh_from_db()
        before=self.v.lock_version
        self.open_recall(future)
        self.assertIn(future,recall_instructions(self.front,'mine'))
        self.v.refresh_from_db()
        self.assertEqual(self.v.lock_version,before)
        delegate,_,grant=self.create_delegate()
        from portal.relationships import select_subject
        self.ctx(delegate,'PATIENT')
        select_subject(actor=delegate,key='grant:'+str(grant.pk))
        self.assertIsNone(ordinary_followup(patient_access(delegate),now))
        self.assertEqual(self.mini_client(self.create_other()).get(reverse('mini_visit',args=[self.v.pk])).status_code,404)

    def test_paused_patient_internal_decision_requires_exact_source_and_current_version(self):
        row=self.instruction()
        ep=self.recall_action(self.open_recall(row),'CONTACT',outcome='DECLINED')
        self.close_origin()
        self.assertNotIn(row, recall_instructions(self.front,'mine'))
        self.assertIn(row, recall_instructions(self.front,'review'))
        self.assertEqual(self.mini.get(reverse('mini_overview')).json()['data']['primary_action']['kind'],'BOOK')
        self.assertContains(self.web.get(reverse('portal_visit',args=[self.v.pk])),'复诊安排已暂缓')
        url=reverse('clinical_dentist_recall',args=[row.pk]); staff=self.web_client(self.doc)
        before=RecallEvent.objects.count()
        detail=staff.get(url)
        self.assertEqual(detail.status_code,200)
        self.assertContains(staff.get(reverse('clinical_dentist_recalls')),url)
        self.assertEqual(RecallEvent.objects.count(),before)
        self.assertEqual(self.web_client(self.reviewer).get(url).status_code,404)
        self.assertEqual(self.front_web.get(url).status_code,403)
        params=dict(phase='preview',decision='HOLD',note='PRIVATE_DOCTOR_ONLY',patient_binding=detail.context['form'].initial['patient_binding'])
        preview=staff.post(url,params)
        self.assertContains(preview,'继续暂缓，由患者主动联系')
        post=dict(phase='confirm',confirmed='on',proposal_token=preview.context['form'].initial['proposal_token'])
        self.assertEqual(staff.post(url,post).status_code,302)
        self.assertEqual(staff.post(url,post).status_code,302)
        self.assertEqual(RecallEvent.objects.count(),before+1)
        ep.refresh_from_db()
        self.assertEqual(ep.state,'REVIEW')
        self.assertNotIn(row,recall_reviews.queue(self.doc))
        self.assertIn(row,recall_reviews.queue(self.doc,True))
        desk=self.front_web.get(reverse('clinical_recall_detail',args=[ep.pk]))
        self.assertContains(desk,'继续暂缓');self.assertNotContains(desk,'PRIVATE_DOCTOR_ONLY')
        self.assertNotContains(self.web.get(reverse('portal_visit',args=[self.v.pk])),'PRIVATE_DOCTOR_ONLY')
        self.recall_action(ep,'RESUME',note='本人主动确认继续安排')
        self.recall_action(ep,'CONTACT',outcome='DECLINED')
        self.assertIn(row,recall_reviews.queue(self.doc))
        self.assertNotIn(row,recall_reviews.queue(self.doc,True))
        again=self.mini.get(reverse('mini_overview')).json()['data']['primary_action']
        self.assertEqual(again['kind'],'BOOK')

    def test_report_has_priority_and_pause_removes_only_its_own_prompt(self):
        ordinary=self.instruction()
        order=self.release(self.open_order())
        report=current_decision(order).instruction
        self.close_origin()
        action=lambda:self.mini.get(reverse('mini_overview')).json()['data']['primary_action']
        self.assertEqual(action()['kind'],'REPORT_FOLLOWUP')
        self.recall_action(self.open_recall(report),'CONTACT',outcome='DECLINED')
        self.assertEqual(action()['followup']['instruction_id'],ordinary.pk)
        self.assertEqual(self.report(order)['followup']['action'],'CONTACT')
        self.assertIn('暂缓',self.report(order)['followup']['message'])
        self.recall_action(self.open_recall(ordinary),'CONTACT',outcome='DECLINED')
        self.assertEqual(action()['kind'],'BOOK')

    def test_two_claims_no_answer_and_stale_appointment(self):
        row=self.instruction()
        due=timezone.now()+timedelta(minutes=6)
        actors=[self.front,self.front2]
        tokens=[recall.prepare_recall(actor=u,action='OPEN',instruction_id=row.pk,fields={'followup_due_at':due})['proposal_token'] for u in actors]
        gate=Barrier(2)
        def claim(pair):
            user,token=pair
            close_old_connections()
            try:
                gate.wait(timeout=10)
                recall.confirm_recall(actor=user,proposal_token=token,confirmed=True)
                return True
            except RuleError:
                return False
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(claim,zip(actors,tokens)))
        self.assertEqual(outcomes.count(True),1)
        actor=actors[outcomes.index(True)]; ep=RecallEpisode.objects.get(instruction=row)
        self.assertEqual(ep.owner_id,actor.pk)
        self.recall_action(ep,'CONTACT',actor=actor,outcome='NO_ANSWER',followup_due_at=timezone.now()+timedelta(days=1))
        self.assertNotIn(row,recall_instructions(actor,'mine'))
        self.assertIn(row,recall_instructions(actor,'later'))
        v=self.scheduled_followup(row)
        fields=dict(note='合成联系备注',outcome='NO_ANSWER',followup_due_at=timezone.now()+timedelta(days=2))
        stale=recall.prepare_recall(actor=actor,action='CONTACT',episode_id=ep.pk,fields=fields)
        self.rebook(v,hours=3)
        with self.assertRaisesMessage(RuleError,'关联预约已有变化'):
            recall.confirm_recall(actor=actor,proposal_token=stale['proposal_token'],confirmed=True)
        self.assertEqual(ep.events.filter(action='CONTACT').count(),1)

    def test_review_rechecks_record_permission_after_preview(self):
        row=self.instruction()
        self.recall_action(self.open_recall(row),'CONTACT',outcome='DECLINED')
        q=recall_reviews.prepare(actor=self.doc,instruction_id=row.pk,decision='COORDINATE',note='内部确认')
        from clinical.models import ProfessionalAuthorization
        scope=ProfessionalAuthorization.objects.get(user=self.doc,clinic=self.a,service=self.service,state='APPROVED')
        with patch.object(timezone,'now',return_value=scope.valid_until+timedelta(seconds=1)):
            with self.assertRaises((PermissionDenied,RuleError)):
                recall_reviews.confirm(actor=self.doc,proposal_token=q['proposal_token'],confirmed=True)
        self.assertFalse(RecallEvent.objects.filter(action='DENTIST_REVIEW').exists())

    def test_page_and_count_do_not_scale_with_the_number_of_instructions(self):
        row=self.instruction(earliest_on=timezone.localdate()-timedelta(days=2),latest_on=timezone.localdate()-timedelta(days=1))
        def grow(n):
            fields=('source_record_id','service_id','earliest_on','latest_on','clinical_purpose','completion_rule','recorded_by_id')
            NextVisitInstruction.objects.bulk_create([NextVisitInstruction(**{f:getattr(row,f) for f in fields}) for _ in range(n)])
        counts=[]
        for extra,total in [(19,20),(180,200)]:
            grow(extra)
            with CaptureQueriesContext(connection) as queries:
                qs=front_page(recall_instructions(self.front,'past_unbooked'))
                self.assertEqual(qs.count(),total)
                self.assertEqual(len(list(recall_page_rows(qs[:20]))),20)
            counts.append(len(queries))
        self.assertEqual(*counts)

    def test_completed_evidence_and_unrelated_visits_do_not_change_each_others_goals(self):
        covered=self.instruction()
        other=self.instruction()
        visit=self.scheduled_followup(covered)
        selected=lambda:set(available_instructions(NextVisitInstruction.objects.all()).values_list('pk',flat=True))
        self.assertEqual(selected(),{other.pk})
        self.close_followup(visit)
        self.assertTrue(recall.completion_candidates(covered))
        self.assertEqual(selected(),{other.pk})
