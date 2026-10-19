"""Manager-owned resource preparation with explicit preview and retained actions."""
from datetime import date,time,datetime
from django.db import transaction
from django.db.models import Q,F
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from adc_core.rules import RuleError
from adc_core.commands import business_errors
from adc_core.proposals import proposal,read_proposal
from care.audit import emit
from equipment.policies import manager_clinic
from scheduling.resource_models import *
from scheduling.resource_forms import config_form,scoped_model,FORMS
from scheduling.resources import lock_physical,record_asset_impact_locked

CONTRACT='adc.resources.catalogue.v1'

def _serialized(form):
    result={}
    for k,v in form.cleaned_data.items():
        if hasattr(v,'values_list'):v=list(v.values_list('pk',flat=True))
        elif hasattr(v,'pk'):v=v.pk
        elif isinstance(v,(date,time,datetime)):v=v.isoformat()
        result[k]=v
    return result

def _validated(clinic,kind,fields,target):
    obj=scoped_model(clinic,kind).get(pk=target) if target else None
    form=config_form(clinic,kind,fields,instance=obj)
    # Clinic/recorder are intentionally absent from editable form fields.
    if kind=='department':form.instance.clinic_id=clinic
    if kind=='block':form.instance.clinic_id=clinic
    if kind=='department' and Department.objects.filter(clinic_id=clinic,code=fields.get('code','')).exclude(pk=target).exists():raise RuleError('本店已有该科室代码，请核对原目录。')
    if not form.is_valid():raise RuleError('；'.join(str(x) for errors in form.errors.values() for x in errors))
    if obj:
        # Identity/location changes use an explicit binding update, not moving
        # rooms/services into a new clinic or rewriting stable catalogue codes.
        for key in ('code','department'):
            original=type(obj).objects.get(pk=obj.pk)
            if key in form.cleaned_data and getattr(original,key)!=form.cleaned_data[key]:
                raise RuleError('已有目录的代码和所属科室保持不变，请新增目录并停用原项。')
    return form

def readiness(clinic):
    from scheduling.models import Visit
    from coordination.models import WaitOffer
    now=timezone.now()
    visits=Visit.objects.filter(clinic_id=clinic).filter(Q(status='SCHEDULED',scheduled_end__gt=now)|Q(status='CHECKED_IN'))
    offers=WaitOffer.objects.filter(request__clinic_id=clinic,state='PENDING',expires_at__gt=now)
    unmapped_visits=visits.exclude(resource_plans__is_current=True)
    unmapped_offers=offers.exclude(resource_plans__is_current=True)
    services=BookingService.objects.filter(department__clinic_id=clinic,is_active=True,department__is_active=True)
    return {'unmapped_visits':list(unmapped_visits.values('pk','visit_no','scheduled_start','scheduled_end')),
        'unmapped_offers':list(unmapped_offers.values('pk','starts_at','ends_at')),
        'unresolved_issues':ResourceCoordination.objects.filter(plan__service__department__clinic_id=clinic,state__in=['OPEN','CONTACT']).count(),
        'service_count':services.count(),'chair_count':ResourceBinding.objects.filter(asset__clinic_id=clinic,
            asset__category='CHAIR',asset__state='IN_SERVICE',is_active=True,shared=False,room__is_active=True,room__department__is_active=True).count(),
        'hours_count':DepartmentHours.objects.filter(department__clinic_id=clinic,department__is_active=True).count()}

def prepare_config(*,actor,kind,fields=None,target=None):
    clinic=manager_clinic(actor);row=ResourcePolicy.objects.filter(clinic_id=clinic).first()
    if kind in FORMS:
        if row is None:raise RuleError('请先点击“开始本店资源核对”。核对期间暂停新增预约，原承诺保留。')
        form=_validated(clinic,kind,fields or {},target);clean=_serialized(form)
    elif kind in ('start','activate','release_block'):
        clean={}
        if kind=='release_block':scoped_model(clinic,'block').get(pk=target,is_active=True)
        if kind=='start' and row:raise RuleError('本店已经开始资源配置。')
        if kind=='activate':
            facts=readiness(clinic)
            if not row or row.state!='PREPARING' or facts['unmapped_visits'] or facts['unmapped_offers'] or facts['unresolved_issues'] or not all(facts[k] for k in ('service_count','chair_count','hours_count')):
                raise RuleError('请补齐服务、开放时间及牙椅，并逐项核实现有预约和有效邀约后再启用。')
    else:raise RuleError('资源目录操作无效。')
    data={'clinic':clinic,'kind':kind,'target':target,'fields':clean,'revision':row.revision if row else None}
    display=[]
    if kind in FORMS:
        for key,value in form.cleaned_data.items():
            if hasattr(value,'values_list'):value='、'.join(str(x) for x in value)
            elif key=='asset' and value:value=value.name+'（'+value.asset_code+'）'
            elif isinstance(value,bool):value='是' if value else '否'
            elif isinstance(value,datetime):value=timezone.localtime(value).strftime('%Y-%m-%d %H:%M')
            elif value is None:value='未提供'
            display.append((form.fields[key].label or key,value))
    label={'department':'维护科室','hours':'维护开放时间','room':'维护诊室','service':'维护预约服务','binding':'核对设备排程位置','block':'登记临时停用','release_block':'结束临时停用','start':'开始本店资源核对','activate':'启用统一资源控制'}[kind]
    return {'kind':kind,'kind_label':label,'fields':clean,'display_fields':display,'proposal_token':proposal(actor,CONTRACT,('MANAGER',),data)}

