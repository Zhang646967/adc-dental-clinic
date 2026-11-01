from django import forms
from django.utils import timezone
from clinical.plan_forms import ExecutionForm
from clinical.preflight_models import ClinicalConsentRule
from clinical.models import ClinicalReviewerAppointment
from registry.models import Clinic,TreatmentType


class PreflightForm(ExecutionForm):
    communication=forms.CharField(label='本次沟通及身份核对依据（沟通记录类项目必填）',required=False,max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['treatment_type'].label='拟实施实际项目'
        self.fields['quantity'].label='本次拟实施数量'
        self.fields['observed_at'].widget=forms.HiddenInput()
        self.fields['preflight'].widget=forms.HiddenInput()
    def fields_data(self):
        d=super().fields_data();d.pop('communication',None);return d


class RetrospectiveForm(ExecutionForm):
    gap_reason=forms.CharField(label='真实发生及事前资料缺口的补记依据',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':4}))
    def __init__(self,*args,visit,actor,**kwargs):
        super().__init__(*args,visit=visit,actor=actor,**kwargs)
        from clinical.plan_models import PlanStepVersion
        from clinical.plan_locks import readable_services
        self.fields['step_version'].queryset=PlanStepVersion.objects.filter(version__plan__origin_encounter__visit__patient_id=visit.patient_id,
            version__plan__origin_encounter__visit__clinic_id=visit.clinic_id,service_id__in=readable_services(actor,visit.clinic_id)).order_by('-version_id','sequence')
        self.fields['preflight'].widget=forms.HiddenInput()
        self.fields['observed_at'].required=True
    def fields_data(self):
        d=super().fields_data();d.pop('gap_reason',None);return d


class ClinicalRuleForm(forms.Form):
    clinic=forms.ModelChoiceField(label='本店专业审核职责范围',queryset=Clinic.objects.none())
    treatment_type=forms.ModelChoiceField(label='实际项目',queryset=TreatmentType.objects.filter(is_active=True),required=False)
    mode=forms.ChoiceField(label='本项目要求',choices=ClinicalConsentRule.MODES)
    reference=forms.CharField(label='机构规则或启用依据编号',min_length=4,max_length=500)
    explanation=forms.CharField(label='适用说明',required=False,max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    activate=forms.BooleanField(label='已逐项核对本店在用项目规则，启用治疗前控制',required=False)
    def __init__(self,*args,actor,**kwargs):
        super().__init__(*args,**kwargs);now=timezone.now()
        self.fields['clinic'].queryset=Clinic.objects.filter(is_active=True,pk__in=ClinicalReviewerAppointment.objects.filter(
            user=actor,is_active=True,valid_from__lte=now,valid_until__gt=now).values('clinic_id'))
    def clean(self):
        d=super().clean()
        if not d.get('activate') and not d.get('treatment_type'):self.add_error('treatment_type','请选择实际项目。')
        return d


class GapReviewForm(forms.Form):
    note_text=forms.CharField(label='历史缺口复核结论',min_length=4,max_length=1000,widget=forms.Textarea(attrs={'rows':4}),
        help_text='说明已核对的实际事实及后续安排；本结论不构成事前同意、开治或倒签。')
