from urllib.parse import urlencode
from datetime import date
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render,redirect,get_object_or_404
from django.http import Http404
from django.views.decorators.http import require_http_methods,require_GET
from django.db.models import Q,Count
from django.utils import timezone
from adc_core.http_support import EXPECTED_ERRORS,add_error
from equipment.policies import manager_clinic
from scheduling.resource_forms import config_form,scoped_model,FORMS,ConfirmForm
from scheduling.resource_config import prepare_config,confirm_config,readiness
from scheduling.resource_models import *
from scheduling.resource_coordination import scope,plans_for,replacement_options,prepare_coordination,confirm_coordination
from scheduling.resource_candidates import candidates
from reception.services import contact_owners
from reception.models import ReceptionCase

LABELS={'department':'科室','hours':'开放时间','room':'诊室','service':'预约服务','binding':'椅位与设备位置','block':'临时停用'}

@login_required
@require_GET
def catalogue(request):
    clinic=manager_clinic(request.user)
    return render(request,'scheduling/resources.html',{'policy':ResourcePolicy.objects.filter(clinic_id=clinic).first(),
        'readiness':readiness(clinic),'groups':[(k,LABELS[k],list(scoped_model(clinic,k).order_by('pk'))) for k in FORMS],
        'actions':ResourceAction.objects.filter(clinic_id=clinic).select_related('actor').order_by('-pk')[:20]})

@login_required
@require_http_methods(['GET','POST'])
def configuration(request,kind):
    clinic=manager_clinic(request.user);target=request.GET.get('target') or request.POST.get('target') or None
    if target and not str(target).isdigit():raise Http404
    instance=get_object_or_404(scoped_model(clinic,kind),pk=target) if kind in FORMS and target else None
    form=config_form(clinic,kind,request.POST or None,instance=instance) if kind in FORMS else forms.Form(request.POST or None)
    if request.method=='POST' and request.POST.get('action')=='confirm':
        cf=ConfirmForm(request.POST)
        if cf.is_valid():
            try:confirm_config(actor=request.user,proposal_token=cf.cleaned_data['proposal_token'],confirmed=cf.cleaned_data['confirmed'])
            except EXPECTED_ERRORS as exc:add_error(cf,exc)
            else:messages.success(request,'资源配置已保存；原预约和邀约继续保留。');return redirect('resource_catalogue')
        return render(request,'scheduling/resource_confirm.html',{'form':cf,'failed':True},status=409)
    if request.method=='POST' and form.is_valid():
        # The public command validates a fresh clinic-scoped form again. Browser
        # fields carry no clinic authority and are never saved directly here.
        try:
            from scheduling.resource_config import _serialized
            preview=prepare_config(actor=request.user,kind=kind,fields=_serialized(form),target=int(target) if target else None)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'scheduling/resource_confirm.html',{'preview':preview,'form':ConfirmForm(initial={'proposal_token':preview['proposal_token']}),'target':target})
    return render(request,'scheduling/resource_form.html',{'title':LABELS.get(kind,{'start':'开始资源核对','activate':'启用统一资源控制','release_block':'结束临时停用'}.get(kind,'资源维护')),
        'form':form,'target':target,'kind':kind})

class CandidateForm(forms.Form):
    patient_no=forms.CharField(label='患者业务编号（咨询可留空）',required=False,max_length=40)
    service=forms.ModelChoiceField(label='预约服务',queryset=BookingService.objects.none())
    day=forms.DateField(label='预约日期',widget=forms.DateInput(format='%Y-%m-%d',attrs={'type':'date'}))
    from registry.models import Dentist
    dentist=forms.ModelChoiceField(label='医师偏好（可选）',required=False,queryset=Dentist.objects.none())
    def __init__(self,*args,clinic,**kwargs):
        super().__init__(*args,**kwargs);self.fields['service'].queryset=BookingService.objects.filter(department__clinic_id=clinic,is_active=True).select_related('department')
        from scheduling.models import AvailabilitySlot
        self.fields['dentist'].queryset=self.Dentist.objects.filter(is_active=True,pk__in=AvailabilitySlot.objects.filter(clinic_id=clinic,is_active=True).values('dentist_id'))

