from datetime import date
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import render,redirect,get_object_or_404
from django.http import Http404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET,require_POST,require_http_methods
from django.views.decorators.cache import never_cache
from adc_core.http_support import EXPECTED_ERRORS,add_error
from adc_core.proposals import workspace_binding
from adc_core.rules import RuleError
from registry.models import Clinic,Dentist
from finance.management_models import CostMonth,MonthlyCost,ManagementReport,COST_CATEGORIES
from finance.management_services import cost_scope
from finance import management_services as commands
from finance.management_selectors import monthly_report,workload
from finance.management_policy import month_bounds
from registry.profile_forms import ProfileConfirmForm


def selection(request):
    binding=workspace_binding(request.user,('MANAGER','FINANCE','HQ','DENTIST','FRONT_DESK'))
    role=binding['role'];clinics=Clinic.objects.filter(is_active=True)
    if role in ('MANAGER','FRONT_DESK'):clinics=clinics.filter(pk=binding['clinic'])
    elif role=='DENTIST':
        clinics=clinics.filter(Q(dentist_affiliations__dentist_id=request.user.dentist_id)|
            Q(availabilityslot__dentist_id=request.user.dentist_id)|Q(visits__dentist_id=request.user.dentist_id)).distinct()
    clinics=list(clinics.order_by('clinic_code'))
    choices=[(str(c.pk),c.public_contact['name']) for c in clinics]
    if role in ('FINANCE','HQ'):choices.append(('hq','总部成本中心'))
    key=request.GET.get('clinic',choices[0][0] if choices else '')
    if key not in dict(choices):raise PermissionDenied('请选择获授权的门店。')
    clinic_id=None if key=='hq' else int(key)
    cost_scope(request.user,clinic_id)
    raw=request.GET.get('period',timezone.localdate().strftime('%Y-%m'))
    try:year,month=map(int,raw.split('-'));month_bounds(year,month)
    except (ValueError,TypeError,RuleError):raise Http404('请选择有效月份。')
    return dict(role=role,choices=choices,clinic=clinic_id,clinic_key=key,year=year,month=month,period=f'{year:04}-{month:02}')


def destination(data):return reverse('management_home')+'?period='+data['period']+'&clinic='+data['clinic_key']


@login_required
@never_cache
@require_GET
def home(request):
    s=selection(request)
    facts=monthly_report(request.user,s['year'],s['month'],s['clinic'])
    dentist=request.GET.get('dentist','');service=request.GET.get('service','')
    from scheduling.service_content import positive_id
    if any(raw and positive_id(raw) is None for raw in (dentist,service)):raise Http404('筛选条件无效。')
    dentists=Dentist.objects.filter(Q(clinic_affiliations__clinic_id=s['clinic'])|Q(availabilityslot__clinic_id=s['clinic'])).distinct()
    if s['role']=='DENTIST':dentists=dentists.filter(pk=request.user.dentist_id)
    from scheduling.resource_models import BookingService
    services=BookingService.objects.filter(department__clinic_id=s['clinic'],is_active=True)
    if dentist and not dentists.filter(pk=dentist).exists():raise PermissionDenied('医师不在当前查询范围。')
    if service and not services.filter(pk=service).exists():raise PermissionDenied('服务不在当前门店范围。')
    work=workload(request.user,s['year'],s['month'],s['clinic'],dentist_id=int(dentist) if dentist else None,
        service_id=int(service) if service else None) if s['clinic'] else None
    period=CostMonth.objects.filter(year=s['year'],month=s['month'],clinic_id=s['clinic']).first()
    costs=period.costs.select_related('prepared_by','dentist','equipment_event__asset').order_by('-pk')[:100] if period and s['role'] in ('MANAGER','FINANCE','HQ') else []
    return render(request,'finance/management.html',dict(s,facts=facts,work=work,costs=costs,category_choices=COST_CATEGORIES,
        dentists=dentists,services=services,selected_dentist=dentist,selected_service=service,
        may_submit=s['role'] in ('MANAGER','FINANCE'),may_review=s['role']=='FINANCE',show_money=s['role']!='FRONT_DESK'))


class CostForm(forms.Form):
    category=forms.ChoiceField(label='成本类别',choices=COST_CATEGORIES)
    amount=forms.DecimalField(label='金额（元）',min_value=0,max_digits=16,decimal_places=2)
    dentist_id=forms.ModelChoiceField(label='直接归属医师（不选为门店公共成本）',queryset=Dentist.objects.none(),required=False)
    reference=forms.CharField(label='来源编号（同一凭据分行时标明行号）',max_length=160)
    basis=forms.CharField(label='期间、金额及归属依据',max_length=500,widget=forms.Textarea(attrs={'rows':3}))
    from equipment.models import EquipmentEvent
    equipment_event_id=forms.ModelChoiceField(label='设备维修／保养费用来源（可选）',queryset=EquipmentEvent.objects.none(),required=False)
    replaces_id=forms.IntegerField(label='修订原已确认成本编号（可选）',min_value=1,required=False)


