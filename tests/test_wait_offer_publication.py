from datetime import timedelta
from django.test import TransactionTestCase
from django.urls import reverse
from coordination.models import SchedulePlan,WaitOffer
from coordination.services import join_waitlist
from scheduling.models import Visit
from scheduling.resource_models import ResourceClaim
from tests.test_reception_resources import ResourceFixture
from tests.workspace_client import WorkspaceClient


class WaitOfferPublicationTests(ResourceFixture,TransactionTestCase):
    def setUp(self):
        self.resources()
        self.client=WorkspaceClient()
        self.client.force_login(self.front)

    def waiting(self):
        return join_waitlist(actor=self.front,clinic_id=self.a.pk,patient_no=self.p1.patient_no,
            earliest=self.t,latest=self.t+timedelta(hours=2),service_id=self.service.pk)

    def generate(self):
        response=self.client.post(reverse('schedule_plans'),{'confirmed':'on'})
        self.assertEqual(response.status_code,302)
        return SchedulePlan.objects.get()

    def test_front_can_find_publication_from_home_list_and_slot(self):
        url=reverse('schedule_plans')
        for route in ['frontdesk_home','waitlist']:
            page=self.client.get(reverse(route))
            self.assertContains(page,url)
            self.assertContains(page,'发布候补邀约')
        page=self.client.get(reverse('front_coordination_detail',kwargs={'pk':self.slot1.pk}))
        self.assertContains(page,'发布本店候补邀约')
        self.assertContains(page,url)

    def test_get_does_not_generate_or_hold_resources(self):
        self.waiting()
        self.assertEqual(self.client.get(reverse('schedule_plans')).status_code,200)
        self.assertEqual((SchedulePlan.objects.count(),WaitOffer.objects.count(),ResourceClaim.objects.count()),(0,0,0))

    def test_generation_is_a_preview_and_publication_needs_explicit_confirmation(self):
        self.waiting();plan=self.generate();self.assertTrue(plan.suggestions)
        url=reverse('schedule_plan',kwargs={'pk':plan.pk})
        self.assertContains(self.client.get(url),'发布限时邀约')
        self.assertEqual((WaitOffer.objects.count(),ResourceClaim.objects.count()),(0,0))
        self.client.post(url,{})
        self.assertEqual(WaitOffer.objects.count(),0)
        for _ in range(2):self.assertEqual(self.client.post(url,{'confirmed':'on'}).status_code,302)
        self.assertEqual((WaitOffer.objects.count(),ResourceClaim.objects.filter(active=True).count(),Visit.objects.count()),(1,1,0))
        self.slot1.refresh_from_db();self.assertFalse(self.slot1.booking_paused)

    def test_manager_reads_explanation_but_cannot_generate_or_publish(self):
        self.waiting();plan=self.generate()
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse('waitlist')),'候补邀约由本店前台')
        for url in [reverse('schedule_plans'),reverse('schedule_plan',kwargs={'pk':plan.pk})]:
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.post(url,{'confirmed':'on'}).status_code,403)
        self.assertEqual(WaitOffer.objects.count(),0)

    def test_withdrawn_request_does_not_create_a_publishable_suggestion(self):
        from coordination.services import withdraw
        row=self.waiting();withdraw(actor=self.front,entry_id=row.pk)
        plan=self.generate();self.assertEqual(plan.suggestions,[])
        self.assertNotContains(self.client.get(reverse('schedule_plan',kwargs={'pk':plan.pk})),'发布限时邀约</button>')

    def test_paused_after_preview_rejects_publication(self):
        self.waiting();plan=self.generate()
        type(self.slot1).objects.filter(pk=self.slot1.pk).update(booking_paused=True,intake_revision=1)
        self.client.post(reverse('schedule_plan',kwargs={'pk':plan.pk}),{'confirmed':'on'})
        self.assertEqual(WaitOffer.objects.count(),0)
        plan.refresh_from_db();self.assertEqual(plan.state,'DRAFT')

    def test_cross_clinic_plan_is_not_available_or_publishable(self):
        self.waiting();plan=self.generate()
        self.client.post(reverse('activate_clinic'),{'clinic':self.b.pk})
        url=reverse('schedule_plan',kwargs={'pk':plan.pk})
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.post(url,{'confirmed':'on'}).status_code,404)
        self.assertEqual(WaitOffer.objects.count(),0)