@login_required
@require_GET
def candidate_list(request):
    clinic=scope(request.user,front=True);form=CandidateForm(request.GET or None,clinic=clinic,initial={'day':timezone.localdate()});rows=[]
    if form.is_valid():
        try:
            from patients.models import Patient
            p=Patient.objects.get(patient_no=form.cleaned_data['patient_no'],is_active=True) if form.cleaned_data['patient_no'] else None
            rows=candidates(clinic_id=clinic,service_id=form.cleaned_data['service'].pk,day=form.cleaned_data['day'],
                dentist_id=form.cleaned_data['dentist'].pk if form.cleaned_data['dentist'] else None,patient_id=p.pk if p else None,horizon=False)
            for r in rows:r['choose']='?'+urlencode({'patient_no':p.patient_no if p else '', 'service':r['service'].pk,'slot':r['slot_id'],
                'start':timezone.localtime(r['start']).strftime('%Y-%m-%dT%H:%M'),'end':timezone.localtime(r['end']).strftime('%Y-%m-%dT%H:%M')})
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'scheduling/resource_candidates.html',{'form':form,'rows':rows})

@login_required
@require_GET
def coordination_list(request):
    clinic=scope(request.user)
    issues=ResourceCoordination.objects.filter(plan__in=plans_for(request.user),state__in=['OPEN','CONTACT']).select_related('plan__visit','plan__offer','asset','owner').order_by('due_at','pk')
    return render(request,'scheduling/resource_coordination_list.html',{'issues':issues[:100],'now':timezone.now(),'may_act':request.workspace.role=='FRONT_DESK'})

class CoordinationForm(forms.Form):
    action=forms.ChoiceField(label='办理方式',choices=[('OPEN','记录接诊资源协调及联系期限'),('REPLACE','同医师同时间替换资源'),('CONTACT','登记联系责任及期限'),('RESOLVE','核实解决结果')])
    assets=forms.ChoiceField(label='已核对的兼容替换组合',required=False,choices=[('','请选择')])
    issue=forms.ChoiceField(label='原协调事项',required=False,choices=[('','请选择')])
    asset=forms.ChoiceField(label='本次涉及的原预约设备',required=False,choices=[('','请选择')])
    owner=forms.ModelChoiceField(label='联系负责人',required=False,queryset=contact_owners(-1))
    due_at=forms.DateTimeField(label='联系期限',required=False,widget=forms.DateTimeInput(format='%Y-%m-%dT%H:%M',attrs={'type':'datetime-local'}))
    note=forms.CharField(label='核实或交接依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,clinic,**kwargs):
        super().__init__(*args,**kwargs);self.fields['owner'].queryset=contact_owners(clinic)
    def clean(self):
        d=super().clean()
        for key in (['assets'] if d.get('action')=='REPLACE' else ['asset','owner','due_at'] if d.get('action')=='OPEN' else ['issue','owner','due_at'] if d.get('action')=='CONTACT' else ['issue']):
            if not d.get(key):self.add_error(key,'请填写此项。')
        if d.get('assets'):
            try:d['assets']=[int(x.strip()) for x in d['assets'].split(',')]
            except ValueError:self.add_error('assets','请使用数字编号，用逗号分隔。')
        return d

@login_required
@require_http_methods(['GET','POST'])
def coordination_detail(request,pk):
    clinic=scope(request.user,front=True);plan=get_object_or_404(plans_for(request.user),pk=pk)
    if request.method=='POST' and request.POST.get('confirm'):
        f=ConfirmForm(request.POST)
        if f.is_valid():
            try:confirm_coordination(actor=request.user,proposal_token=f.cleaned_data['proposal_token'],confirmed=f.cleaned_data['confirmed'])
            except EXPECTED_ERRORS as exc:add_error(f,exc)
            else:messages.success(request,'协调结果已保存；原承诺和历次资源方案保留。');return redirect('resource_coordination_list')
        return render(request,'scheduling/resource_confirm.html',{'form':f,'failed':True},status=409)
    problem='';options=[]
    try:_,options=replacement_options(request.user,pk)
    except EXPECTED_ERRORS as exc:problem=str(exc)
    for x in options:x['ids']=','.join(str(r['id']) for r in x['resources'])
    form=CoordinationForm(request.POST or None,clinic=clinic)
    form.fields['issue'].choices=[('','请选择原事项')]+[(str(i.pk),'事项 #'+str(i.pk)+' · '+i.asset.name+' · '+i.get_state_display()) for i in plan.coordination.filter(state__in=['OPEN','CONTACT']).select_related('asset')]
    form.fields['asset'].choices=[('','请选择原预约设备')]+[(str(c.asset_id),c.asset.name+'（'+c.asset.asset_code+'）') for c in plan.claims.select_related('asset')]
    form.fields['assets'].choices=[('','请选择兼容方案')]+[(x['ids'],x['room']['name']+' · '+'、'.join(r['name']+'（'+r['code']+'）' for r in x['resources'])) for x in options]
    if request.method=='POST' and form.is_valid():
        d=dict(form.cleaned_data);action=d.pop('action')
        if d.get('owner'):d['owner']=d['owner'].pk
        try:preview=prepare_coordination(actor=request.user,plan_id=pk,action=action,fields=d)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'scheduling/resource_confirm.html',{'preview':preview,'coordination':True,'form':ConfirmForm(initial={'proposal_token':preview['proposal_token']})})
    return render(request,'scheduling/resource_coordination_detail.html',{'plan':plan,'options':options,'problem':problem,'form':form,
        'issues':plan.coordination.select_related('owner','asset'),'history':ResourcePlan.objects.filter(visit_id=plan.visit_id) if plan.visit_id else ResourcePlan.objects.filter(offer_id=plan.offer_id)})

