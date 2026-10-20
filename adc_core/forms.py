from django import forms
from accounts.policies import clinic_ids
from registry.models import Clinic, Dentist, Allergy
from scheduling.selectors import booking_slots
from adc_core.rules import RuleError, validate_allergies

class PatientForm(forms.Form):
    reception_case=forms.IntegerField(required=False,widget=forms.HiddenInput,min_value=1)
    clinic = forms.ModelChoiceField(label="建档诊所", queryset=Clinic.objects.none())
    name = forms.CharField(label="姓名", max_length=80)
    date_of_birth = forms.DateField(label="出生日期", widget=forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}))
    billing_address = forms.CharField(label="账单地址", max_length=255)
    phone = forms.CharField(label="电话", max_length=32)
    email = forms.EmailField(label="邮箱（选填）", required=False)
    emergency_name = forms.CharField(label="紧急联系人", max_length=80)
    emergency_phone = forms.CharField(label="紧急联系电话", max_length=32)
    allergy_status = forms.ChoiceField(label="过敏信息状态", choices=[("UNKNOWN", "未询问/未知"), ("NO_KNOWN", "已确认无已知过敏"), ("KNOWN", "已知过敏")])
    allergies = forms.ModelMultipleChoiceField(label="已知过敏项目", queryset=Allergy.objects.none(), required=False, widget=forms.CheckboxSelectMultiple)
    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["clinic"].queryset = Clinic.objects.filter(pk__in=clinic_ids(user), is_active=True)
        self.fields["allergies"].queryset = Allergy.objects.filter(is_active=True)
    def clean(self):
        result = super().clean()
        if "allergy_status" in result and "allergies" in result:
            try:
                validate_allergies(result["allergy_status"], [x.pk for x in result["allergies"]])
            except RuleError as exc:
                raise forms.ValidationError(str(exc)) from exc
        return result

class AppointmentForm(forms.Form):
    from scheduling.resource_models import BookingService
    service=forms.ModelChoiceField(label='预约服务',queryset=BookingService.objects.none(),required=False)
    consent=forms.BooleanField(label='已核对诊所、服务、医师和起止时间，并取得患者同意',required=False)
    patient_no = forms.CharField(label="患者业务编号", max_length=40, help_text="从患者页复制完整编号。跨店患者先用精确编号检索。")
    slot = forms.ModelChoiceField(label="出诊时段", queryset=None)
    start = forms.DateTimeField(label="预约开始", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    end = forms.DateTimeField(label="预计结束", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    chief_complaint = forms.CharField(label="患者主诉", widget=forms.Textarea(attrs={"rows": 2}), required=False, max_length=2000)
    special_needs = forms.CharField(label="特殊需求", widget=forms.Textarea(attrs={"rows": 2}), required=False, max_length=2000)
    treatment_request = forms.CharField(label="治疗意向（不是已治疗项目）", required=False, max_length=500)
    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slot"].queryset = booking_slots(user)
        self.fields['service'].queryset=self.BookingService.objects.filter(department__clinic_id__in=clinic_ids(user),is_active=True).select_related('department')
        from scheduling.resources import policy
        row=policy(getattr(getattr(user,'_adc_workspace',None),'clinic_id',None))
        if row:
            self.fields['service'].required=True;self.fields['consent'].required=True

class RescheduleForm(forms.Form):
    from scheduling.resource_models import BookingService
    service=forms.ModelChoiceField(label='预约服务',queryset=BookingService.objects.none(),required=False)
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    slot = forms.ModelChoiceField(label="新的出诊时段", queryset=None)
    start = forms.DateTimeField(label="新的开始时间", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M:%S", attrs={"type": "datetime-local", "step": "1"}))
    end = forms.DateTimeField(label="新的结束时间", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M:%S", attrs={"type": "datetime-local", "step": "1"}))
    reason = forms.CharField(label="改期原因", max_length=500)
    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slot"].queryset = booking_slots(user)
        self.fields['service'].queryset=self.BookingService.objects.filter(department__clinic_id__in=clinic_ids(user),is_active=True).select_related('department')
        from scheduling.resources import policy
        if policy(getattr(getattr(user,'_adc_workspace',None),'clinic_id',None)):self.fields['service'].required=True

class ActionForm(forms.Form):
    expected_version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    action = forms.ChoiceField(choices=[("check_in", "登记到诊"), ("cancel", "取消预约"), ("no_show", "核实爽约")])
    party = forms.ChoiceField(label="取消发起方", choices=[("", "请选择（取消时必填）"), ("PATIENT", "患者"), ("CLINIC", "诊所")], required=False)
    reason = forms.CharField(label="原因/核实说明", required=False, max_length=500)

class SlotForm(forms.Form):
    clinic = forms.ModelChoiceField(label="诊所", queryset=Clinic.objects.none())
    dentist = forms.ModelChoiceField(label="牙医", queryset=Dentist.objects.none())
    start = forms.DateTimeField(label="开始", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    end = forms.DateTimeField(label="结束", widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}))
    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["clinic"].queryset = Clinic.objects.filter(pk__in=clinic_ids(user, ("FRONT_DESK",)), is_active=True)
        self.fields["dentist"].queryset = Dentist.objects.filter(is_active=True)
