from decimal import Decimal
from django import forms
from clinical.prescription_models import PrescriptionDecision
from clinical.prescription_payload import MAX_ITEMS, catalogue_for


class PrescriptionForm(forms.Form):
    patient_binding = forms.CharField(widget=forms.HiddenInput)
    record_id = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    previous = forms.IntegerField(widget=forms.HiddenInput, min_value=1, required=False)
    indication = forms.CharField(label='临床依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class PrescriptionItemForm(forms.Form):
    item = forms.ModelChoiceField(label='目录条目', queryset=None, empty_label='选择本店条目')
    dose = forms.DecimalField(label='单次剂量（目录单位）', max_digits=7, decimal_places=3, min_value=Decimal('0.001'),
                              max_value=9999)
    frequency = forms.IntegerField(label='每日次数', min_value=1, max_value=24)
    days = forms.IntegerField(label='疗程天数', min_value=1, max_value=90)
    quantity = forms.IntegerField(label='调配数量（目录单位）', min_value=1, max_value=9999)

    def __init__(self, *args, clinic_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['item'].queryset = catalogue_for(clinic_id)


PrescriptionItems = forms.formset_factory(
    PrescriptionItemForm, extra=MAX_ITEMS - 1, min_num=1, max_num=MAX_ITEMS,
    validate_min=True, validate_max=True, absolute_max=MAX_ITEMS, can_delete=True, can_delete_extra=False,
)


class PrescriptionDecisionForm(forms.Form):
    version_id = forms.IntegerField(widget=forms.HiddenInput, min_value=1)
    action = forms.ChoiceField(label='办理决定')
    reason = forms.CharField(label='决定依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, pharmacist, **kwargs):
        super().__init__(*args, **kwargs)
        withdraw = PrescriptionDecision.Action.WITHDRAWN
        self.fields['action'].choices = [
            (action, label) for action, label in PrescriptionDecision.Action.choices
            if (action != withdraw) == pharmacist
        ]


class PrescriptionConfirmForm(forms.Form):
    proposal_token = forms.CharField(widget=forms.HiddenInput, max_length=16384)
    confirmed = forms.BooleanField(label='我已核对患者、处方版本和本次办理内容')
