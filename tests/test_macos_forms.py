"""Regression for the contact form's first real Django startup."""
from django.test import SimpleTestCase
from patients.contact_forms import ContactEditForm


class ContactFormStartupTests(SimpleTestCase):
    def form(self, email):
        return ContactEditForm(data={
            'state_token': 'synthetic-state-token', 'phone': '000-1234',
            'email': email, 'billing_address': '虚构课程地址',
            'emergency_name': '合成联系人', 'emergency_phone': '000-5678',
            'reason_code': 'PATIENT_UPDATE',
        })

    def test_valid_email_is_accepted(self):
        form = self.form('course@example.invalid')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], 'course@example.invalid')

    def test_optional_email_can_be_cleared(self):
        form = self.form('')
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['email'], '')

    def test_invalid_email_is_rejected(self):
        self.assertIn('email', self.form('not-an-email').errors)

    def test_email_is_not_silently_trimmed_before_validation(self):
        self.assertIn('email', self.form(' course@example.invalid ').errors)
