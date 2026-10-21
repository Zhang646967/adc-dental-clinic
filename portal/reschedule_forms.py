from datetime import timedelta
from django import forms
from django.utils import timezone
from registry.models import Dentist
from scheduling.models import AvailabilitySlot
from portal.rules import HORIZON_DAYS


class SearchForm(forms.Form):
    day = forms.DateField(label='希望就诊日期（北京时间）', widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}))
    dentist = forms.ModelChoiceField(label='医师（可选）', queryset=Dentist.objects.none(), required=False,
        empty_label='本店可接收的医师')

    def __init__(self, *args, visit, **kwargs):
        super().__init__(*args, **kwargs)
        today = timezone.localdate()
        self.fields['day'].widget.attrs.update(min=today.isoformat(), max=(today+timedelta(days=HORIZON_DAYS)).isoformat())
        ids = AvailabilitySlot.objects.filter(clinic_id=visit.clinic_id, is_active=True,
            ends_at__gt=timezone.now()).values('dentist_id')
        self.fields['dentist'].queryset = Dentist.objects.filter(pk__in=ids, is_active=True).order_by('employee_no')

    def clean_day(self):
        value = self.cleaned_data['day']
        if not timezone.localdate() <= value <= timezone.localdate()+timedelta(days=HORIZON_DAYS):
            raise forms.ValidationError('请选择今日起未来十四天内日期。')
        return value


class PreviewForm(forms.Form):
    action = forms.CharField(initial='preview', widget=forms.HiddenInput)
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    slot_id = forms.IntegerField(min_value=1, widget=forms.HiddenInput)
    start = forms.DateTimeField(widget=forms.HiddenInput)
    offer_id = forms.IntegerField(min_value=1, required=False, widget=forms.HiddenInput)
    reason = forms.CharField(label='为什么需要改期？', max_length=500, strip=True,
        widget=forms.Textarea(attrs={'rows': 3}), help_text='请说明安排方面的原因，无需填写病情或证件资料。')


class ConfirmForm(forms.Form):
    action = forms.CharField(initial='confirm', widget=forms.HiddenInput)
    proposal_token = forms.CharField(max_length=16384, widget=forms.HiddenInput)
    confirmed = forms.BooleanField(label='我已核对新医师、日期和起止时间，同意用新安排替代原预约。')
