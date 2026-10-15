from django import forms
from equipment.forms import ExplicitProposalForm
from finance.cash_forms import EvidenceFields, CashReviewForm
from finance.reconciliation_models import METHODS, PaymentAccount
from registry.models import Clinic

class AccountForm(forms.Form):
    clinic_id=forms.TypedChoiceField(label='诊所',coerce=int)
    code=forms.CharField(label='合成渠道账户代码',max_length=40,help_text='2至40个英文字母、数字、下划线或短横线。不填写真实银行账号。')
    method=forms.ChoiceField(label='收付款方式',choices=METHODS)
    def __init__(self,*a,**kw):
        super().__init__(*a,**kw)
        self.fields['clinic_id'].choices=[('', '请选择诊所')]+list(Clinic.objects.filter(is_active=True).order_by('clinic_code').values_list('pk','name'))

class AccountStateForm(forms.Form):
    active=forms.TypedChoiceField(label='新的账户状态',choices=[('1','启用'),('0','停用')],coerce=lambda v:v=='1')

class EvidenceForm(EvidenceFields):
    reason=forms.CharField(label='补证／更正依据（仅合成案例）',max_length=500,widget=forms.Textarea(attrs={'rows':3}))

class ImportForm(forms.Form):
    payment_account_id=forms.TypedChoiceField(label='本店渠道账户',coerce=int)
    source=forms.FileField(label='UTF-8 CSV（v1，≤2 MiB／1000行）')
    def __init__(self,*a,actor,**kw):
        super().__init__(*a,**kw)
        from finance.evidence_policies import account_choices
        self.fields['payment_account_id'].choices=[('', '请选择渠道账户')]+[(v.pk,str(v)) for v in account_choices(actor)]
    def clean_source(self):
        f=self.cleaned_data['source']
        from finance.statement_csv import MAX_BYTES
        if f.size>MAX_BYTES:raise forms.ValidationError('CSV最多2 MiB。')
        return f

class MatchForm(forms.Form):
    entry_id=forms.IntegerField(label='已记账款项编号',min_value=1,help_text='只允许匹配同店、同渠道、凭据编号、方向与金额一致的已核实凭据。')

class EvidenceReviewForm(CashReviewForm):
    decision=forms.ChoiceField(label='凭据复核决定',choices=[('approve','核实凭据，原金额保持'),('reject','拒绝本次补证／更正')])

class MatchReviewForm(CashReviewForm):
    decision=forms.ChoiceField(label='匹配复核决定',choices=[('approve','确认此项匹配'),('reject','拒绝本次匹配，保留差异')])
