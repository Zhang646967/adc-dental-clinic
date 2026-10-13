from django import forms
from scheduling.intake_rules import REASONS, ACTION_REASONS

class IntakeChangeForm(forms.Form):
    state_token = forms.CharField(widget=forms.HiddenInput, max_length=5000)
    reason = forms.ChoiceField(label='已核对的操作依据')
    def __init__(self,*args,action,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['reason'].choices = [('', '请选择已核对的依据')] + [(k,v) for k,v in REASONS.items() if k in ACTION_REASONS[action]]

class IntakeConfirmForm(forms.Form):
    proposal_token = forms.CharField(widget=forms.HiddenInput, max_length=5000)
    confirmed = forms.BooleanField(label='我已核对接收状态及影响；已有预约和有效邀约不被取消。')
