from django import forms
from django.utils import timezone
from clinical.encounter_models import HISTORY_STATES,DENTITIONS
from clinical.encounters import visible_history
from clinical.tooth_rules import PERMANENT,PRIMARY,SURFACES,KINDS


class RevisionForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    expected_revision=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    operation_id=forms.UUIDField(widget=forms.HiddenInput)


class HistoryForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096,required=False)
    expected_revision=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    operation_id=forms.UUIDField(widget=forms.HiddenInput)
    medical_status=forms.ChoiceField(label='患者自述的既往健康情况',choices=HISTORY_STATES,initial='UNKNOWN')
    medical_history=forms.CharField(label='既往健康情况说明',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    medication_status=forms.ChoiceField(label='患者自述的目前用药情况',choices=HISTORY_STATES,initial='UNKNOWN')
    medications=forms.CharField(label='用药说明',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    allergy_status=forms.ChoiceField(label='患者自述的过敏情况',choices=HISTORY_STATES,initial='UNKNOWN')
    reported_allergies=forms.CharField(label='自述过敏说明',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='确认这是患者自述；不清楚的情况保留未知，仍由医师在接诊时另行核对')


class StartEncounterForm(forms.Form):
    patient_binding=forms.CharField(widget=forms.HiddenInput,max_length=4096)
    expected_visit_version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    operation_id=forms.UUIDField(widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='已核对本次就诊人和实际到诊情况，开始记录检查')


class ClinicalNotesForm(RevisionForm):
    chief_complaint=forms.CharField(label='主诉与本次就诊目的',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    examination=forms.CharField(label='检查经过、全口或其他部位观察',max_length=4000,required=False,widget=forms.Textarea(attrs={'rows':4}))
    history=forms.ModelChoiceField(label='本次核对的具体自述版本',queryset=None,required=False,empty_label='尚未取得自述')
    history_review=forms.ChoiceField(label='病史核对情况',choices=[('UNAVAILABLE','未取得自述，未知保留'),('REVIEWED','已核对所选自述')])
    history_assessment=forms.CharField(label='医师核对结论与仍未知事项',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    history_discrepancy=forms.CharField(label='自述差异与待继续核实事项',max_length=2000,required=False,widget=forms.Textarea(attrs={'rows':3}))
    dentition=forms.ChoiceField(label='本次核对的牙列',choices=DENTITIONS)
    observed_at=forms.DateTimeField(label='更改检查发生时间（北京时间，可留空）',required=False,
        help_text='留空保留已保存的发生时间；首次保存按当前时间记录。补记时请核对实际到诊时间。',
        widget=forms.DateTimeInput(attrs={'type':'datetime-local','step':'1'},format='%Y-%m-%dT%H:%M:%S'))
    amendment_reason=forms.CharField(label='更正依据',min_length=4,max_length=500,required=False,widget=forms.Textarea(attrs={'rows':2}))

    def __init__(self,*args,visit,is_amendment=False,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['history'].queryset=visible_history(visit.patient_id,visit.clinic_id)
        self.fields['history'].label_from_instance=lambda r:f'{r.get_source_display()} · 第{r.revision}版 · {timezone.localtime(r.recorded_at):%Y-%m-%d %H:%M}'
        if not is_amendment:self.fields.pop('amendment_reason')
    def fields_data(self):
        data=dict(self.cleaned_data);row=data.pop('history');data['history_id']=row.pk if row else None
        return data


class FindingForm(RevisionForm):
    tooth=forms.TypedChoiceField(label='牙位（FDI编号，可直接用键盘选择）',coerce=int,
        choices=[('', '请选择牙位')]+[(t,('恒牙 ' if t in PERMANENT else '乳牙 ')+str(t)) for t in PERMANENT+PRIMARY])
    surfaces=forms.MultipleChoiceField(label='牙面（整牙观察可不选）',choices=list(SURFACES.items()),required=False,widget=forms.CheckboxSelectMultiple)
    kind=forms.ChoiceField(label='观察类别',choices=list(KINDS.items()))
    detail=forms.CharField(label='观察说明',max_length=1000,widget=forms.Textarea(attrs={'rows':3}))
    def fields_data(self):
        data=dict(self.cleaned_data);data['surface']=''.join(data.pop('surfaces'));return data


class RemoveFindingForm(RevisionForm):
    line_no=forms.IntegerField(min_value=1,widget=forms.HiddenInput)


class ClinicalReasonForm(RevisionForm):
    reason=forms.CharField(label='办理依据',min_length=4,max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='已核对当前就诊人与版本，确认办理本次操作')


class ClinicalConfirmForm(forms.Form):
    proposal_token=forms.CharField(widget=forms.HiddenInput,max_length=16384)
    confirmed=forms.BooleanField(label='已核对就诊人、检查内容、自述来源和未知／差异情况，确认形成新的检查版本')
