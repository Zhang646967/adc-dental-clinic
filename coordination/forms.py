from datetime import timedelta
from django import forms
from accounts.policies import clinic_ids
from registry.models import Clinic,Dentist
class JoinForm(forms.Form):
    from scheduling.resource_models import BookingService
    service=forms.ModelChoiceField(label='预约服务（启用资源控制的诊所必选）',queryset=BookingService.objects.none(),required=False)
    clinic=forms.ModelChoiceField(label='希望就诊的诊所',queryset=Clinic.objects.none())
    preferred_dentist=forms.ModelChoiceField(label='希望的牙医（不限制则留空）',queryset=Dentist.objects.none(),required=False)
    patient_no=forms.CharField(label='患者业务编号（前台代登记）',required=False,max_length=40)
    earliest=forms.DateTimeField(label='最早可开始就诊（北京时间）',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    latest=forms.DateTimeField(label='最晚必须结束就诊（北京时间）',widget=forms.DateTimeInput(attrs={'type':'datetime-local'}))
    patient_authority=forms.CharField(required=False,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对以上偏好；候补登记不是正式预约')
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        from django.utils import timezone
        from coordination.windows import window_bounds
        self.window_limits = window_bounds(timezone.now()).as_dict()
        self.fields['earliest'].widget.attrs.update({'min': self.window_limits['min_start'], 'max': self.window_limits['max_start'], 'step': '60'})
        self.fields['latest'].widget.attrs.update({'min': self.window_limits['min_start'], 'max': self.window_limits['max_end'], 'step': '60'})
        self.fields['earliest'].help_text = '只选未来时间。默认每15分钟提供一个快捷选项；不会修改既有候补时间。'
        self.fields['latest'].help_text = '范围须能容纳所选服务；无资源模式时至少30分钟，结束不超过当前时刻之后14天。'
        self.fields['clinic'].queryset=Clinic.objects.filter(is_active=True)
        if getattr(getattr(user,'_adc_workspace',None),'role',None)=='FRONT_DESK':
            self.fields['clinic'].queryset=self.fields['clinic'].queryset.filter(pk__in=clinic_ids(user))
            self.fields['patient_no'].required=True
        else:
            self.fields.pop('patient_no')
            from portal.policies import patient_access,form_authority
            access=patient_access(user)
            self.fields['patient_authority'].initial=form_authority(user)
            if access.delegated:self.fields['clinic'].queryset=self.fields['clinic'].queryset.filter(pk=access.clinic_id)
        self.fields['preferred_dentist'].queryset=Dentist.objects.filter(is_active=True)
        self.fields['service'].queryset=self.BookingService.objects.filter(is_active=True,department__clinic__in=self.fields['clinic'].queryset).select_related('department__clinic')
        self.fields['service'].label_from_instance=lambda s:s.department.clinic.name+' · '+str(s)
        self.window_limits['service_durations']={str(s.pk):s.duration_minutes for s in self.fields['service'].queryset}
    def clean(self):
        data = super().clean()
        if data.get('earliest') and data.get('latest'):
            from django.utils import timezone
            from coordination.windows import validate_wait_window, WindowError
            try:
                validate_wait_window(data['earliest'], data['latest'], now=timezone.now(),minimum=timedelta(minutes=data['service'].duration_minutes) if data.get('service') else timedelta(minutes=30))
            except WindowError as exc:
                self.add_error(exc.field if exc.field in self.fields else None, str(exc))
        return data

class ConfirmForm(forms.Form):
    patient_authority=forms.CharField(required=False,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='我已核对本次操作及其影响')
