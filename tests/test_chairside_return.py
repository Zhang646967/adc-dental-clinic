"""An appointed return is traced through chairside, patient web and native HTTP."""
from datetime import timedelta

from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from care.models import Invoice, VisitRecordVersion
from care.services import complete_visit, review_allergies
from clinical.examination_models import ExaminationNotice
from clinical.plan_models import PerformedProcedure, PlanAppointment
from clinical.return_visits import chairside_sources
from finance.cash_models import CashEntry
from portal import rescheduling, services
from registry.models import Allergy
from scheduling.models import Visit
from tests.test_examination_followup import ReportFollowupFixture


class ChairsideFixture(ReportFollowupFixture):
    def supplement_chart(self):
        from clinical import encounters
        from uuid import uuid4
        head = self.v.clinical_encounter
        head.refresh_from_db()
        head, _ = encounters.change_draft(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision,
            operation_id=uuid4(), action='BEGIN_AMEND', fields={'reason':'补记已核对的牙位与牙面'})
        encounters.change_draft(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision,
            operation_id=uuid4(), action='ADD_FINDING', fields=dict(tooth=16, surface='MO',
            kind='EXISTING_WORK', detail='合成样本的原检查位置'))
        prepared = encounters.prepare_record(actor=self.doc, visit_id=self.v.pk)
        return encounters.confirm_record(actor=self.doc, proposal_token=prepared['proposal_token'], confirmed=True)[0]

    def linked_return(self, order, *, hours=2):
        return services.confirm_booking(actor=self.patient_user, token=self.scoped_preview(order, hours=hours),
                                        require_published_service=True)

    def staged_return(self):
        self.supplement_chart()
        plan = self.new_plan(charge_basis='ON_COMPLETION', description='复核阶段修复', goal='在复诊时复核原定阶段')
        step = self.publish_plan(plan).steps.get()
        self.decision(step)
        allergy = Allergy.objects.create(code='RETURN-TEST', name='合成材料甲')
        self.v.refresh_from_db()
        review_allergies(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version,
                         patient_version=self.v.patient.allergy_info_version, status='KNOWN', allergy_ids=[allergy.pk])
        self.actual(step, progress='PARTIAL', charge_mode='NO_CHARGE', reason='上次仅完成第一阶段')
        order = self.release(self.open_order('复诊依据'), kind='NONE', body='初版检查摘要')
        order = self.release(order, reason='更正所见', body='已核对的第二版检查摘要',
                             step_version=step.pk, completion_rule='STEP_COMPLETED')
        self.v.refresh_from_db()
        complete_visit(actor=self.doc, visit_id=self.v.pk, expected_version=self.v.lock_version, outcome='TREATED')
        self.v.refresh_from_db()
        return order, self.linked_return(order)

    def rebook(self, visit, *, hours=3):
        proposed = rescheduling.prepare(actor=self.patient_user, visit_id=visit.pk, expected_version=visit.lock_version, slot_id=self.slot1.pk,
                                        start=self.t+timedelta(hours=hours), reason='调整复诊时间')
        return rescheduling.confirm(actor=self.patient_user, visit_id=visit.pk,
                                    proposal_token=proposed['proposal_token'], confirmed=True)[0]

    def business_counts(self):
        return (Visit.objects.count(), PlanAppointment.objects.count(), PerformedProcedure.objects.count(),
                Invoice.objects.count(), CashEntry.objects.count(), VisitRecordVersion.objects.count(),
                ExaminationNotice.objects.filter(read_at__isnull=False).count())


