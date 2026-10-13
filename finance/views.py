import csv
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse,Http404
from django.shortcuts import render,redirect,get_object_or_404
from django.views.decorators.http import require_GET,require_http_methods
from accounts.policies import bindings
from adc_core.http_support import EXPECTED_ERRORS,add_error
from finance.models import Quarter,DentistQuarterCost
from finance.forms import QuarterForm,MemberForm,ConfirmedForm,CostForm
from accounts.finance_access import require_finance_read
from finance.selectors import quarter_report
from finance.policies import safe_csv_cell
from finance import services

def _can_write(user):
    return bindings(user).filter(role='FINANCE',scope_kind='CHAIN').exists()

@login_required
@require_http_methods(['GET','POST'])
def quarters(request):
    require_finance_read(request.user)
    form=QuarterForm(request.POST or None)
    if request.method=='POST':
        if not _can_write(request.user): raise PermissionDenied
        if form.is_valid():
            data=dict(form.cleaned_data);data.pop('confirmed')
            try: q=services.create_quarter(actor=request.user,**data)
            except EXPECTED_ERRORS as exc: add_error(form,exc)
            else: return redirect('quarter_detail',pk=q.pk)
    return render(request,'finance/quarters.html',{'quarters':Quarter.objects.order_by('-year','-quarter_no'),'form':form,'can_write':_can_write(request.user)})

@login_required
@require_http_methods(['GET','POST'])
def detail(request,pk):
    report=quarter_report(request.user,pk)
    action=request.POST.get('action')
    member=MemberForm(request.POST if action=='add' else None,initial={'expected_version':report.lock_version})
    confirm=ConfirmedForm(request.POST if action=='confirm' else None,initial={'expected_version':report.lock_version})
    form={'add':member,'confirm':confirm}.get(action)
    if request.method=='POST':
        if not _can_write(request.user): raise PermissionDenied
        if form is None: raise PermissionDenied('未知财务操作。')
        if form.is_valid():
            data=dict(form.cleaned_data);data.pop('confirmed')
            try:
                if action=='add':
                    data['dentist_id']=data['dentist_id'].pk;services.add_member(actor=request.user,quarter_id=pk,**data)
                else: services.confirm_roster(actor=request.user,quarter_id=pk,**data)
            except EXPECTED_ERRORS as exc: add_error(form,exc)
            else:
                messages.success(request,'已保存；统计将依据当前数据重新计算。');return redirect('quarter_detail',pk=pk)
    return render(request,'finance/detail.html',{'report':report,'member_form':member,'confirm_form':confirm,'can_write':_can_write(request.user)})

@login_required
@require_http_methods(['GET','POST'])
def cost(request,pk,cost_pk):
    report=quarter_report(request.user,pk)
    if not _can_write(request.user): raise PermissionDenied
    c=next((r for r in report.rows if r.id==cost_pk),None)
    if c is None:
        raise Http404("成本记录不属于所选季度。")
    action=request.POST.get('action')
    form=CostForm(request.POST if action=='save' else None,initial={'expected_version':report.lock_version,'supply_cost':c.supply,'operating_expense':c.operating,'notes':c.notes})
    confirm=ConfirmedForm(request.POST if action=='confirm' else None,initial={'expected_version':report.lock_version})
    active={'save':form,'confirm':confirm}.get(action)
    if request.method=='POST':
        if active is None: raise PermissionDenied
        if active.is_valid():
            data=dict(active.cleaned_data);data.pop('confirmed')
            try:
                command=services.save_cost if action=='save' else services.confirm_cost
                command(actor=request.user,quarter_id=pk,cost_id=cost_pk,**data)
            except EXPECTED_ERRORS as exc:add_error(active,exc)
            else:return redirect('quarter_cost',pk=pk,cost_pk=cost_pk)
    return render(request,'finance/cost.html',{'report':report,'cost':c,'form':form,'confirm_form':confirm})

@login_required
@require_GET
def export(request,pk):
    report=quarter_report(request.user,pk)
    response=HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition']=f'attachment; filename="ADC-{report.year}-Q{report.number}.csv"'
    response.write('\ufeff');writer=csv.writer(response)
    writer.writerow(['口径',report.policy_version,'查询时间',report.as_of.isoformat(),'开单金额≠实收款','期间进行中',str(report.in_progress)])
    writer.writerow(['状态','可测算' if report.result.ready else '数据不完整','；'.join(report.result.reasons)])
    writer.writerow(['员工编号','牙医','成本状态','开单收入(CNY)','用品成本','运营费用','账单数'])
    for r in report.rows:
        writer.writerow([safe_csv_cell(r.employee_no),safe_csv_cell(r.dentist_name),r.status,str(r.income),'' if r.supply is None else str(r.supply),'' if r.operating is None else str(r.operating),r.invoice_count])
    for row in report.unlisted: writer.writerow([safe_csv_cell(row['employee_no']),safe_csv_cell(row['name']),'未纳入清单','','','',''])
    writer.writerow(['总开单收入',str(report.result.income)])
    if report.result.ready:
        writer.writerow(['总体利润贡献',str(report.result.profit)])
        writer.writerow(['总体基金测算',str(report.result.fund) if report.result.fund is not None else '零/负利润政策待确认'])
    return response
