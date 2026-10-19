from django import forms
from django.utils import timezone
from operations.views import FilterForm
from operations.cancellation_policy import (BANDS, WEEKDAYS, REASONS, FOLLOW_STATES, PENDING_FOLLOW,
    KINDS, ASSESSMENTS, review_window)
from operations.cancellation_selectors import owners
from operations.policies import period_bounds
from adc_core.rules import RuleError

DATE = {'type': 'date'}

class CancellationFilterForm(FilterForm):
    weekday = forms.TypedChoiceField(label='星期', choices=[('', '全部星期')]+WEEKDAYS, required=False, coerce=int, empty_value=None)
    band = forms.ChoiceField(label='预约开始时段', choices=[('', '全部时段')]+BANDS, required=False)

class FollowUpForm(forms.Form):
    reason_code = forms.ChoiceField(label='核实后的原因分类', choices=REASONS)
    state = forms.ChoiceField(label='联系结果', choices=FOLLOW_STATES)
    due_on = forms.DateField(label='下次联系期限（北京时间）', required=False, widget=forms.DateInput(attrs=DATE))
    replacement_no = forms.CharField(label='另约成功的预约编号', max_length=40, required=False,
        help_text='选择“已另约”时必填。须先通过原预约流程办理；记录联系结果不会创建预约。')
    note = forms.CharField(label='本次联系结果与依据', max_length=500, widget=forms.Textarea(attrs={'rows':3}),
        help_text='保留实际沟通结果；只用课程合成资料，不填病历、银行卡或账号秘密。')
    def __init__(self, *a, clinic, **kw):
        super().__init__(*a, **kw)
        self.fields['assigned_to'] = forms.ModelChoiceField(label='本店跟进前台', queryset=owners(clinic, ('FRONT_DESK',)))
        self.order_fields(['reason_code', 'assigned_to', 'state', 'due_on', 'replacement_no', 'note'])
    def clean(self):
        d = super().clean()
        if d.get('state') in PENDING_FOLLOW and not d.get('due_on'):
            self.add_error('due_on', '待联系或等待回复必须有下次联系期限。')
        if d.get('state') == 'REBOOKED' and not d.get('replacement_no'):
            self.add_error('replacement_no', '请先核实另约成功的预约编号。')
        if d.get('state') not in PENDING_FOLLOW: d['due_on'] = None
        if d.get('state') != 'REBOOKED': d['replacement_no'] = ''
        return d

class ImprovementForm(forms.Form):
    weekday = forms.TypedChoiceField(label='需要改进的星期', choices=WEEKDAYS, coerce=int)
    band = forms.ChoiceField(label='预约开始时段', choices=BANDS)
    baseline_start = forms.DateField(label='原观察窗口起日', widget=forms.DateInput(attrs=DATE))
    baseline_end = forms.DateField(label='原观察窗口止日', widget=forms.DateInput(attrs=DATE))
    kind = forms.ChoiceField(label='措施类别', choices=KINDS)
    plan = forms.CharField(label='具体措施与可核对的完成标准', max_length=500, widget=forms.Textarea(attrs={'rows':3}),
        help_text='例如每周核对取消原因并协商替代时段。不要填写患者姓名、电话或诊疗文字。')
    due_on = forms.DateField(label='执行期限', widget=forms.DateInput(attrs=DATE))
    def __init__(self, *a, clinic, **kw):
        super().__init__(*a, **kw)
        self.fields['assigned_to'] = forms.ModelChoiceField(label='本店执行负责人', queryset=owners(clinic))
    def clean(self):
        d = super().clean()
        if d.get('baseline_start') and d.get('baseline_end'):
            try: period_bounds(d['baseline_start'], d['baseline_end'])
            except RuleError as e: raise forms.ValidationError(str(e))
            if d['baseline_end'] >= timezone.localdate():
                self.add_error('baseline_end', '原观察窗口须完整结束，止日请选昨天或更早。')
        return d

class ImprovementStepForm(forms.Form):
    note = forms.CharField(label='本次办理说明与执行依据', max_length=500, widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self, *a, clinic, action, baseline_end, **kw):
        super().__init__(*a, **kw)
        self.action, self.baseline_end = action, baseline_end
        if action == 'ASSIGN':
            self.fields['assigned_to'] = forms.ModelChoiceField(label='本店执行负责人', queryset=owners(clinic))
            self.fields['due_on'] = forms.DateField(label='执行期限', widget=forms.DateInput(attrs=DATE))
        if action == 'REVIEW':
            self.fields['review_start'] = forms.DateField(label='后续观察起日', widget=forms.DateInput(attrs=DATE))
            self.fields['review_end'] = forms.DateField(label='后续观察止日', widget=forms.DateInput(attrs=DATE))
            self.fields['assessment'] = forms.ChoiceField(label='业务复核结论', choices=ASSESSMENTS,
                help_text='数字变化只能作为观察，不自动证明措施有效；样本不足或不可比时如实选择。')
    def clean(self):
        d = super().clean()
        if self.action == 'REVIEW' and d.get('review_start') and d.get('review_end'):
            try: review_window(d['review_start'], d['review_end'], self.baseline_end)
            except RuleError as e: raise forms.ValidationError(str(e))
            if d['review_end'] >= timezone.localdate():
                self.add_error('review_end', '后续观察尚未结束，不能提前完成复核。')
        return d
