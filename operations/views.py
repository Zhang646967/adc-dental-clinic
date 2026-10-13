from datetime import timedelta
from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from operations.selectors import operation_report,allowed_clinics
from operations.policies import period_bounds
from adc_core.rules import RuleError

class FilterForm(forms.Form):
    start=forms.DateField(label='预约开始日期',widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='预约结束日期（包含当天）',widget=forms.DateInput(attrs={'type':'date'}))
    clinic_id=forms.TypedChoiceField(label='诊所范围',required=False,coerce=int,empty_value=None)
    def __init__(self,*a,clinics,**kw):
        super().__init__(*a,**kw)
        self.fields['clinic_id'].choices=[('','所有获授权诊所')]+[(c.pk,c.name) for c in clinics]
    def clean(self):
        data=super().clean()
        if 'start' in data and 'end' in data:
            try:period_bounds(data['start'],data['end'])
            except RuleError as exc:raise forms.ValidationError(str(exc))
        return data

@login_required
@require_GET
def dashboard(request):
    today=timezone.localdate()
    form=FilterForm(request.GET if request.GET else {'start':today.replace(day=1).isoformat(),'end':today.isoformat()},clinics=allowed_clinics(request.user))
    report=None
    if form.is_valid():report=operation_report(request.user,form.cleaned_data['start'],form.cleaned_data['end'],form.cleaned_data['clinic_id'])
    return render(request,'operations/dashboard.html',{'form':form,'report':report})
