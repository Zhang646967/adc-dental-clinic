from django import forms
from coordination.task_rules import ACTION_REASONS, REASONS, PURPOSES, validate_options

class TaskChangeForm(forms.Form):
    state_token=forms.CharField(max_length=6000,widget=forms.HiddenInput)
    reason=forms.ChoiceField(label='本次操作依据')
    due_at=forms.DateTimeField(label='下次跟进期限（北京时间）',required=False,
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))
    purpose=forms.ChoiceField(label='协调目标',required=False,choices=[('','请选择目标')]+list(PURPOSES.items()))
    target_kind=forms.ChoiceField(label='办理声明对应的对象',required=False,
        choices=[('','不指定对象，仅请求主管协助'),('visit','本出诊预约'),('offer','本出诊邀约')])
    target_id=forms.IntegerField(label='对象记录编号',required=False,min_value=1,max_value=2**63-1,
        help_text='取自本出诊协调列表；不要填写患者姓名、电话、主诉或治疗内容。')
    def __init__(self,*args,action,**kwargs):
        super().__init__(*args,**kwargs);self.action=action
        self.fields['reason'].choices=[('','请选择依据')]+[(k,REASONS[k]) for k in ACTION_REASONS[action]]
        if action!='open': self.fields.pop('purpose')
        else: self.fields['purpose'].required=True
        if action!='progress':
            self.fields.pop('target_kind');self.fields.pop('target_id')
        if action in ('open','claim','progress'):self.fields['due_at'].required=True
        else:self.fields.pop('due_at')
    def clean(self):
        d=super().clean()
        if self.errors: return d
        try: validate_options(self.action,d['reason'],purpose=d.get('purpose',''),
                              target_kind=d.get('target_kind',''),target_id=d.get('target_id'))
        except ValueError as exc: raise forms.ValidationError(str(exc)) from exc
        return d

class TaskConfirmForm(forms.Form):
    proposal_token=forms.CharField(max_length=6000,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='我已核对目标及影响：本操作只更新协调任务，不代替患者意思或办理预约，也不自动停用或恢复出诊。')
