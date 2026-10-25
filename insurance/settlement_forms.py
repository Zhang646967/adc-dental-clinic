from decimal import Decimal
from django import forms
from insurance.settlement_models import SIMULATION_MODES


class SettlementForm(forms.Form):
    simulation_mode = forms.ChoiceField(label='本地模拟响应', choices=SIMULATION_MODES)
    reason = forms.CharField(label='逐项分担依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}),
        help_text='明确记录合成结果的核对依据，不填写真实医保或支付凭证。')

    def __init__(self, source, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.source = source
        self.line_fields = []
        for line in source['lines']:
            keys = []
            for kind, label in [('patient_cash', '患者现金责任'), ('personal_account', '个人账户承担'), ('fund_amount', '基金承担')]:
                key = f'{kind}_{line["treatment_record"]}'
                self.fields[key] = forms.DecimalField(label=label, max_digits=16, decimal_places=2,
                    min_value=Decimal('0'), initial=line['amount'] if kind == 'patient_cash' else '0.00',
                    widget=forms.NumberInput(attrs={'step': '0.01', 'inputmode': 'decimal'}))
                keys.append(key)
            self.line_fields.append(dict(source=line, fields=[self[k] for k in keys]))

    def allocations(self):
        return [dict(treatment_record=line['treatment_record'],
            **{kind: self.cleaned_data[f'{kind}_{line["treatment_record"]}'] for kind in ('patient_cash', 'personal_account', 'fund_amount')})
            for line in self.source['lines']]


class SettlementReviewForm(forms.Form):
    decision = forms.ChoiceField(label='独立核对决定', choices=[('APPROVE', '分担核对通过'), ('REJECT', '未通过，保留原请求待处置')])
    reason = forms.CharField(label='核对依据及后续安排', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))