def preview_response(request,preview,s):
    return render(request,'finance/management_confirm.html',dict(selection=s,preview=preview,
        form=ProfileConfirmForm(initial={'proposal_token':preview['proposal_token']})))


@login_required
@never_cache
@require_http_methods(['GET','POST'])
def cost_new(request):
    s=selection(request);cost_scope(request.user,s['clinic'],write=True)
    form=CostForm(request.POST or None)
    form.fields['dentist_id'].queryset=Dentist.objects.filter(clinic_affiliations__clinic_id=s['clinic']).distinct() if s['clinic'] else Dentist.objects.none()
    from equipment.models import EquipmentEvent
    form.fields['equipment_event_id'].queryset=EquipmentEvent.objects.filter(asset__clinic_id=s['clinic'],kind='SERVICE').select_related('asset') if s['clinic'] else EquipmentEvent.objects.none()
    form.fields['equipment_event_id'].label_from_instance=lambda e:f'{e.asset.name} · {e.performed_on}（费用来源 {e.pk}）'
    if request.method=='POST' and form.is_valid():
        try:
            d=dict(form.cleaned_data);replaces=d.pop('replaces_id');d['dentist_id']=d['dentist_id'].pk if d['dentist_id'] else None
            d['equipment_event_id']=d['equipment_event_id'].pk if d['equipment_event_id'] else None
            return preview_response(request,commands.prepare_cost(actor=request.user,year=s['year'],month=s['month'],
                clinic_id=s['clinic'],fields=d,replaces_id=replaces),s)
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'finance/management_cost.html',dict(selection=s,form=form))


@login_required
@require_POST
def action(request):
    s=selection(request);form=ProfileConfirmForm()
    try:
        common=dict(actor=request.user,year=s['year'],month=s['month'],clinic_id=s['clinic'])
        action=request.POST.get('action')
        if action=='OPEN':p=commands.prepare_month(**common)
        elif action=='COVERAGE':p=commands.prepare_coverage(**common,category=request.POST.get('category'),
            state=request.POST.get('state'),note=request.POST.get('note',''))
        elif action=='REPORT':p=commands.prepare_report(**common)
        elif action=='REVIEW':p=commands.prepare_decision(actor=request.user,cost_id=request.POST.get('cost_id'),
            decision=request.POST.get('decision'),note=request.POST.get('note',''))
        else:raise RuleError('请选择有效办理动作。')
        return preview_response(request,p,s)
    except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'finance/management_confirm.html',dict(selection=s,form=form),status=409)


@login_required
@require_POST
def confirm(request):
    form=ProfileConfirmForm(request.POST)
    if form.is_valid():
        try:
            event,replay=commands.confirm_management(actor=request.user,**form.cleaned_data)
            messages.success(request,'已返回原核算结果。' if replay else '核算办理完成。')
            return redirect(reverse('management_home')+f'?period={event.period.year:04}-{event.period.month:02}&clinic='+str(event.period.clinic_id or 'hq'))
        except EXPECTED_ERRORS as exc:add_error(form,exc)
    return render(request,'finance/management_confirm.html',{'form':form},status=409)


@login_required
@never_cache
@require_GET
def retained_report(request,pk):
    row=get_object_or_404(ManagementReport.objects.select_related('period'),pk=pk)
    ctx=cost_scope(request.user,row.period.clinic_id)
    if ctx.role not in ('MANAGER','FINANCE','HQ'):raise PermissionDenied('仅主管、财务和总部可查看整店留存月报。')
    old=row.period.reports.filter(sequence__lt=row.sequence).order_by('-sequence').first()
    keys=('production','confirmed_cost','profit','net_collections','unallocated')
    differences=[(k,old.snapshot.get(k),row.snapshot.get(k)) for k in keys if old and old.snapshot.get(k)!=row.snapshot.get(k)]
    return render(request,'finance/management_retained.html',{'report':row,'facts':row.snapshot,'differences':differences})


@login_required
@never_cache
@require_GET
def chain(request):
    from finance.management_selectors import chain_report
    raw=request.GET.get('period',timezone.localdate().strftime('%Y-%m'))
    try:year,month=map(int,raw.split('-'));month_bounds(year,month)
    except (ValueError,TypeError,RuleError):raise Http404('请选择有效月份。')
    data=chain_report(request.user,year,month)
    return render(request,'finance/management_chain.html',dict(report=data,period=f'{year:04}-{month:02}'))
