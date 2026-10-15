from django import forms
from decimal import Decimal
from django.utils import timezone

class EvidenceFields(forms.Form):
    payment_account_id=forms.TypedChoiceField(label='本店收付款渠道账户',coerce=int)
    reference=forms.CharField(label='合成付款凭据编号',max_length=80,help_text='填写可供流水核对的参考编号，不含银行卡、真实账号或病历。')
    def __init__(self,*args,actor=None,**kwargs):
        super().__init__(*args,**kwargs)
        from finance.evidence_policies import account_choices
        choices=account_choices(actor) if actor is not None else []
        self.fields['payment_account_id'].choices=[('', '请选择渠道账户')]+[(a.pk,str(a)) for a in choices]
        self.fields['payment_account_id'].help_text='没有可用渠道时，请先由财务在“渠道账户”中建立本店合成渠道。'

class CashRequestForm(EvidenceFields):
    kind=forms.ChoiceField(label='记录类型',choices=[('RECEIPT','模拟收款'),('REFUND','模拟退款')])
    amount=forms.DecimalField(label='本次金额（CNY）',min_value=Decimal('0.01'),max_digits=16,decimal_places=2)
    occurred_on=forms.DateField(label='事实日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    reason=forms.CharField(label='核对依据（合成案例，不含病历）',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class ExpenseRequestForm(EvidenceFields):
    occurred_on=forms.DateField(label='事实日期（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    reason=forms.CharField(label='设备费用核对依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class CashReviewForm(forms.Form):
    decision=forms.ChoiceField(label='财务决定',choices=[('approve','核实并记账'),('reject','拒绝本次申请')])
    reason=forms.CharField(label='独立审核说明',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
