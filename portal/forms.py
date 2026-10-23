from django import forms

class BookingConfirmationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, max_length=8192)
    patient_request = forms.CharField(label='这次主要想解决什么问题？（可选）', required=False,
        max_length=500, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': '例如：想做一次口腔检查；或说明不适的位置、持续时间及希望医师了解的事项。'}),
        help_text='仅记录本次就诊需求，不用于在线诊断。紧急情况请及时就医。')
    confirmed = forms.BooleanField(label="我已核对诊所、牙医和北京时间，确认提交此预约。")

class CancelForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(label="取消原因", max_length=500, widget=forms.Textarea(attrs={"rows":3}))
    confirmed = forms.BooleanField(label="我确认取消这一次预约；不会影响其他预约。")

class SlotFilterForm(forms.Form):
    from scheduling.resource_models import BookingService
    from registry.models import Dentist
    service=forms.ModelChoiceField(label='预约服务',queryset=BookingService.objects.none())
    dentist=forms.ModelChoiceField(label='医师（可选）',queryset=Dentist.objects.none(),required=False)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from portal.service_catalogue import public_services
        from scheduling.service_content import positive_id
        from registry.models import Clinic
        services=public_services()
        self.fields['clinic'].queryset=Clinic.objects.filter(pk__in=services.values('department__clinic_id'))
        clinic_id=positive_id(str(self.data.get('clinic',''))) if self.is_bound else None
        if clinic_id:services=services.filter(department__clinic_id=clinic_id)
        self.fields['service'].queryset=services
        self.fields['service'].label_from_instance=lambda s:s.patient_presentation.title+' · '+s.department.clinic.name
        self.fields['service'].help_text='先选服务，再查看接诊医师与时间。'
        selected=positive_id(str(self.data.get('service',''))) if self.is_bound else None
        self.fields['dentist'].queryset=self.Dentist.objects.filter(is_active=True,
            booking_services__in=services.filter(pk=selected)).distinct() if selected else self.Dentist.objects.none()
        self.fields['dentist'].empty_label='由可约时间匹配医师'

    from registry.models import Clinic
    clinic = forms.ModelChoiceField(label='就诊门店（可选）',queryset=Clinic.objects.none(),required=False,
        empty_label='全部接诊门店')
    day = forms.DateField(label="日期（北京时间，选填）", required=False, widget=forms.DateInput(attrs={"type":"date","id":"day-filter"}))

    def clean_day(self):
        from datetime import timedelta
        from django.utils import timezone
        day=self.cleaned_data.get('day')
        if day and not timezone.localdate() <= day <= timezone.localdate()+timedelta(days=14):
            raise forms.ValidationError('请选择今日至未来14天内的日期。')
        return day
