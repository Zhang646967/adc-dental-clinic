from django import forms
from registry.models import Dentist

class ConfirmedForm(forms.Form):
    expected_version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    confirmed=forms.BooleanField(label='我已核对并确认本次操作')

class QuarterForm(forms.Form):
    year=forms.IntegerField(label='年份',min_value=1900,max_value=9998)
    quarter_no=forms.TypedChoiceField(label='自然季度',choices=[(i,f'第{i}季度') for i in range(1,5)],coerce=int)
    confirmed=forms.BooleanField(label='建立该季度管理范围（不会自动填入成本）')

class MemberForm(ConfirmedForm):
    dentist_id=forms.ModelChoiceField(label='纳入牙医（含有成本但无收入者）',queryset=Dentist.objects.all().order_by('employee_no'))

class CostForm(ConfirmedForm):
    supply_cost=forms.DecimalField(label='医疗用品成本（元）',min_value=0,max_digits=16,decimal_places=2)
    operating_expense=forms.DecimalField(label='运营费用（元）',min_value=0,max_digits=16,decimal_places=2)
    notes=forms.CharField(label='成本依据／修改说明',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
