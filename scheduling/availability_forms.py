from datetime import datetime, timedelta
from django import forms
from django.utils import timezone
from scheduling.availability_rules import LOCAL_ZONE, REASONS

class BeijingDateTimeField(forms.DateTimeField):
    """The UI says Beijing time; never infer the browser/host OS timezone."""
    def to_python(self, value):
        if value in self.empty_values:
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=LOCAL_ZONE) if value.tzinfo is None else value
        for fmt in ('%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M'):
            try:
                return datetime.strptime(value, fmt).replace(tzinfo=LOCAL_ZONE)
            except (ValueError, TypeError):
                pass
        raise forms.ValidationError('请输入完整的北京时间日期与时刻（精确到分钟）。')

class SlotChangeForm(forms.Form):
    state_token = forms.CharField(max_length=5000, widget=forms.HiddenInput)
    start = BeijingDateTimeField(label='新开始时间（北京时间）',
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type':'datetime-local','step':60}),
        help_text='仅改变未来空闲出诊的时间；牙医和诊所保持不变。')
    end = BeijingDateTimeField(label='新结束时间（北京时间）',
        widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'type':'datetime-local','step':60}))
    reason_code = forms.ChoiceField(label='变更依据', choices=[('', '请选择已核对的依据'), *REASONS.items()])
    def __init__(self,*args,action,**kwargs):
        super().__init__(*args,**kwargs)
        self.action=action
        if action == 'deactivate':
            self.fields.pop('start');self.fields.pop('end')
        else:
            minimum=(timezone.now().astimezone(LOCAL_ZONE)+timedelta(minutes=1)).replace(second=0,microsecond=0)
            self.fields['start'].widget.attrs['min']=minimum.strftime('%Y-%m-%dT%H:%M')
            self.fields['end'].widget.attrs['min']=(minimum+timedelta(minutes=1)).strftime('%Y-%m-%dT%H:%M')
    def clean(self):
        result=super().clean()
        if self.action=='replace':
            a,b=result.get('start'),result.get('end')
            if a and a<=timezone.now():self.add_error('start','新开始时间必须晚于当前时间。')
            if a and b and b<=a:self.add_error('end','新结束时间必须晚于新开始时间。')
        return result

class SlotConfirmForm(forms.Form):
    proposal_token=forms.CharField(max_length=5000,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='我已核对原时段、拟变更内容及影响；此操作不代患者取消或改期，不删除历史记录')
