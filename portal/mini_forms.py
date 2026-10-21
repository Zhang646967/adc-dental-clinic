"""Inputs for the native patient channel; ownership always comes from PatientAccess."""
from django import forms
from portal.reschedule_forms import PreviewForm, ConfirmForm


class CandidateForm(forms.Form):
    clinic = forms.IntegerField(min_value=1)
    service = forms.IntegerField(min_value=1, required=False)
    dentist = forms.IntegerField(min_value=1, required=False)
    day = forms.DateField()


class BookingPreviewForm(forms.Form):
    slot = forms.IntegerField(min_value=1)
    start = forms.DateTimeField()
    service = forms.IntegerField(min_value=1, required=False)


class ConfirmationForm(forms.Form):
    proposal_token = forms.CharField(max_length=16384)
    confirmed = forms.BooleanField()


class CancellationPreviewForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0)
    reason = forms.CharField(min_length=1, max_length=500, strip=True)


class PageForm(forms.Form):
    page = forms.IntegerField(min_value=1, max_value=100000, required=False)
    queue = forms.ChoiceField(choices=[(s, s) for s in ('active', 'history', 'all')], required=False)


class WaitJoinForm(forms.Form):
    clinic = forms.IntegerField(min_value=1)
    service = forms.IntegerField(min_value=1, required=False)
    dentist = forms.IntegerField(min_value=1, required=False)
    earliest = forms.DateTimeField()
    latest = forms.DateTimeField()


class OfferAnswerForm(forms.Form):
    action = forms.ChoiceField(choices=[('accept', '接受并新增一次预约'), ('decline', '拒绝本次邀约')])
