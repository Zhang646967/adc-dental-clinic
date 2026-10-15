from django import forms
from django.utils import timezone
from equipment.models import CATEGORIES

class EquipmentRegisterForm(forms.Form):
    asset_code=forms.RegexField(regex=r'^[A-Za-z0-9][A-Za-z0-9_-]{1,39}$',label='设备编号',max_length=40,help_text='2至40个英文字母、数字、下划线或短横线；保存为大写。')
    name=forms.CharField(label='设备名称',max_length=120)
    category=forms.ChoiceField(label='类别',choices=CATEGORIES)
    location=forms.CharField(label='本店存放／使用位置',max_length=120)
    acquired_on=forms.DateField(label='购置／接收日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    acquisition_cost=forms.DecimalField(label='购置成本（CNY，空白表示未登记）',min_value=0,max_digits=16,decimal_places=2,required=False)
    next_service_due=forms.DateField(label='下一次保养到期日（空白表示未登记）',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    note=forms.CharField(label='登记依据（合成案例）',max_length=500,widget=forms.Textarea(attrs={'rows':2}))

    def clean_acquired_on(self):
        value=self.cleaned_data['acquired_on']
        if value>timezone.localdate():raise forms.ValidationError('已接收设备的日期不能在未来。')
        return value

class EquipmentActionForm(forms.Form):
    kind=forms.ChoiceField(label='本次操作',choices=[('MAINTENANCE','送修／停止使用'),('SERVICE','保养完成／恢复使用'),('RETIRE','永久退役')])
    performed_on=forms.DateField(label='事实发生日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    cost=forms.DecimalField(label='本次保养费用（空白表示未登记）',min_value=0,max_digits=16,decimal_places=2,required=False)
    next_service_due=forms.DateField(label='完成保养后的下一到期日',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    note=forms.CharField(label='原因及本次事实（合成案例）',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

    def __init__(self,*args,state=None,**kwargs):
        super().__init__(*args,**kwargs)
        if state=='MAINTENANCE':
            self.fields['kind'].choices=[('SERVICE','完成维修／恢复使用'),('RETIRE','永久退役')]
            self.initial.setdefault('kind','SERVICE')
        elif state=='RETIRED':self.fields['kind'].choices=[]

    def clean(self):
        data=super().clean()
        if data.get('kind')!='SERVICE' and (data.get('cost') is not None or data.get('next_service_due') is not None):
            raise forms.ValidationError('只有保养完成／恢复使用时登记费用及下一保养日期。')
        return data

class ExplicitProposalForm(forms.Form):
    proposal_token=forms.CharField(max_length=16384,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='我已核对事实，确认保存以上安排（本人声明）。')
