"""C0.2 HTTP/transaction regressions; require the real Django/PostgreSQL gate."""
from datetime import timedelta
from decimal import Decimal
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from care.models import AuditEvent
from coordination.models import WaitRequest
from coordination.services import withdraw
from portal.models import BookingReceipt
from scheduling.models import Visit
from scheduling.resource_models import BookingService, ServicePresentation, ResourceClaim
from scheduling.resource_config import prepare_config, confirm_config
from scheduling.service_content import presentation_values
from tests import test_mini_program as base
from tests.test_reception_resources import ResourceFixture


class NativeServiceTests(ResourceFixture, TransactionTestCase):
    setUp = base.MiniProgramTests.setUp
    login = base.MiniProgramTests.login
    post = base.MiniProgramTests.post
    preview = base.MiniProgramTests.preview
    book = base.MiniProgramTests.book

    def content_change(self, **changes):
        self.profile.refresh_from_db()
        fields = dict(presentation_values(self.profile), service=self.service.pk, **changes)
        prepared = prepare_config(actor=self.manager, kind='service_profile', fields=fields, target=self.profile.pk)
        return confirm_config(actor=self.manager, proposal_token=prepared['proposal_token'], confirmed=True)

    def catalogue(self):
        return self.client.get(reverse('mini_catalogue')).json()['data']

    def join_preview(self):
        return self.post('mini_wait_join_preview', dict(clinic=self.a.pk, service=self.service.pk,
            earliest=self.t.isoformat(), latest=(self.t+timedelta(hours=8)).isoformat()))

    def test_detail_is_authenticated_and_private(self):
        response = Client().get(reverse('mini_service', kwargs={'pk': self.service.pk}))
        self.assertEqual(response.status_code, 401)
        response = self.client.get(reverse('mini_service', kwargs={'pk': self.service.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_catalogue_shares_published_projection_with_website(self):
        from portal.service_catalogue import public_profiles, public_services
        data = self.catalogue()
        self.assertEqual([r['id'] for r in data['offerings']], [p.service_id for p in public_profiles()])
        self.assertEqual([r['id'] for r in data['services']], list(public_services().values_list('pk', flat=True)))
        self.assertEqual(data['resource_clinics'], [self.a.pk])
        self.assertEqual(data['services'][0]['name'], self.profile.title)
        self.assertEqual(set(data['services'][0]['dentists'][0]), {'id', 'name'})

    def test_unpublished_and_absent_services_have_same_detail_error(self):
        self.profile.is_published = False; self.profile.save()
        first = self.client.get(reverse('mini_service', kwargs={'pk': self.service.pk}))
        second = self.client.get(reverse('mini_service', kwargs={'pk': 99999999}))
        self.assertEqual((first.status_code, second.status_code), (404, 404))
        self.assertEqual(first.json()['message'], second.json()['message'])
        self.assertEqual(self.catalogue()['offerings'], [])

    def test_incomplete_published_content_fails_closed(self):
        ServicePresentation.objects.filter(pk=self.profile.pk).update(summary='')
        self.assertEqual(self.catalogue()['offerings'], [])
        self.assertEqual(self.client.get(reverse('mini_service', kwargs={'pk': self.service.pk})).status_code, 404)

    def test_active_service_without_profile_is_not_advertised(self):
        second = BookingService.objects.create(department=self.department, code='DRAFT', name='未发布服务', duration_minutes=30)
        second.dentists.set([self.d1])
        self.assertNotIn(second.pk, [r['id'] for r in self.catalogue()['offerings']])

    def test_disabled_operational_service_is_hidden(self):
        for obj, field, value in [(self.a, 'is_active', False), (self.department, 'is_active', False),
                (self.service, 'is_active', False), (self.policy, 'state', 'PREPARING')]:
            with self.subTest(model=type(obj).__name__):
                original = getattr(obj, field); setattr(obj, field, value); obj.save()
                self.assertEqual(self.catalogue()['offerings'], [])
                setattr(obj, field, original); obj.save()

    def test_no_active_receiving_dentists_is_hidden(self):
        self.service.dentists.clear()
        self.assertEqual(self.catalogue()['offerings'], [])

    def test_child_service_visible_but_no_native_self_booking_or_waitlist(self):
        self.content_change(category='CHILDREN')
        data = self.catalogue()
        self.assertEqual(len(data['offerings']), 1); self.assertEqual(data['services'], [])
        self.assertFalse(data['offerings'][0]['self_booking'])
        self.assertEqual(self.client.get(reverse('mini_candidates'), dict(clinic=self.a.pk,
            service=self.service.pk, day=self.t.date().isoformat())).status_code, 409)
        self.assertEqual(self.post('mini_book_preview', dict(slot=self.slot1.pk,
            service=self.service.pk, start=self.t.isoformat())).status_code, 409)
        self.assertEqual(self.join_preview().status_code, 409)

    def test_assessed_fixed_zero_and_starting_fees_stay_distinct(self):
        for mode, amount, label in [('ASSESSED', None, '评估后确认费用'),
                ('FIXED', Decimal('0.00'), '¥0.00 / 本次服务'), ('FROM', Decimal('99.90'), '¥99.90 起')]:
            with self.subTest(mode=mode):
                self.content_change(fee_mode=mode, fee_amount=amount)
                row = self.catalogue()['offerings'][0]
                self.assertEqual((row['fee_mode'], row['fee_amount'], row['fee_label']),
                    (mode, str(amount) if amount is not None else None, label))

    def test_draft_cannot_start_new_candidate_preview_or_waitlist(self):
        self.content_change(is_published=False)
        self.assertEqual(self.client.get(reverse('mini_candidates'), dict(clinic=self.a.pk,
            service=self.service.pk, day=self.t.date().isoformat())).status_code, 409)
        self.assertEqual(self.post('mini_book_preview', dict(slot=self.slot1.pk,
            service=self.service.pk, start=self.t.isoformat())).status_code, 409)
        self.assertEqual(self.join_preview().status_code, 409)
        self.assertFalse(Visit.objects.exists()); self.assertFalse(WaitRequest.objects.exists())

    def test_missing_service_cannot_fall_back_to_legacy_booking(self):
        self.assertEqual(self.client.get(reverse('mini_candidates'), dict(clinic=self.b.pk,
            day=self.t.date().isoformat())).status_code, 409)
        self.assertEqual(self.post('mini_book_preview', dict(slot=self.slot1.pk,
            start=self.t.isoformat())).status_code, 409)
        response = self.post('mini_wait_join_preview', dict(clinic=self.b.pk,
            earliest=self.t.isoformat(), latest=(self.t+timedelta(hours=1)).isoformat()))
        self.assertEqual(response.status_code, 409)

    def test_signed_request_survives_confirmation_and_raw_edits_are_ignored(self):
        text = '想了解本次检查范围\n近期有不适'
        response = self.post('mini_book_preview', dict(slot=self.slot1.pk, start=self.t.isoformat(),
            service=self.service.pk, patient_request='  '+text+'  '))
        self.assertEqual(response.status_code, 200, response.content)
        p = response.json()['data']
        self.assertEqual((p['patient_request'], p['fee_label'], p['preparation']),
            (text, '评估后确认费用', self.profile.preparation))
        confirmed = self.post('mini_book_confirm', dict(proposal_token=p['proposal_token'], confirmed='on',
            patient_request='被修改的正文', fee_amount='0', service=999999))
        self.assertEqual(confirmed.status_code, 200, confirmed.content)
        visit = Visit.objects.get()
        self.assertEqual(visit.chief_complaint, text)
        detail = self.client.get(reverse('mini_visit', kwargs={'pk': visit.pk})).json()['data']
        self.assertEqual(detail['patient_request'], text)
        self.assertNotIn(text, str(list(AuditEvent.objects.values_list('change_summary', flat=True))))

    def test_patient_request_limit_and_control_characters(self):
        for value in ('字'*501, 'request\x00'):
            with self.subTest(value=value):
                response = self.post('mini_book_preview', dict(slot=self.slot1.pk, start=self.t.isoformat(),
                    service=self.service.pk, patient_request=value))
                self.assertEqual(response.status_code, 409)
        self.assertFalse(Visit.objects.exists())

    def test_content_change_invalidates_new_booking_preview(self):
        token = self.preview()
        self.content_change(fee_mode='FROM', fee_amount=Decimal('99.90'))
        response = self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on'))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Visit.objects.exists()); self.assertFalse(BookingReceipt.objects.exists())

    def test_unpublish_republish_does_not_revive_booking_preview(self):
        token = self.preview()
        self.content_change(is_published=False); self.content_change(is_published=True)
        self.assertEqual(self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on')).status_code, 409)
        self.assertFalse(Visit.objects.exists())

    def test_locked_booking_guard_rejects_direct_unpublish_without_revision(self):
        token = self.preview()
        ServicePresentation.objects.filter(pk=self.profile.pk).update(is_published=False)
        self.assertEqual(self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on')).status_code, 409)
        self.assertFalse(Visit.objects.exists()); self.assertFalse(ResourceClaim.objects.exists())

    def test_successful_booking_replay_after_withdrawal_returns_current_visit(self):
        token = self.preview()
        first = self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on')).json()['data']
        self.post('mini_cancel_confirm', dict(proposal_token=self.post('mini_cancel_preview',
            dict(expected_version=0, reason='行程变化'), pk=first['id']).json()['data']['proposal_token'], confirmed='on'), pk=first['id'])
        self.content_change(is_published=False)
        response = self.post('mini_book_confirm', dict(proposal_token=token, confirmed='on', patient_request='不可覆盖'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['status'], 'CANCELLED')
        self.assertNotEqual(Visit.objects.get().chief_complaint, '不可覆盖')
        self.assertEqual(Visit.objects.count(), 1)

    def test_own_reschedule_projection_survives_publication_withdrawal(self):
        visit = self.book(); self.content_change(is_published=False)
        self.assertEqual(self.catalogue()['offerings'], [])
        response = self.client.get(reverse('mini_visit', kwargs={'pk': visit.pk}))
        data = response.json()['data']
        self.assertEqual(data['reschedule_service']['id'], self.service.pk)
        self.assertEqual(data['reschedule_service']['name'], data['service'])
        self.assertEqual(set(data['reschedule_service']['dentists'][0]), {'id', 'name'})
        candidates = self.client.get(reverse('mini_reschedule_candidates', kwargs={'pk': visit.pk}), dict(day=self.t.date().isoformat()))
        self.assertEqual(candidates.status_code, 200, candidates.content)
        self.assertTrue(candidates.json()['data']['rows'])
        c, _ = self.login(self.other)
        self.assertEqual(c.get(reverse('mini_visit', kwargs={'pk': visit.pk})).status_code, 404)

    def test_withdrawal_does_not_prevent_existing_same_service_reschedule(self):
        visit = self.book(); self.content_change(is_published=False)
        response = self.post('mini_reschedule_preview', dict(action='preview', expected_version=0,
            slot_id=self.slot2.pk, start=(self.t+timedelta(hours=1)).isoformat(), reason='调整时间'), pk=visit.pk)
        self.assertEqual(response.status_code, 200, response.content)
        response = self.post('mini_reschedule_confirm', dict(proposal_token=response.json()['data']['proposal_token'],
            confirmed='on'), pk=visit.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Visit.objects.count(), 2)

    def test_waitlist_confirmation_rechecks_publication(self):
        p = self.join_preview().json()['data']['proposal_token']
        self.content_change(is_published=False)
        self.assertEqual(self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on')).status_code, 409)
        self.assertFalse(WaitRequest.objects.exists())

    def test_waitlist_preview_uses_published_title_and_fee_terms(self):
        response = self.join_preview()
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()['data']
        self.assertEqual((data['service'], data['fee_label'], data['fee_note']),
            (self.profile.title, '评估后确认费用', self.profile.fee_note))

    def test_waitlist_terms_aba_requires_fresh_preview(self):
        p = self.join_preview().json()['data']['proposal_token']
        self.content_change(is_published=False); self.content_change(is_published=True)
        self.assertEqual(self.post('mini_wait_join_confirm', dict(proposal_token=p, confirmed='on')).status_code, 409)

    def test_waitlist_success_receipt_remains_readable_after_withdrawal(self):
        token = self.join_preview().json()['data']['proposal_token']
        response = self.post('mini_wait_join_confirm', dict(proposal_token=token, confirmed='on'))
        self.assertEqual(response.status_code, 200, response.content)
        entry = WaitRequest.objects.get()
        withdraw(actor=self.front, entry_id=entry.pk); self.content_change(is_published=False)
        response = self.post('mini_wait_join_confirm', dict(proposal_token=token, confirmed='on'))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['data']['wait']['state'], 'WITHDRAWN')
        self.assertEqual(WaitRequest.objects.count(), 1)

    @override_settings(ADC_PUBLIC_ENVIRONMENT_LABEL='测试环境')
    def test_native_environment_label_comes_from_server(self):
        self.assertEqual(self.client.get(reverse('mini_session')).json()['data']['environment_label'], '测试环境')

    @override_settings(ADC_PUBLIC_ENVIRONMENT_LABEL='', ADC_READ_ONLY=True)
    def test_read_only_does_not_hide_services_or_invent_demo_label(self):
        response = self.client.get(reverse('mini_service', kwargs={'pk': self.service.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(reverse('mini_session')).json()['data']['environment_label'], '')
