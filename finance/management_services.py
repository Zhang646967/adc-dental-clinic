from datetime import date
from decimal import Decimal
from django.db import connection, transaction
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone
from django.conf import settings
from accounts.policies import require_writable
from accounts.finance_access import lock_finance_write
from workspaces.context import require_active
from equipment.policies import manager_clinic
from adc_core.proposals import proposal,read_proposal,workspace_binding
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit
from finance.management_models import (CostMonth, MonthlyCost, ManagementReport,
    CostAllocation, ManagementAction, COST_CATEGORIES)
from finance.management_policy import month_bounds,digest,ZERO

CONTRACT='adc.management-cost.p1'


def cost_scope(actor,clinic_id,*,write=False,lock=False):
    roles=('MANAGER','FINANCE') if write else ('MANAGER','FINANCE','HQ','DENTIST','FRONT_DESK')
    workspace_binding(actor,roles)
    ctx=actor._adc_workspace
    if write and lock:require_writable(actor)
    elif write and settings.ADC_READ_ONLY:raise PermissionDenied('当前实例仅供只读演示。')
    if ctx.role=='MANAGER':
        clinic=manager_clinic(actor,lock=lock)
        if clinic_id!=clinic:raise PermissionDenied('只能办理当前门店的经营资料。')
    elif ctx.role=='FRONT_DESK':
        if clinic_id!=ctx.clinic_id:raise PermissionDenied('只能查看当前门店的履约与排班。')
    elif ctx.role=='DENTIST':
        if clinic_id is None:raise PermissionDenied('请先选择本人的接诊门店。')
        from registry.profile_models import DentistClinicAffiliation
        from scheduling.models import Visit,AvailabilitySlot
        if not (DentistClinicAffiliation.objects.filter(clinic_id=clinic_id,dentist_id=actor.dentist_id).exists()
            or Visit.objects.filter(clinic_id=clinic_id,dentist_id=actor.dentist_id).exists()
            or AvailabilitySlot.objects.filter(clinic_id=clinic_id,dentist_id=actor.dentist_id).exists()):
            raise PermissionDenied('没有本人在该店的业务关联。')
    elif lock and ctx.role=='FINANCE':lock_finance_write(actor)
    return ctx


def period_lookup(year,month,clinic_id):
    month_bounds(year,month)
    return {'year':int(year),'month':int(month),'clinic_id':clinic_id}


def period_lock(key):
    with connection.cursor() as cur:
        cur.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
            ['management:'+str(key['clinic_id'])+':'+str(key['year'])+':'+str(key['month'])])


def current_costs(period):
    return period.costs.filter(state='APPROVED').exclude(
        pk__in=MonthlyCost.objects.filter(state='APPROVED',replaces__isnull=False).values('replaces_id'))


def category_stamp(period,category):
    return digest(list(period.costs.filter(category=category).order_by('pk').values(
        'id','state','amount','dentist_id','replaces_id','reviewed_by_id','equipment_event_id')))


def equipment_sources(event_ids):
    from equipment.models import EquipmentEvent,EquipmentCostAmendment
    result={r['id']:{'version':0,'amount':r['cost']} for r in EquipmentEvent.objects.filter(pk__in=event_ids).values('id','cost')}
    for r in EquipmentCostAmendment.objects.filter(event_id__in=event_ids,state='APPROVED').order_by('pk').values('id','event_id','proposed_cost'):
        result[r['event_id']]={'version':r['id'],'amount':r['proposed_cost']}
    return result


def cost_values(fields,clinic_id,period=None):
    from finance.policies import money
    from registry.models import Dentist
    from equipment.models import EquipmentEvent
    f=dict(fields)
    category=f.get('category')
    if category not in dict(COST_CATEGORIES):raise RuleError('请选择有效成本类别。')
    amount=money(f.get('amount'))
    if amount<0:raise RuleError('成本不能为负数；修改请提交原成本的修订版本。')
    reference=str(f.get('reference','')).strip();basis=str(f.get('basis','')).strip()
    if not reference or len(reference)>160 or not basis or len(basis)>500:
        raise RuleError('请填写来源编号和成本归集依据。')
    dentist_id=f.get('dentist_id') or None
    if dentist_id:
        if clinic_id is None or not Dentist.objects.filter(pk=dentist_id,is_active=True).exists():
            raise RuleError('总部公共费用不能直接归属医师，请核对医师与门店。')
        from registry.profile_models import DentistClinicAffiliation
        from scheduling.models import AvailabilitySlot,Visit
        if not (DentistClinicAffiliation.objects.filter(dentist_id=dentist_id,clinic_id=clinic_id).exists()
            or AvailabilitySlot.objects.filter(dentist_id=dentist_id,clinic_id=clinic_id).exists()
            or Visit.objects.filter(dentist_id=dentist_id,clinic_id=clinic_id).exists()):
            raise RuleError('该医师没有本店任职或业务依据。')
    equipment_id=f.get('equipment_event_id') or None
    equipment_cursor=None
    if equipment_id:
        event=EquipmentEvent.objects.filter(pk=equipment_id,asset__clinic_id=clinic_id).first()
        if not event or event.kind not in ('MAINTENANCE','SERVICE') or category!='MAINTENANCE':
            raise RuleError('仅可将本店维修／保养来源归集为维修费用；采购款不能作为当期维修成本。')
        amendment=event.cost_amendments.filter(state='APPROVED').order_by('-pk').first()
        actual=amendment.proposed_cost if amendment else event.cost
        if actual is None or amount!=actual:raise RuleError('金额须与当前已核实设备费用一致，未知费用请先核实。')
        equipment_cursor=amendment.pk if amendment else 0
    return dict(category=category,amount=str(amount),reference=reference,basis=basis,dentist_id=dentist_id,
        equipment_event_id=equipment_id,equipment_cursor=equipment_cursor)


