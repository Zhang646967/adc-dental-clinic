from django import forms
from decimal import Decimal
from types import SimpleNamespace
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_http_methods,require_GET
from accounts.policies import bindings
from adc_core.http_support import EXPECTED_ERRORS,add_error
from care.models import CorrectionRequest,Invoice,TreatmentRecord
from care.views import _own_visit
from care.corrections import request_line_correction,review_correction
from urllib.parse import urlencode


class CorrectionFilterForm(forms.Form):
    queue = forms.ChoiceField(label='办理范围', required=False)

    def __init__(self, *args, finance, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['queue'].choices = [('all', '全部历史'), ('open', '待审核申请')]
        if finance:
            self.fields['queue'].choices.append(('review', '可由我独立审核'))

class RequestForm(forms.Form):
    expected_version=forms.IntegerField(min_value=0,widget=forms.HiddenInput)
    line_id=forms.TypedChoiceField(label='当前账单中的治疗行',coerce=int)
    quantity=forms.DecimalField(label='更正后数量',max_digits=12,decimal_places=3,min_value=Decimal("0.001"))
    unit_price=forms.DecimalField(label='更正后单价（元）',max_digits=12,decimal_places=2,min_value=0)
    reason=forms.CharField(label='误录原因及事实依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='我确认仍是同一项目、同一患者；这些数值反映实际提供的服务')

class ReviewForm(forms.Form):
    decision=forms.ChoiceField(label='审核决定',choices=[('approve','批准并发布新版本'),('reject','拒绝并保留原账单')])
    reason=forms.CharField(label='审核说明',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    confirmed=forms.BooleanField(label='我已对照原版与更正草稿，并核对金额和依据')

def correction_access(user,req):
    if bindings(user).filter(role='FINANCE',scope_kind='CHAIN').exists():return
    if req.requester_id==user.pk and bindings(user).filter(role='DENTIST',scope_kind='SELF_DENTIST',user__dentist_id=req.visit.dentist_id).exists():return
    raise PermissionDenied('没有该更正的访问权限。')

@login_required
@require_GET
def listing(request):
    grants=bindings(request.user)
    qs=CorrectionRequest.objects.select_related('visit','requester','base_record_version').filter(kind='RECORD_CONTENT')
    finance = grants.filter(role='FINANCE',scope_kind='CHAIN').exists()
    if finance:pass
    elif grants.filter(role='DENTIST',scope_kind='SELF_DENTIST').exists():qs=qs.filter(requester=request.user,visit__dentist_id=request.user.dentist_id)
    else:raise PermissionDenied
    form = CorrectionFilterForm(request.GET, finance=finance)
    valid = form.is_valid()
    if not valid:
        qs = qs.none()
    elif form.cleaned_data['queue'] in ('open', 'review'):
        qs = qs.filter(status='OPEN')
        if form.cleaned_data['queue'] == 'review':
            qs = qs.exclude(requester_id=request.user.pk)
    from django.core.paginator import Paginator
    queue = form.cleaned_data.get('queue') or 'all'
    qs = qs.order_by('requested_at', 'pk') if queue != 'all' else qs.order_by('-requested_at', '-pk')
    return render(request,'care/corrections.html',{'page':Paginator(qs,20).get_page(request.GET.get('page')),
        'filter_form':form,'filters_valid':valid,'pagination_query':urlencode({'queue':queue})}, status=200 if valid else 400)

@login_required
@require_http_methods(['GET','POST'])
def create(request,pk):
    v=_own_visit(request.user,pk)
    invoice=get_object_or_404(Invoice.objects.select_related('current_record_version'),visit=v)
    lines=list(invoice.current_record_version.treatment_lines.all())
    form=RequestForm(request.POST or None,initial={'expected_version':v.lock_version})
    form.fields['line_id'].choices=[(r.pk,f'第{r.line_no}行 · {r.name_snapshot} / 数量{r.quantity} / 单价{r.unit_price}') for r in lines]
    if request.method=='POST' and form.is_valid():
        data=dict(form.cleaned_data);data.pop('confirmed')
        try:req=request_line_correction(actor=request.user,visit_id=pk,**data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return redirect('correction_detail',pk=req.pk)
    return render(request,'care/correction_create.html',{'form':form,'visit':v,'invoice':invoice})

@login_required
@require_http_methods(['GET','POST'])
def detail(request,pk):
    req=get_object_or_404(CorrectionRequest.objects.select_related('visit','requester','base_record_version','new_version'),pk=pk,kind='RECORD_CONTENT')
    correction_access(request.user,req)
    can_review=bindings(request.user).filter(role='FINANCE',scope_kind='CHAIN').exists() and request.user.pk!=req.requester_id
    form=ReviewForm(request.POST or None)
    if request.method=='POST':
        if not can_review:raise PermissionDenied
        if form.is_valid():
            data=dict(form.cleaned_data);data.pop('confirmed')
            try:invoice=review_correction(actor=request.user,request_id=pk,**data)
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            else:
                messages.success(request,'审核结果已保存。旧版未被覆盖，当前收入按有效版本重新汇总。')
                return redirect('correction_detail',pk=pk)
    # Only billing columns, no allergy or clinical narrative in financial review context.
    columns=('line_no','name_snapshot','quantity','unit_price','line_amount')
    request_summary=SimpleNamespace(pk=req.pk,status=req.status,reason=req.reason,requested_at=req.requested_at,
        requester=SimpleNamespace(username=req.requester.username),get_status_display=req.get_status_display())
    return render(request,'care/correction_detail.html',{'req':request_summary,'old_lines':list(req.base_record_version.treatment_lines.values(*columns)),
        'new_lines':list(req.new_version.treatment_lines.values(*columns)),'old_total':req.base_record_version.total_amount,
        'new_total':req.new_version.total_amount,'can_review':can_review and req.status=='OPEN','form':form})
