from datetime import timedelta

from django import forms
from django.utils import timezone

from adc_core.rules import BUSINESS_TZ
from registry.models import Dentist
from scheduling.reschedule_selectors import HORIZON_DAYS
from scheduling.selectors import booking_slots


class ReplacementSearchForm(forms.Form):
    day = forms.DateField(label='新的预约开始日期（北京时间）', widget=forms.DateInput(attrs={'type': 'date'}))
    dentist = forms.ModelChoiceField(label='牙医（可选，留空查本店全部）', queryset=Dentist.objects.none(), required=False)

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        now = timezone.now()
        today = now.astimezone(BUSINESS_TZ).date()
        self.fields['day'].widget.attrs.update(min=today.isoformat(), max=(today+timedelta(days=HORIZON_DAYS)).isoformat())
        slots = booking_slots(actor).filter(starts_at__lt=now+timedelta(days=HORIZON_DAYS+1))
        self.fields['dentist'].queryset = Dentist.objects.filter(pk__in=slots.values('dentist_id')).order_by('employee_no')

    def clean_day(self):
        day = self.cleaned_data['day']
        today = timezone.now().astimezone(BUSINESS_TZ).date()
        if day < today or day > today+timedelta(days=HORIZON_DAYS):
            raise forms.ValidationError('请选择今日起未来14天内的日期。')
        return day


class RescheduleConfirmForm(forms.Form):
    proposal_token = forms.CharField(widget=forms.HiddenInput, max_length=8192)
    confirmed = forms.BooleanField(label='我已核对患者的改期意愿、牙医与起止时间，确认改为此安排（本人声明）')
