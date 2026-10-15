from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError
from django.http import Http404
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.http import require_GET,require_http_methods
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.cache import never_cache
from adc_core.http_support import EXPECTED_ERRORS,add_error
from equipment.forms import EquipmentRegisterForm,EquipmentActionForm,ExplicitProposalForm
from equipment.selectors import equipment_listing,equipment_detail
from equipment.services import prepare_registration,prepare_change,confirm_equipment
from equipment.policies import manager_clinic
from equipment.fees import fee_worklist
from equipment.schedule import maintenance_schedule

@login_required
@never_cache
@require_GET
def expenses(request):
    try:data=fee_worklist(request.user,request.GET.get('state',''),request.GET.get('page','1'),request.GET.get('asset',''))
    except EXPECTED_ERRORS:
        return render(request,'business/problem.html',{'problem':'设备费用筛选无效，请重新查询。'},status=400)
    return render(request,'equipment/expenses.html',data)

@login_required
@never_cache
@require_GET
def schedule(request,pk):
    try:data=maintenance_schedule(request.user,pk,request.GET.get('slot',''),request.GET.get('page','1'))
    except EXPECTED_ERRORS:raise Http404
    return render(request,'equipment/schedule.html',data)

@login_required
@require_GET
def listing(request):
    try:data=equipment_listing(request.user,request.GET.get('state',''),request.GET.get('due',''),request.GET.get('page','1'))
    except EXPECTED_ERRORS:
        return render(request,'business/problem.html',{'problem':'设备筛选无效，请从设备首页重新查询。'},status=400)
    return render(request,'equipment/list.html',data)

@login_required
@require_GET
def detail(request,pk):
    try:data=equipment_detail(request.user,pk)
    except EXPECTED_ERRORS:raise Http404
    return render(request,'equipment/detail.html',data)

def _edit(request,pk=None):
    manager_clinic(request.user)
    data=equipment_detail(request.user,pk) if pk else {}
    action=request.POST.get('action','preview')
    title='设备登记' if pk is None else '设备状态与保养记录'
    if request.method=='POST' and action=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:
                asset,repeated=confirm_equipment(actor=request.user,**form.cleaned_data,
                    expected_action='register' if pk is None else 'change',expected_asset_id=pk)
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            except DatabaseError:
                return render(request,'business/problem.html',{'problem':'暂不能核实保存结果，请先打开设备清单查看历史，不要重复登记。'},status=503)
            else:
                messages.success(request,'此前已保存，返回设备当前状态。' if repeated else '设备记录已保存；未自动改动预约或记账。')
                return redirect('equipment_detail',pk=asset.pk)
        return render(request,'business/proposal.html',{'title':title,'form':form,'recovery_route':'equipment_list','button':'确认保存设备记录'},status=409)
    if request.method=='POST' and action!='preview':raise PermissionDenied('未知设备操作。')
    if pk is not None and data['asset'].state=='RETIRED':
        return render(request,'business/problem.html',{'problem':'该设备已永久退役，请从台账核对保留历史。'},status=409)
    form=(EquipmentRegisterForm if pk is None else EquipmentActionForm)(
        request.POST if request.method=='POST' else None,
        initial={'acquired_on':timezone.localdate(),'performed_on':timezone.localdate()},
        **({'state':data['asset'].state} if pk is not None else {}))
    if request.method=='POST' and form.is_valid():
        try:
            preview=prepare_registration(actor=request.user,**form.cleaned_data) if pk is None else prepare_change(actor=request.user,asset_id=pk,**form.cleaned_data)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            fields=preview['fields']
            summary=[('当前诊所',request.workspace.clinic.name)]
            for key,label in [('asset_code','设备编号'),('name','设备名称'),('location','位置'),('category','类别'),('kind','操作'),('previous_state','原状态'),('next_state','新状态'),('acquired_on','接收日'),('performed_on','事实日'),('acquisition_cost','购置成本（CNY）'),('cost','本次费用（CNY）'),('next_service_due','下次保养日'),('note','核对依据')]:
                if key in fields:
                    val=fields[key]
                    from equipment.models import STATES,CATEGORIES
                    if key in ('previous_state','next_state'):val=dict(STATES).get(val,'无')
                    elif key=='category':val=dict(CATEGORIES).get(val,val)
                    elif key=='kind':val={'MAINTENANCE':'送修','SERVICE':'保养完成／恢复','RETIRE':'退役'}.get(val,val)
                    summary.append((label,val))
            return render(request,'business/proposal.html',{'title':preview['title'],'summary':summary,'form':ExplicitProposalForm(initial={'proposal_token':preview['proposal_token']}),'button':'确认保存设备记录','recovery_route':'equipment_list'})
    return render(request,'equipment/edit.html',dict(data,title=title,form=form))

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def register(request):return _edit(request)

@login_required
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def change(request,pk):
    try:return _edit(request,pk)
    except EXPECTED_ERRORS:raise Http404