@business_errors
@transaction.atomic
def confirm_config(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请核对后明确确认。')
    payload=read_proposal(actor,CONTRACT,('MANAGER',),proposal_token);d=payload['data'];clinic=manager_clinic(actor,lock=True)
    if d.get('clinic')!=clinic:raise PermissionDenied
    assets=lock_physical(clinic)
    row=ResourcePolicy.objects.select_for_update().filter(clinic_id=clinic).first()
    prior=ResourceAction.objects.filter(operation_id=payload['operation'],actor=actor,clinic_id=clinic).first()
    if prior:return prior,True
    if (row.revision if row else None)!=d['revision']:raise RuleError('资源目录已变化，请重新预览。')
    kind=d['kind'];target=d['target'];result={}
    if kind=='start':
        if row:raise RuleError('本店已开始配置。')
        row=ResourcePolicy.objects.create(clinic_id=clinic)
    elif kind=='activate':
        facts=readiness(clinic)
        if not row or row.state!='PREPARING' or facts['unmapped_visits'] or facts['unmapped_offers'] or facts['unresolved_issues'] or not all(facts[k] for k in ('service_count','chair_count','hours_count')):
            raise RuleError('启用条件已变化，请重新核对资源与原承诺。')
        row.state='ENABLED';row.activated_at=timezone.now();result=facts
    elif kind=='release_block':
        block=scoped_model(clinic,'block').select_for_update().get(pk=target,is_active=True)
        block.is_active=False;block.save(update_fields=['is_active']);result={'id':block.pk}
    elif kind in FORMS:
        if not row:raise RuleError('尚未开始资源配置。')
        form=_validated(clinic,kind,d['fields'],target)
        obj=form.save(commit=False)
        if kind=='block':obj.recorded_by=actor
        obj.save();form.save_m2m();result={'id':obj.pk,'fields':d['fields']}
        if kind=='service':
            for key,category in [('imaging','IMAGING'),('sterilizer','STERILIZER'),('other','OTHER')]:
                count=form.cleaned_data[key]
                if count:ServiceRequirement.objects.update_or_create(service=obj,category=category,defaults={'quantity':count})
                else:ServiceRequirement.objects.filter(service=obj,category=category).delete()
        if kind=='block':
            affected=[a for a in assets if obj.asset_id==a.pk or ResourceBinding.objects.filter(asset=a).filter(
                Q(room_id=obj.room_id) if obj.room_id else Q(room__department_id=obj.department_id) if obj.department_id else Q(pk__in=[])).exists()]
            for asset in affected:record_asset_impact_locked(asset,'排程停用：请核对原承诺',obj.starts_at,obj.ends_at)
    else:raise RuleError('资源目录操作无效。')
    if kind=='binding':record_asset_impact_locked(obj.asset,'资源位置或启用配置已核对更新，请复核原承诺')
    if kind in ('department','room') and not obj.is_active:
        affected=ResourceBinding.objects.filter(room__department=obj) if kind=='department' else ResourceBinding.objects.filter(room=obj)
        for binding in affected.select_related('asset'):record_asset_impact_locked(binding.asset,'科室或诊室停用，请协调原承诺')
    row.revision+=1;row.save()
    action=ResourceAction.objects.create(clinic_id=clinic,actor=actor,operation_id=payload['operation'],kind=kind,result=result)
    emit(actor,'RESOURCE_CATALOGUE_CHANGED',action,summary={'clinic_id':clinic,'kind':kind,'revision':row.revision})
    return action,False
