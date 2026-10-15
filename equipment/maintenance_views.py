from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Count,Q,Exists,OuterRef
from django.http import Http404
from django.shortcuts import render,redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET,require_http_methods
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.snapshots import reporting_snapshot
from equipment.forms import ExplicitProposalForm
from accounts.models import UserAccount,RoleAssignment
from equipment.fees import source_id
from equipment.models import EquipmentAsset
from equipment.maintenance_models import ACTIVE,STATES,ACTIONS
from equipment.policies import manager_clinic
from equipment.maintenance_services import order_scope,owners,available_actions,prepare_maintenance,confirm_maintenance

class MaintenanceForm(forms.Form):
    note=forms.CharField(label='本次办理说明（仅合成案例）',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,action,clinic,**kwargs):
        super().__init__(*args,**kwargs)
        if action in ('OPEN','ASSIGN'):
            self.fields['owner']=forms.ModelChoiceField(label='本店维护负责人',queryset=owners(clinic),help_text='负责人负责内部跟进；账号授权不代表维修专业资质。')
            self.fields['due']=forms.DateField(label='办理期限（北京时间）',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
        if action=='OPEN':self.fields['issue']=forms.CharField(label='维修问题与处理范围',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
        if action=='SUBMIT':
            self.fields['performed']=forms.DateField(label='维修完成事实日',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
            self.fields['cost']=forms.DecimalField(label='本次维修费用（CNY）',max_digits=16,decimal_places=2,min_value=0,required=False,help_text='空白表示未知，0 表示明确无费用；验收后仍需单独财务审核。')
            self.fields['next_due']=forms.DateField(label='下次保养到期日',required=False,widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
            self.fields['evidence']=forms.CharField(label='维修事实、检查结果和凭据编号',max_length=500,widget=forms.Textarea(attrs={'rows':3}),help_text='只填设备事实与合成凭据，不填患者资料、银行信息或凭据秘密。')
            self.fields['schedule_checked']=forms.BooleanField(label='已核对出诊影响及后续协调事项；涉及接收暂停／恢复时另行明确办理。')
        self.order_fields([k for k in ('issue','owner','due','performed','cost','next_due','evidence','schedule_checked','note') if k in self.fields])

@login_required
@never_cache
@require_GET
def listing(request):
    state=request.GET.get('state','active');due=request.GET.get('due','');mine=request.GET.get('owner','');asset=request.GET.get('asset','')
    if state not in ('','active',*[s for s,l in STATES]) or due not in ('','overdue') or mine not in ('','mine'):
        return render(request,'business/problem.html',{'problem':'维护工单筛选无效。'},status=400)
    if mine and request.workspace.role!='MANAGER':raise PermissionDenied
    try:asset_id=source_id(asset) if asset else None
    except EXPECTED_ERRORS:return render(request,'business/problem.html',{'problem':'设备筛选无效。'},status=400)
    with reporting_snapshot():
        qs=order_scope(request.user);today=timezone.localdate()
        if asset_id:qs=qs.filter(asset_id=asset_id)
        totals=qs.aggregate(active=Count('pk',filter=Q(state__in=ACTIVE)),ready=Count('pk',filter=Q(state='READY')),overdue=Count('pk',filter=Q(state__in=ACTIVE,due_on__lt=today)))
        if state=='active':qs=qs.filter(state__in=ACTIVE)
        elif state:qs=qs.filter(state=state)
        if due:qs=qs.filter(state__in=ACTIVE,due_on__lt=today)
        if mine:qs=qs.filter(assigned_to=request.user)
        qs=qs.annotate(owner_authorized=Exists(RoleAssignment.objects.filter(user_id=OuterRef('assigned_to_id'),clinic_id=OuterRef('asset__clinic_id'),role='MANAGER',scope_kind='CLINIC',is_active=True,user__is_active=True)))
        page=Paginator(qs.order_by('due_on','pk'),20).get_page(request.GET.get('page','1'));rows=list(page.object_list)
        for row in rows:row.owner_available=row.owner_authorized
    from urllib.parse import urlencode
    return render(request,'equipment/maintenance_list.html',dict(rows=rows,page_obj=page,totals=totals,today=today,state=state,due=due,mine=mine,asset=asset,states=STATES,page_query=urlencode(dict(state=state,due=due,owner=mine,asset=asset))))

def _detail(actor,pk,page='1'):
    with reporting_snapshot():
        row=order_scope(actor).get(pk=pk)
        paginator=Paginator(row.actions.select_related('actor').order_by('-sequence'),20).get_page(page)
        history=list(paginator.object_list)
        labels=dict(UserAccount.objects.filter(pk__in=[e.snapshot['owner'] for e in history]).values_list('pk','username'))
        for event in history:event.owner_label=labels.get(event.snapshot['owner'],'历史负责人')
        return dict(row=row,asset=row.asset,actions=available_actions(actor,row),history=history,page_obj=paginator,
            owner_available=owners(row.asset.clinic_id).filter(pk=row.assigned_to_id).exists(),today=timezone.localdate())

@login_required
@never_cache
@require_GET
def detail(request,pk):
    try:data=_detail(request.user,pk,request.GET.get('page','1'))
    except EXPECTED_ERRORS:raise Http404
    return render(request,'equipment/maintenance_detail.html',data)

def _edit(request,asset_id=None,pk=None,action='OPEN'):
    clinic=manager_clinic(request.user)
    if action not in dict(ACTIONS) or (pk is not None and action=='OPEN'):raise Http404
    try:
        data=_detail(request.user,pk) if pk else dict(asset=EquipmentAsset.objects.select_related('clinic').get(pk=asset_id,clinic_id=clinic),row=None)
    except EXPECTED_ERRORS:raise Http404
    asset=data['asset'];row=data['row'];title=dict(ACTIONS)[action]
    phase=request.POST.get('action','preview')
    if request.method=='POST' and phase=='confirm':
        form=ExplicitProposalForm(request.POST)
        if form.is_valid():
            try:result,repeated=confirm_maintenance(actor=request.user,expected_asset_id=asset.pk,expected_order_id=pk,expected_action=action,**form.cleaned_data)
            except EXPECTED_ERRORS as exc:add_error(form,exc)
            except DatabaseError:return render(request,'business/problem.html',{'problem':'暂不能核实维护结果，请查看工单历史；不要重复创建或推断设备已恢复。'},status=503)
            else:
                messages.success(request,'此前已保存，显示当前工单。' if repeated else '维护办理记录已保存。')
                return redirect('maintenance_detail',pk=result.pk)
        return render(request,'business/proposal.html',dict(title=title,form=form,button='确认维护办理',recovery_route='maintenance_list'),status=409)
    if request.method=='POST' and phase!='preview':raise PermissionDenied
    initial=dict(owner=row.assigned_to_id if row else request.user.pk,due=row.due_on if row else timezone.localdate(),performed=timezone.localdate())
    form=MaintenanceForm(request.POST if request.method=='POST' else None,initial=initial,action=action,clinic=clinic)
    if request.method=='POST' and form.is_valid():
        fields=dict(form.cleaned_data);note=fields.pop('note')
        if 'owner' in fields:fields['owner']=fields['owner'].pk
        try:p=prepare_maintenance(actor=request.user,asset_id=asset.pk,order_id=pk,action=action,fields=fields,note=note)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:
            summary=[('设备',asset.asset_code),('诊所',asset.clinic.name),('操作',title),('当前设备状态',asset.get_state_display())]
            if row:summary.extend([('工单',row.pk),('负责人',row.assigned_to.username),('办理期限',row.due_on)])
            labels={'owner':'拟分配负责人','due':'办理期限','issue':'维修范围','performed':'完成事实日','cost':'本次费用（CNY）','next_due':'下次保养日','evidence':'维修事实与凭据','schedule_checked':'已明确核对出诊协调事项'}
            for k,v in p['fields'].items():summary.append((labels[k],owners(clinic).get(pk=v).username if k=='owner' else '未知／未登记' if v is None else '已确认' if k=='schedule_checked' else v))
            if action=='APPROVE':summary.extend([('负责人提交事实',row.completion_note),('完成日',row.performed_on),('费用（CNY）','未知／未登记' if row.cost is None else row.cost),('下次保养日',row.next_service_due or '未登记'),('确认后','记录独立验收，生成对应保养事件，并将设备恢复为在用；费用申请与排班变更另行办理')])
            elif action=='CANCEL':summary.append(('确认后','取消本工单；设备保持维修中，后续送修跟进或退役另行明确办理'))
            else:summary.append(('确认后','保留办理历史；设备继续维修中，等待独立验收'))
            summary.append(('本次说明',note))
            return render(request,'business/proposal.html',dict(title=title,summary=summary,form=ExplicitProposalForm(initial={'proposal_token':p['proposal_token']}),button='确认维护办理',recovery_route='maintenance_list'))
    return render(request,'equipment/maintenance_edit.html',dict(data,title=title,form=form,action=action))

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def create(request,asset_id):return _edit(request,asset_id=asset_id)

@login_required
@never_cache
@sensitive_post_parameters()
@require_http_methods(['GET','POST'])
def action(request,pk,action):return _edit(request,pk=pk,action=action.upper())
