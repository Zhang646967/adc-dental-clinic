from django import forms

class BookingConfirmationForm(forms.Form):
    token = forms.CharField(widget=forms.HiddenInput, max_length=8192)
    confirmed = forms.BooleanField(label="我已核对诊所、牙医和北京时间，确认提交此预约。")

class CancelForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    reason = forms.CharField(label="取消原因", max_length=500, widget=forms.Textarea(attrs={"rows":3}))
    confirmed = forms.BooleanField(label="我确认取消这一次预约；不会影响其他预约。")

class SlotFilterForm(forms.Form):
    from scheduling.resource_models import BookingService
    from registry.models import Dentist
    service=forms.ModelChoiceField(label='预约服务',queryset=BookingService.objects.none(),required=False)
    dentist=forms.ModelChoiceField(label='医师（可选）',queryset=Dentist.objects.none(),required=False)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        from scheduling.resource_models import ResourcePolicy
        self.fields['service'].queryset=self.BookingService.objects.filter(is_active=True,department__is_active=True,
            department__clinic_id__in=ResourcePolicy.objects.filter(state='ENABLED').values('clinic_id')).select_related('department__clinic')
        self.fields['service'].label_from_instance=lambda s:s.department.clinic.name+' · '+str(s)
        self.fields['service'].help_text='启用资源的诊所须选择预约服务，系统安排兼容设备。'
        self.fields['dentist'].queryset=self.Dentist.objects.filter(is_active=True)

    clinic = forms.IntegerField(label="诊所编号（选填）", required=False, min_value=1)
    day = forms.DateField(label="日期（北京时间，选填）", required=False, widget=forms.DateInput(attrs={"type":"date","id":"day-filter"}))
