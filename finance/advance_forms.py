from decimal import Decimal

from django import forms

from finance.advance_services import MAX_LINES


class AllocationBasisForm(forms.Form):
    basis = forms.CharField(label='分配依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class AllocationLineForm(forms.Form):
    invoice = forms.TypedChoiceField(label='本店账单', coerce=int)
    amount = forms.DecimalField(label='本次抵扣（CNY）', min_value=Decimal('0.01'), max_digits=16, decimal_places=2)

    def __init__(self, *args, invoices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['invoice'].choices = [('', '请选择账单')] + invoices


AllocationLines = forms.formset_factory(AllocationLineForm, extra=MAX_LINES, max_num=MAX_LINES,
                                        validate_max=True, absolute_max=MAX_LINES)


class AllocationReviewForm(forms.Form):
    decision = forms.ChoiceField(label='复核决定', choices=[('approve', '批准抵扣'), ('reject', '拒绝分配')])
    reason = forms.CharField(label='独立复核依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class ReversalBasisForm(AllocationBasisForm):
    basis = forms.CharField(label='撤销依据', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))


class ReversalReviewForm(AllocationReviewForm):
    decision = forms.ChoiceField(label='复核决定', choices=[('approve', '批准撤销'), ('reject', '拒绝撤销')])
