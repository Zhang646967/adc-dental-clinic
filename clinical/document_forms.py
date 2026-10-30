from django import forms
from django.utils import timezone
from clinical.document_models import DOCUMENT_KINDS, EVIDENCE_KINDS
from clinical.encounter_forms import RevisionForm


class DocumentForm(RevisionForm):
    kind = forms.ChoiceField(label='文书类别', choices=DOCUMENT_KINDS)
    prior_visit_version = forms.ModelChoiceField(label='本店本人负责的既往确认文书', queryset=None,
                                                required=False, empty_label='未选择既往文书')
    prior_context = forms.CharField(label='复诊来源及本次变化', max_length=1000, required=False,
                                   widget=forms.Textarea(attrs={'rows': 3}))
    diagnosis = forms.CharField(label='诊断／临床判断与依据', max_length=2000, required=False,
                               widget=forms.Textarea(attrs={'rows': 4}))
    ancillary_results = forms.CharField(label='辅助检查结果及来源', max_length=2000, required=False,
                                       help_text='记录实际取得的检查及其日期／来源；尚无结果请明确说明。',
                                       widget=forms.Textarea(attrs={'rows': 3}))
    instructions = forms.CharField(label='离诊医嘱与注意事项', max_length=2000, required=False,
                                  widget=forms.Textarea(attrs={'rows': 4}))
    follow_up = forms.CharField(label='复诊安排与异常时的联系建议', max_length=1000, required=False,
                               widget=forms.Textarea(attrs={'rows': 3}))
    evidence_kind = forms.ChoiceField(label='医师确认凭据', choices=EVIDENCE_KINDS)
    evidence_reference = forms.CharField(label='纸质原件位置及凭据引用', max_length=500, required=False,
                                        widget=forms.Textarea(attrs={'rows': 2}))
    late_reason = forms.CharField(label='迟记原因', max_length=500, required=False,
                                 widget=forms.Textarea(attrs={'rows': 2}))

    def __init__(self, *args, prior_versions, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['prior_visit_version'].queryset = prior_versions
        self.fields['prior_visit_version'].label_from_instance = lambda v: f'{timezone.localtime(v.document.encounter.visit.attended_at):%Y-%m-%d %H:%M} · {v.get_kind_display()}第{v.revision}版'

    def fields_data(self):
        data = {key: value for key, value in self.cleaned_data.items()
                if key not in ('patient_binding', 'expected_revision', 'operation_id')}
        data['prior_visit_version'] = data['prior_visit_version'].pk if data['prior_visit_version'] else None
        return data


class DocumentFollowupForm(RevisionForm):
    note = forms.CharField(label='办理进展与待解决事项', min_length=4, max_length=1000,
                          widget=forms.Textarea(attrs={'rows': 3}))
    due_at = forms.DateTimeField(label='下一次办理期限（北京时间）',
                                widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    confirmed = forms.BooleanField(label='确认记录进展；原文书办理期限及超期事实继续保留')


class DocumentConfirmForm(forms.Form):
    proposal_token = forms.CharField(widget=forms.HiddenInput, max_length=16384)
    confirmed = forms.BooleanField(label='我已核对就诊人、来源、实际处置及完整文书，以本人医师身份确认此准确版本')
