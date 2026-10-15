from django import forms
from decimal import Decimal
from django.utils import timezone

class CashRequestForm(forms.Form):
    kind=forms.ChoiceField(label='记录类型',choices=[('RECEIPT','模拟收款'),('REFUND','模拟退款')])
    amount=forms.DecimalField(label='本次金额（CNY）',min_value=Decimal('0.01'),max_digits=16,decimal_places=2)
    occurred_on=forms.DateField(label='事实日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    reason=forms.CharField(label='核对依据（合成案例，不含病历）',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class ExpenseRequestForm(forms.Form):
    occurred_on=forms.DateField(label='事实日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    reason=forms.CharField(label='设备费用核对依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class CashReviewForm(forms.Form):
    decision=forms.ChoiceField(label='财务决定',choices=[('approve','核实并记账'),('reject','拒绝本次申请')])
    reason=forms.CharField(label='独立审核说明',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
