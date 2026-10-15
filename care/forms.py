from django import forms
from decimal import Decimal
from registry.models import Allergy, TreatmentType

class VersionForm(forms.Form):
    expected_version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)

class ClinicalNoteForm(VersionForm):
    clinical_note=forms.CharField(label="本次接诊记录（草稿）",max_length=4000,required=False,
        widget=forms.Textarea(attrs={"rows":5}),help_text="仅记录合成案例的接诊事实；保存不会确认治疗、关闭接诊或收款。")
    confirmed=forms.BooleanField(label="我已核对这份草稿内容。")

class AllergyReviewForm(VersionForm):
    patient_version=forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    status=forms.ChoiceField(label="本次询问结果",choices=[("UNKNOWN","仍然未知"),("NO_KNOWN","已确认无已知过敏"),("KNOWN","已知过敏")])
    allergy_ids=forms.ModelMultipleChoiceField(label="已知过敏项目",queryset=Allergy.objects.none(),required=False,widget=forms.CheckboxSelectMultiple)
    confirmed=forms.BooleanField(label="我已向患者复核上述信息（不是医学安全保证）。")
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.fields["allergy_ids"].queryset=Allergy.objects.filter(is_active=True)

class TreatmentChoice(forms.ModelChoiceField):
    def label_from_instance(self,obj):
        return f"{obj.name} · {obj.standard_unit_price:.2f} 元 / {obj.unit_definition}"

class TreatmentForm(VersionForm):
    treatment_id=TreatmentChoice(label="实际提供的治疗",queryset=TreatmentType.objects.none())
    quantity=forms.DecimalField(label="标准单位数量",max_digits=12,decimal_places=3,min_value=Decimal("0.001"))
    price_reason=forms.CharField(label="零价格说明（标准单价为零时必填）",max_length=500,required=False)
    confirmed=forms.BooleanField(label="我确认该项目已经实际提供，数量和标准单位准确。")
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs);self.fields["treatment_id"].queryset=TreatmentType.objects.filter(is_active=True)

class CompletionForm(VersionForm):
    outcome=forms.ChoiceField(label="本次结果",choices=[("TREATED","已实施治疗，完成并开单"),("NO_TREATMENT","已到诊但未治疗，关闭并出零金额单")])
    reason=forms.CharField(label="无治疗关闭原因",max_length=500,required=False,widget=forms.Textarea(attrs={"rows":3}))
    confirmed=forms.BooleanField(label="我已核对实际治疗和金额；发布后不能直接修改。")

class RemoveLineForm(VersionForm):
    line_id=forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    reason=forms.CharField(label="撤回误录明细的原因",max_length=500)
