from django import forms
from clinical.consent_models import ConsentEvent


class ConsentActionForm(forms.Form):
    action = forms.ChoiceField(label='本次办理', choices=[(k, v) for k, v in ConsentEvent.ACTIONS if k not in ('PUBLISHED', 'ANSWER')])
    version = forms.IntegerField(required=False, widget=forms.HiddenInput)
    text = forms.CharField(label='问题／原因／沟通说明', required=False, max_length=2000, widget=forms.Textarea(attrs={'rows': 3}))
    identity_reference = forms.CharField(label='本人身份及理解表达核对依据（只填记录编号，不填证件全文）', required=False, max_length=500)
    self_qualified = forms.BooleanField(label='已当面核对成年患者本人身份及理解表达条件；微信或年龄不代替本次核对', required=False)
    amendment_reason = forms.CharField(label='重新告知原因', required=False, max_length=500)
    reply_to = forms.IntegerField(label='待答复问题编号', required=False, min_value=1)
    paper = forms.BooleanField(label='登记患者本人纸质原件决定', required=False)
    reference = forms.CharField(label='原件参考编号', required=False, max_length=500)
    occurred_at = forms.DateTimeField(label='纸质决定实际时间', required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}))
    paper_verified = forms.BooleanField(label='已核对本人纸质原件、对应版本和实际时间；本操作没有代点患者账号', required=False)

    def __init__(self, *args, doctor=False, **kwargs):
        super().__init__(*args, **kwargs)
        if doctor:
            self.fields['action'].choices = [('PUBLISH', '确认告知／重新告知'), ('ANSWER', '答复具体问题')] + self.fields['action'].choices
        else:
            for key in ('identity_reference', 'self_qualified', 'amendment_reason', 'reply_to', 'paper', 'reference', 'occurred_at', 'paper_verified'):
                self.fields.pop(key)

    def values(self):
        values = dict(self.cleaned_data);action = values.pop('action');version = values.pop('version', None)
        if values.get('occurred_at'):values['occurred_at'] = values['occurred_at'].isoformat()
        return action, version, values