@login_required
@require_GET
def summary(request):
    from django.core.exceptions import PermissionDenied
    if request.workspace.role not in ('HQ','MANAGER'):raise PermissionDenied
    policies=ResourcePolicy.objects.all();cases=ReceptionCase.objects.all()
    if request.workspace.role=='MANAGER':
        clinic=manager_clinic(request.user);policies=policies.filter(clinic_id=clinic);cases=cases.filter(clinic_id=clinic)
    from reception.models import STATES
    reception=list(cases.values('clinic__name','state').annotate(count=Count('pk')))
    for row in reception:row['label']=dict(STATES).get(row['state'],row['state'])
    return render(request,'scheduling/resource_summary.html',{'rows':[dict(row,label=dict(ResourcePolicy._meta.get_field('state').choices).get(row['state'],row['state'])) for row in policies.values('clinic__name','state').annotate(count=Count('clinic'))],
        'reception':reception,'overdue':cases.exclude(state__in=['BOOKED','UNBOOKED','WITHDRAWN']).filter(due_at__lt=timezone.now()).count()})


class MappingForm(forms.Form):
    kind=forms.ChoiceField(label='原承诺类型',choices=[('visit','正式预约'),('offer','有效邀约')])
    source_id=forms.IntegerField(label='原记录编号',min_value=1)
    service=forms.ModelChoiceField(label='本次已核实的预约服务',queryset=BookingService.objects.none())
    note=forms.CharField(label='核实依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    def __init__(self,*args,clinic,**kwargs):
        super().__init__(*args,**kwargs);self.fields['service'].queryset=BookingService.objects.filter(department__clinic_id=clinic,is_active=True)

@login_required
@require_http_methods(['GET','POST'])
def mapping(request):
    clinic=manager_clinic(request.user);form=MappingForm(request.POST or None,clinic=clinic,
        initial={'kind':request.GET.get('kind','visit'),'source_id':request.GET.get('source','')})
    from scheduling.resource_mapping import prepare_mapping,confirm_mapping
    if request.method=='POST' and request.POST.get('action')=='confirm':
        cf=ConfirmForm(request.POST)
        if cf.is_valid():
            try:confirm_mapping(actor=request.user,proposal_token=cf.cleaned_data['proposal_token'],confirmed=cf.cleaned_data['confirmed'])
            except EXPECTED_ERRORS as exc:add_error(cf,exc)
            else:messages.success(request,'原承诺的资源已逐项核实，未改写原始预约事实。');return redirect('resource_catalogue')
        return render(request,'scheduling/resource_confirm.html',{'form':cf,'failed':True},status=409)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:preview=prepare_mapping(actor=request.user,kind=d['kind'],source_id=d['source_id'],service_id=d['service'].pk,note=d['note'])
        except EXPECTED_ERRORS as exc:add_error(form,exc)
        else:return render(request,'scheduling/resource_confirm.html',{'preview':preview,'form':ConfirmForm(initial={'proposal_token':preview['proposal_token']})})
    return render(request,'scheduling/resource_form.html',{'title':'逐项核实原承诺资源','form':form})
