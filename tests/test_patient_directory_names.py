from django.test import TransactionTestCase
from django.urls import reverse

from patients.models import Patient
from tests.fixtures import FixtureMixin
from tests.workspace_client import WorkspaceClient


class PatientNameLookupTests(FixtureMixin, TransactionTestCase):
    def test_namesakes_use_only_visible_records_even_across_pages(self):
        self.make_fixture()
        client = WorkspaceClient()
        client.force_login(self.front)
        self.assertEqual(client.post(reverse('activate_clinic'), {'clinic': self.a.pk}).status_code, 302)
        name = self.p1.name
        self.p2.name = name
        self.p2.save(update_fields=['name'])
        route = reverse('patients')
        only = client.get(route, {'q': name})
        self.assertContains(only, self.p1.patient_no)
        self.assertNotContains(only, '同名 · 请核对编号')
        for i in range(21):
            Patient.objects.create(name=name, date_of_birth=self.p1.date_of_birth,
                billing_address='合成地址', phone='9000000000', emergency_name='合成',
                emergency_phone='000', created_in_clinic=self.a)
        selected = client.get(route, {'q': self.p1.patient_no})
        self.assertContains(selected, '同名 · 请核对编号', count=1)
        page = client.get(route, {'q': name, 'page': 2})
        self.assertContains(page, '同名 · 请核对编号', count=2)
        self.assertContains(page, self.p1.patient_no)
        self.assertNotContains(page, self.p2.patient_no)
        self.assertNotContains(page, '9000000000')
        detail = client.get(reverse('patient_detail', args=[self.p1.pk]), {'q': name, 'list_page': '2'})
        self.assertContains(detail, f'page=2#patient-{self.p1.pk}')