def prepare_cost(*,actor,year,month,clinic_id,fields,replaces_id=None):
    cost_scope(actor,clinic_id,write=True)
    key=period_lookup(year,month,clinic_id);period=CostMonth.objects.filter(**key).first()
    values=cost_values(fields,clinic_id,period)
    if replaces_id:
        old=MonthlyCost.objects.filter(pk=replaces_id,period=period,state='APPROVED').first()
        if not old or not current_costs(period).filter(pk=old.pk).exists():raise RuleError('只能修订本月当前已确认成本。')
        if old.equipment_event_id!=values['equipment_event_id']:raise RuleError('修订不能更换原设备费用来源。')
    data={'key':key,'action':'SUBMIT','fields':values,'replaces':replaces_id}
    return {'data':data,'proposal_token':proposal(actor,CONTRACT,('MANAGER','FINANCE'),data)}


def prepare_decision(*,actor,cost_id,decision,note=''):
    cost_scope(actor,None,write=True)
    require_active(actor,('FINANCE',))
    from scheduling.service_content import positive_id
    cost_id=positive_id(str(cost_id))
    if cost_id is None:raise RuleError('请选择有效成本记录。')
    row=MonthlyCost.objects.select_related('period').get(pk=cost_id)
    if decision not in ('APPROVED','REJECTED'):raise RuleError('请选择复核结果。')
    if row.prepared_by_id==actor.pk:raise RuleError('不能复核本人提交的成本。')
    data={'key':period_lookup(row.period.year,row.period.month,row.period.clinic_id),
        'action':'REVIEW','cost':row.pk,'decision':decision,'note':str(note)[:500]}
    return {'data':data,'proposal_token':proposal(actor,CONTRACT,('FINANCE',),data)}


def prepare_coverage(*,actor,year,month,clinic_id,category,state,note):
    cost_scope(actor,clinic_id,write=True);require_active(actor,('FINANCE',))
    key=period_lookup(year,month,clinic_id);period=CostMonth.objects.filter(**key).first()
    if not period:raise RuleError('请先提交成本资料，或建立本月核算期间。')
    if category not in dict(COST_CATEGORIES) or state not in ('COMPLETE','ZERO') or not str(note).strip():
        raise RuleError('请选择类别、完整／确认为零，并填写核对依据。')
    data={'key':key,'action':'COVERAGE','category':category,'state':state,
        'stamp':category_stamp(period,category),'note':str(note).strip()[:500]}
    return {'data':data,'proposal_token':proposal(actor,CONTRACT,('FINANCE',),data)}


def prepare_month(*,actor,year,month,clinic_id):
    cost_scope(actor,clinic_id,write=True)
    data={'key':period_lookup(year,month,clinic_id),'action':'OPEN'}
    return {'data':data,'proposal_token':proposal(actor,CONTRACT,('MANAGER','FINANCE'),data)}


def prepare_report(*,actor,year,month,clinic_id):
    cost_scope(actor,clinic_id,write=True);require_active(actor,('FINANCE',))
    from finance.management_selectors import monthly_facts
    from adc_core.snapshots import reporting_snapshot
    with reporting_snapshot():facts=monthly_facts(year,month,clinic_id)
    if not facts['ready']:raise RuleError('成本尚未完整核实，请先处理待复核或缺失类别。')
    data={'key':period_lookup(year,month,clinic_id),'action':'REPORT','digest':facts['digest']}
    return {'data':data,'summary':facts,'proposal_token':proposal(actor,CONTRACT,('FINANCE',),data)}