@override_settings(ADC_CLINICAL_SYNTHETIC=True)
class ChairsideReturnTests(ChairsideFixture, TransactionTestCase):
    def setUp(self):
        self.setup_examinations()

    def rows(self, visit, client=None):
        response = (client or self.mini).get(reverse('mini_visit', args=[visit.pk]))
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['data']['review']['return_sources']

    def test_exact_return_cross_client_and_read_only(self):
        order, visit = self.staged_return()
        self.arrive(visit)
        before = self.business_counts()
        doctor = self.web_client(self.doc).get(reverse('care_workspace', args=[visit.pk]))
        for value in ['本次复诊交接', '16 牙 · 近中面、咬合面', '步骤尚待继续', '合成材料甲', '本次仍需复核',
                      self.v.visit_no, '原检查记录中的牙位', '既往处置', '已核对的第二版检查摘要']:
            self.assertContains(doctor, value)
        patient = self.web.get(reverse('portal_visit', args=[visit.pk]))
        native = self.rows(visit)
        self.assertEqual(native, patient.context['review']['return_sources'])
        self.assertEqual(native, [dict(source_visit_id=self.v.pk, source_visit_no=self.v.visit_no, service=self.service.patient_presentation.title,
            state='CURRENT', label='已关联原就诊', report=dict(id=order.pk, number=order.number,
            revision=2, project=order.project_name))])
        for value in ('合成材料甲', '16 牙', '步骤尚待继续', '已核对的第二版检查摘要'):
            self.assertNotContains(patient, value)
        source_url = reverse('portal_examination', args=[self.v.pk, order.pk])
        self.assertContains(self.web.get(source_url, {'revision':2, 'from_visit':visit.pk}), '返回这次复诊')
        self.assertNotContains(self.web.get(source_url, {'revision':2, 'from_visit':self.v.pk}), '返回这次复诊')
        self.assertEqual(self.business_counts(), before)

    def test_reschedule_carries_link_ordinary_booking_has_none(self):
        order = self.release(self.open_order())
        first = self.linked_return(order)
        latest = self.rebook(first)
        self.assertFalse(self.rows(first))
        self.assertEqual(self.rows(latest)[0]['source_visit_id'], self.v.pk)
        unrelated = self.booking(start=self.t+timedelta(hours=4))
        self.assertFalse(self.rows(unrelated))
        self.assertFalse(self.rows(self.v))

    def test_corrected_then_withdrawn_and_preserved_appointment(self):
        order = self.release(self.open_order())
        visit = self.linked_return(order)
        self.release(order, kind='NONE', body='新依据', reason='变更后的报告')
        before = self.business_counts()
        for action in ('corrected', 'withdrawn'):
            if action == 'withdrawn':
                self.step(order, 'WITHDRAW', reason='撤回本次发布')
            item, = self.rows(visit)
            self.assertEqual((item['state'], item['report']), ('CONTACT', None))
            self.assertContains(self.web.get(reverse('portal_visit', args=[visit.pk])), '复诊依据有变化')
            self.assertEqual(self.web.get(reverse('portal_examination', args=[self.v.pk, order.pk]),
                                          {'revision':1}).status_code, 404)
        visit.refresh_from_db()
        self.assertEqual(visit.status, 'SCHEDULED')
        self.assertEqual(self.business_counts(), before)

    def test_plan_source_without_report_and_new_plan_version(self):
        plan = self.new_plan()
        step = self.publish_plan(plan).steps.get()
        instruction = self.instruction(step_version=step.pk)
        visit = self.book_followup(instruction)
        item, = self.rows(visit)
        self.assertEqual((item['state'], item['report']), ('CURRENT', None))
        self.command(plan, 'BEGIN_AMEND', reason='需要重新讨论步骤')
        self.command(plan, 'NOTES', summary='更新本阶段安排')
        self.publish_plan(plan)
        self.assertEqual(self.rows(visit)[0]['state'], 'CONTACT')

    def test_chart_change_rechecks_without_substituting_new_version(self):
        from clinical import encounters
        from uuid import uuid4
        order = self.release(self.open_order())
        visit = self.linked_return(order)
        head = self.v.clinical_encounter
        head.refresh_from_db()
        encounters.change_draft(actor=self.doc, visit_id=self.v.pk, expected_revision=head.revision,
                                operation_id=uuid4(), action='BEGIN_AMEND', fields={'reason':'更正已确认的检查内容'})
        prepared = encounters.prepare_record(actor=self.doc, visit_id=self.v.pk)
        encounters.confirm_record(actor=self.doc, proposal_token=prepared['proposal_token'], confirmed=True)
        self.assertEqual(self.rows(visit)[0]['state'], 'CONTACT')
        doctor = self.web_client(self.doc).get(reverse('care_workspace', args=[visit.pk]))
        self.assertContains(doctor, '原检查已更新至第 2 版')

    def test_multiple_sources_stay_separate(self):
        first = self.instruction()
        visit = self.book_followup(first)
        another = self.instruction()
        from clinical import next_visits
        proposal = next_visits.prepare_link(actor=self.front, instruction_id=another.pk, visit_id=visit.pk)
        next_visits.confirm_link(actor=self.front, proposal_token=proposal['proposal_token'], confirmed=True)
        self.assertEqual(len(self.rows(visit)), 2)

    def test_role_boundaries(self):
        from clinical.models import ProfessionalAuthorization
        order = self.release(self.open_order())
        visit = self.linked_return(order)
        delegate, _, grant = self.create_delegate()
        client = self.mini_client(delegate)
        session = client.get(reverse('mini_session')).json()['data']
        response = client.post(reverse('mini_subject_select'), {'subject': f'grant:{grant.pk}'},
            HTTP_X_CSRFTOKEN=session['csrf_token'], HTTP_X_ADC_WORKSPACE=session['workspace_token'],
            HTTP_X_ADC_ACCOUNT=str(delegate.pk))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.rows(visit, client), [])
        other = self.create_other()
        self.assertEqual(self.mini_client(other).get(reverse('mini_visit', args=[visit.pk])).status_code, 404)
        self.assertEqual(self.front_web.get(reverse('care_workspace', args=[visit.pk])).status_code, 403)
        self.assertEqual(self.web_client(self.reviewer).get(reverse('care_workspace', args=[visit.pk])).status_code, 403)
        self.assertNotContains(self.front_web.get(reverse('visit_detail', args=[visit.pk])), order.number)
        ProfessionalAuthorization.objects.filter(user=self.doc).update(state='REVOKED')
        doctor = self.web_client(self.doc).get(reverse('care_workspace', args=[visit.pk]))
        self.assertNotContains(doctor, order.number, status_code=doctor.status_code)
        self.assertFalse(chairside_sources(self.doc, visit))