@business_errors
def confirm_management(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确核对并确认本次办理。')
    # A retained month report uses one coherent writable PG snapshot.
    initial=read_proposal(actor,CONTRACT,('MANAGER','FINANCE'),proposal_token)
    outer=connection.in_atomic_block
    with transaction.atomic():
        if not outer and initial['data']['action']=='REPORT':
            with connection.cursor() as cur:cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        p=read_proposal(actor,CONTRACT,('MANAGER','FINANCE'),proposal_token);d=p['data'];key=d['key']
        cost_scope(actor,key['clinic_id'],write=True,lock=True)
        if d['action'] not in ('SUBMIT','OPEN'):require_active(actor,('FINANCE',))
        period_lock(key)
        prior=ManagementAction.objects.filter(operation_id=p['operation'],actor=actor).first()
        if prior:return prior,True
        period,_=CostMonth.objects.get_or_create(**key)
        period=CostMonth.objects.select_for_update().get(pk=period.pk)
        cost=report=None
        if d['action']=='SUBMIT':
            if d['fields']['equipment_event_id']:
                with connection.cursor() as cur:cur.execute('SELECT pg_advisory_xact_lock(%s,%s)',[7120,d['fields']['equipment_event_id']])
            f=cost_values(d['fields'],key['clinic_id'],period)
            if f['equipment_cursor']!=d['fields']['equipment_cursor']:raise RuleError('设备费用已修订，请重新核对。')
            if d['replaces']:
                old=current_costs(period).filter(pk=d['replaces']).first()
                if not old or MonthlyCost.objects.filter(replaces=old,state__in=['PENDING','APPROVED']).exists():
                    raise RuleError('原成本已修订或正在复核，请查看原办理结果。')
                if old.equipment_event_id!=f['equipment_event_id']:raise RuleError('不能更换原设备来源。')
            elif period.costs.filter(reference=f['reference'],replaces__isnull=True,state__in=['PENDING','APPROVED']).exists():
                raise RuleError('该来源编号已登记，请查看原成本或提交修订。')
            if f['equipment_event_id'] and not d['replaces'] and MonthlyCost.objects.filter(
                equipment_event_id=f['equipment_event_id'],replaces__isnull=True,state__in=['PENDING','APPROVED']).exists():
                raise RuleError('该设备费用已归集，不能再次计入其他月份。')
            f.pop('equipment_cursor')
            cost=MonthlyCost.objects.create(period=period,prepared_by=actor,replaces_id=d['replaces'],**f)
        elif d['action']=='REVIEW':
            cost=MonthlyCost.objects.select_for_update().get(pk=d['cost'],period=period)
            if cost.state!='PENDING':raise RuleError('成本已复核，请查看原结果。')
            if cost.prepared_by_id==actor.pk:raise RuleError('不能复核本人提交的成本。')
            if d['decision']=='APPROVED':
                if cost.replaces_id and not current_costs(period).filter(pk=cost.replaces_id).exists():
                    raise RuleError('原成本已变化，请退回后重新提交。')
                if cost.equipment_event_id:
                    cost_values({'category':cost.category,'amount':str(cost.amount),'reference':cost.reference,
                        'basis':cost.basis,'dentist_id':cost.dentist_id,'equipment_event_id':cost.equipment_event_id},key['clinic_id'],period)
            cost.state=d['decision'];cost.reviewed_by=actor;cost.reviewed_at=timezone.now();cost.review_note=d['note'];cost.save()
        elif d['action']=='COVERAGE':
            category=d['category'];stamp=category_stamp(period,category)
            if stamp!=d['stamp']:raise RuleError('该类成本已有变化，请重新核对。')
            if period.costs.filter(category=category,state='PENDING').exists():raise RuleError('该类别仍有待复核成本。')
            amounts=sum(current_costs(period).filter(category=category).values_list('amount',flat=True),ZERO)
            if (d['state']=='ZERO')!=(amounts==ZERO):raise RuleError('已确认金额与完整／零费用选择不一致。')
            period.coverage={**period.coverage,category:{'state':d['state'],'stamp':stamp,'reviewer':actor.pk,'note':d['note']}}
        elif d['action']=='REPORT':
            from finance.management_selectors import monthly_facts
            facts=monthly_facts(key['year'],key['month'],key['clinic_id'])
            if not facts['ready'] or facts['digest']!=d['digest']:raise RuleError('账单、出诊或成本已有变化，请重新预览月报。')
            sequence=period.reports.count()+1
            report=ManagementReport.objects.create(period=period,sequence=sequence,snapshot=facts,
                digest=facts['digest'],confirmed_by=actor)
            for row in facts['allocations']:
                CostAllocation.objects.create(report=report,dentist_id=row['dentist'],shift_minutes=row['minutes'],
                    direct_cost=row['direct'],shared_cost=row['shared'],production=row['production'],
                    contribution=row['contribution'],basis={'slots':row['slots'],'policy':facts['policy']})
        elif d['action']!='OPEN':raise RuleError('核算动作无效。')
        period.revision+=1;period.save()
        event=ManagementAction.objects.create(period=period,cost=cost,report=report,actor=actor,action=d['action'],
            operation_id=p['operation'],snapshot={'revision':period.revision,'category':d.get('category'),'decision':d.get('decision'),
                'source_fields':d.get('fields',{})})
        emit(actor,'MANAGEMENT_COST_CHANGED',event,summary={'action':d['action'],'period':period.pk})
        return event,False
