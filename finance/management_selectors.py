"""Authorized aggregate projections: never patient names, notes or salary lines."""
from collections import defaultdict
from decimal import Decimal
from django.db.models import Sum,Q,Count
from django.utils import timezone
from adc_core.snapshots import reporting_snapshot
from finance.management_policy import month_bounds,allocate_cost,digest,ZERO,POLICY
from finance.management_models import CostMonth,COST_CATEGORIES
from finance.management_services import current_costs,category_stamp,cost_scope,equipment_sources
from registry.models import Dentist,Clinic
from scheduling.models import AvailabilitySlot,Visit
from care.models import Invoice
from finance.cash_models import CashEntry
from operations.policies import summarize


def monthly_facts(year,month,clinic_id):
    """Caller owns authorization and its transaction snapshot (read or write)."""
    start,end=month_bounds(year,month);now=timezone.now()
    period=CostMonth.objects.filter(year=year,month=month,clinic_id=clinic_id).first()
    invoices=list(Invoice.objects.filter(visit__clinic_id=clinic_id,visit__completed_at__gte=start,
        visit__completed_at__lt=end,visit__completed_at__lte=now).order_by('pk').values(
            'id','visit__dentist_id','current_record_version_id','current_record_version__total_amount')) if clinic_id else []
    shifts=list(AvailabilitySlot.objects.filter(clinic_id=clinic_id,is_active=True,starts_at__lt=end,ends_at__gt=start)
        .order_by('pk').values('id','dentist_id','starts_at','ends_at','booking_paused')) if clinic_id else []
    costs=list(current_costs(period).order_by('pk')) if period else []
    equipment=equipment_sources({c.equipment_event_id for c in costs if c.equipment_event_id})
    changed_sources=[c.pk for c in costs if c.equipment_event_id and equipment[c.equipment_event_id]['amount']!=c.amount]
    income=defaultdict(lambda:ZERO);direct=defaultdict(lambda:ZERO);minutes=defaultdict(int);slot_basis=defaultdict(list)
    for row in invoices:income[row['visit__dentist_id']]+=row['current_record_version__total_amount']
    for row in shifts:
        # Intake pause is not absence: retain paid/published shift time.
        value=int((min(row['ends_at'],end)-max(row['starts_at'],start)).total_seconds()//60)
        minutes[row['dentist_id']]+=value
        slot_basis[row['dentist_id']].append({'slot':row['id'],'minutes':value,
            'start':max(row['starts_at'],start).isoformat(),'end':min(row['ends_at'],end).isoformat()})
    shared=ZERO
    for row in costs:
        if row.dentist_id:direct[row.dentist_id]+=row.amount
        else:shared+=row.amount
    ids=set(income)|set(direct)|set(minutes)
    dentists={d.pk:d for d in Dentist.objects.filter(pk__in=ids)}
    code_minutes={dentists[i].employee_no:minutes[i] for i in ids}
    shares,unallocated=allocate_cost(shared,code_minutes)
    allocations=[dict(dentist=i,employee_no=dentists[i].employee_no,name=dentists[i].name,minutes=minutes[i],
        slots=slot_basis[i],production=str(income[i]),direct=str(direct[i]),shared=str(shares[dentists[i].employee_no]),
        contribution=str(income[i]-direct[i]-shares[dentists[i].employee_no])) for i in sorted(ids,key=lambda i:dentists[i].employee_no)]
    categories=[]
    for category,label in COST_CATEGORIES:
        recorded=period.coverage.get(category,{}) if period else {}
        stamp=category_stamp(period,category) if period else None
        total=sum((c.amount for c in costs if c.category==category),ZERO)
        state=recorded.get('state','MISSING') if recorded.get('stamp')==stamp and stamp else 'MISSING'
        categories.append(dict(code=category,label=label,amount=str(total),state=state,
            state_label={'MISSING':'待核实','ZERO':'已确认为零','COMPLETE':'已完整核对'}[state]))
    pending=period.costs.filter(state='PENDING').count() if period else 0
    ready=bool(period and not pending and not changed_sources and all(c['state']!='MISSING' for c in categories))
    production=sum(income.values(),ZERO);cost_total=sum((c.amount for c in costs),ZERO)
    cash=list(CashEntry.objects.filter(clinic_id=clinic_id,state='POSTED',kind__in=['RECEIPT','REFUND'],
        occurred_on__gte=start.date(),occurred_on__lt=end.date()).order_by('pk').values(
            'id','invoice__visit__dentist_id','kind','amount','occurred_on')) if clinic_id else []
    patient_net=sum((r['amount'] if r['kind']=='RECEIPT' else -r['amount'] for r in cash),ZERO)
    from finance.fund_models import FundTransfer
    from finance.allocation_models import FundAllocationLine
    bank=list(FundTransfer.objects.filter(state='CONFIRMED',line__account__clinic_id=clinic_id,
        line__booked_on__gte=start.date(),line__booked_on__lt=end.date()).order_by('pk')
        .values('id','kind','line__amount','line__booked_on')) if clinic_id else []
    fund_net=sum((r['line__amount'] if r['kind']=='RECEIPT' else -r['line__amount'] for r in bank),ZERO)
    allocated=list(FundAllocationLine.objects.filter(allocation__state='CONFIRMED',allocation__transfer__state='CONFIRMED',
        allocation__transfer_id__in=[r['id'] for r in bank]).order_by('pk').values(
            'id','claim__invoice__visit__dentist_id','allocation__transfer__kind','amount'))
    for row in allocations:
        person=row['dentist']
        net=sum((r['amount'] if r['kind']=='RECEIPT' else -r['amount'] for r in cash if r['invoice__visit__dentist_id']==person),ZERO)
        net+=sum((r['amount'] if r['allocation__transfer__kind']=='RECEIPT' else -r['amount'] for r in allocated
            if r['claim__invoice__visit__dentist_id']==person),ZERO)
        row['net_collections']=str(net)
    facts=dict(policy=POLICY,year=int(year),month=int(month),clinic=clinic_id,
        in_progress=now<end,
        ready=ready,categories=categories,pending=pending,changed_cost_sources=changed_sources,production=str(production),
        confirmed_cost=str(cost_total),profit=str(production-cost_total) if ready else None,
        direct_cost=str(sum(direct.values(),ZERO)),shared_cost=str(shared),unallocated=str(unallocated),
        patient_net=str(patient_net),fund_net=str(fund_net),net_collections=str(patient_net+fund_net),
        cash_balance=None,cash_balance_note='尚未核实期初账户余额，净收款不等于现金余额。',allocations=allocations,
        source={'invoices':invoices,'shifts':[{**r,'starts_at':r['starts_at'].isoformat(),'ends_at':r['ends_at'].isoformat()} for r in shifts],
            'costs':[dict(id=c.pk,amount=str(c.amount),dentist=c.dentist_id,category=c.category,replaces=c.replaces_id,
                reviewer=c.reviewed_by_id,equipment=c.equipment_event_id,
                equipment_source=equipment.get(c.equipment_event_id)) for c in costs],
            'coverage':period.coverage if period else {},'cash':cash,'fund_bank':bank,'fund_allocations':allocated})
    # Snapshots are JSON-native. All amounts and dates retain exact representations.
    import json
    facts=json.loads(json.dumps(facts,default=str,ensure_ascii=False))
    facts['digest']=digest(facts)
    return facts


def monthly_report(actor,year,month,clinic_id):
    with reporting_snapshot():
        ctx=cost_scope(actor,clinic_id)
        facts=monthly_facts(year,month,clinic_id)
        period=CostMonth.objects.filter(year=year,month=month,clinic_id=clinic_id).first()
        previous=period.reports.order_by('-sequence').first() if period else None
        facts['retained_reports']=list(period.reports.order_by('-sequence').values('id','sequence','confirmed_at','digest')) if period else []
        facts['changed_since_confirmation']=bool(previous and previous.digest!=facts['digest'])
        facts['as_of']=timezone.now()
        if ctx.role=='DENTIST':
            facts['allocations']=[r for r in facts['allocations'] if r['dentist']==actor.dentist_id]
            own=facts['allocations'][0] if facts['allocations'] else None
            # Never return store-wide costs, colleague figures or source identities.
            facts={k:facts[k] for k in ('policy','year','month','clinic','ready','as_of','allocations')}
            facts.update(production=own['production'] if own else '0.00',
                net_collections=own['net_collections'] if own else '0.00',
                confirmed_cost=str(Decimal(own['direct'])+Decimal(own['shared'])) if own else '0.00',
                profit=own['contribution'] if own and facts['ready'] else None)
        elif ctx.role=='FRONT_DESK':
            facts={k:facts[k] for k in ('policy','year','month','clinic','as_of')}
        else:facts.pop('source',None)
        return facts


def workload(actor,year,month,clinic_id,*,dentist_id=None,service_id=None):
    """Slot/visit intervals are planning time, never actual treatment duration."""
    with reporting_snapshot():
        ctx=cost_scope(actor,clinic_id)
        if ctx.role=='DENTIST':dentist_id=actor.dentist_id
        start,end=month_bounds(year,month);now=timezone.now()
        visits=Visit.objects.filter(clinic_id=clinic_id,scheduled_start__gte=start,scheduled_start__lt=end)
        slots=AvailabilitySlot.objects.filter(clinic_id=clinic_id,is_active=True,starts_at__lt=end,ends_at__gt=start)
        if dentist_id:visits=visits.filter(dentist_id=dentist_id);slots=slots.filter(dentist_id=dentist_id)
        if service_id:
            visits=visits.filter(resource_plans__is_current=True,resource_plans__service_id=service_id)
            slots=slots.filter(dentist__booking_services__pk=service_id).distinct()
        mature=visits.filter(scheduled_end__lte=now).exclude(status='RESCHEDULED')
        groups=list(mature.values('status','cancellation_party').annotate(n=Count('pk')))
        metrics=summarize((r['status'],r['cancellation_party'],r['n']) for r in groups)
        shift_minutes=sum((int((min(s.ends_at,end)-max(s.starts_at,start)).total_seconds()//60) for s in slots),0)
        retained=visits.filter(status__in=['SCHEDULED','CHECKED_IN','COMPLETED','CLOSED_NO_TREATMENT'])
        booked_minutes=sum((int((v.scheduled_end-v.scheduled_start).total_seconds()//60) for v in retained),0)
        from coordination.models import WaitOffer
        holds=WaitOffer.objects.filter(request__clinic_id=clinic_id,state='PENDING',expires_at__gt=now,
            starts_at__gte=start,starts_at__lt=end)
        if dentist_id:holds=holds.filter(slot__dentist_id=dentist_id)
        if service_id:holds=holds.filter(resource_plans__is_current=True,resource_plans__service_id=service_id)
        held=sum((int((x.ends_at-x.starts_at).total_seconds()//60) for x in holds),0)
        return dict(as_of=now,metrics=metrics,shift_minutes=shift_minutes,booked_minutes=booked_minutes,
            held_minutes=held,load_percent=round(Decimal(booked_minutes)*100/shift_minutes,2) if shift_minutes else None,
            scheduled=visits.filter(status='SCHEDULED').count(),completed=visits.filter(status='COMPLETED').count(),
            replaced=visits.filter(status='RESCHEDULED').count(),total=visits.count(),
            scope_note='预约与服务筛选影响履约统计；财务成本与利润按完整月份、整店／本人归集。')


def chain_report(actor,year,month):
    from adc_core.proposals import workspace_binding
    from finance.management_models import MonthlyCost
    from finance.management_services import category_stamp
    workspace_binding(actor,('FINANCE','HQ'))
    with reporting_snapshot():
        start,end=month_bounds(year,month);now=timezone.now()
        clinics=list(Clinic.objects.filter(is_active=True).order_by('clinic_code'))
        periods={p.clinic_id:p for p in CostMonth.objects.filter(year=year,month=month)}
        all_costs=list(MonthlyCost.objects.filter(period__year=year,period__month=month).order_by('pk').values(
            'id','period_id','state','amount','dentist_id','replaces_id','reviewed_by_id','equipment_event_id','category'))
        equipment=equipment_sources({c['equipment_event_id'] for c in all_costs if c['equipment_event_id']})
        superseded={r['replaces_id'] for r in all_costs if r['state']=='APPROVED' and r['replaces_id']}
        by_period=defaultdict(list)
        for c in all_costs:by_period[c['period_id']].append(c)
        income={r['visit__clinic_id']:r['total'] for r in Invoice.objects.filter(visit__clinic_id__in=[c.pk for c in clinics],
            visit__completed_at__gte=start,visit__completed_at__lt=end,visit__completed_at__lte=now)
            .values('visit__clinic_id').annotate(total=Sum('current_record_version__total_amount'))}
        cash=defaultdict(lambda:ZERO)
        for r in (CashEntry.objects.filter(clinic_id__in=[c.pk for c in clinics],state='POSTED',
            occurred_on__gte=start.date(),occurred_on__lt=end.date(),kind__in=['RECEIPT','REFUND'])
            .values('clinic_id','kind').annotate(total=Sum('amount'))):
            cash[r['clinic_id']]+=r['total'] if r['kind']=='RECEIPT' else -r['total']
        from finance.fund_models import FundTransfer
        for r in (FundTransfer.objects.filter(state='CONFIRMED',line__account__clinic_id__in=[c.pk for c in clinics],
            line__booked_on__gte=start.date(),line__booked_on__lt=end.date()).values('line__account__clinic_id','kind').annotate(total=Sum('line__amount'))):
            cash[r['line__account__clinic_id']]+=r['total'] if r['kind']=='RECEIPT' else -r['total']
        grouped=list(Visit.objects.filter(clinic_id__in=[c.pk for c in clinics],scheduled_start__gte=start,
            scheduled_start__lt=end,scheduled_end__lte=now).exclude(status='RESCHEDULED')
            .values('clinic_id','status','cancellation_party').annotate(n=Count('pk')))
        rows=[]
        for clinic in [*clinics,None]:
            clinic_id=clinic.pk if clinic else None;period=periods.get(clinic_id)
            costs=by_period[period.pk] if period else []
            ready=bool(period) and not any(r['state']=='PENDING' for r in costs)
            ready=ready and not any(r['state']=='APPROVED' and r['id'] not in superseded and r['equipment_event_id']
                and equipment[r['equipment_event_id']]['amount']!=r['amount'] for r in costs)
            for category,_ in COST_CATEGORIES:
                exact=[{k:r[k] for k in ('id','state','amount','dentist_id','replaces_id','reviewed_by_id','equipment_event_id')}
                    for r in costs if r['category']==category]
                coverage=period.coverage.get(category,{}) if period else {}
                ready=ready and coverage.get('state') in ('ZERO','COMPLETE') and coverage.get('stamp')==digest(exact)
            total=sum((r['amount'] for r in costs if r['state']=='APPROVED' and r['id'] not in superseded),ZERO)
            production=income.get(clinic_id,ZERO)
            metrics=summarize((g['status'],g['cancellation_party'],g['n']) for g in grouped if g['clinic_id']==clinic_id)
            rows.append(dict(clinic=clinic_id,name=clinic.public_contact['name'] if clinic else '总部成本中心',
                code=clinic.clinic_code if clinic else 'HQ',production=production,cost=total,ready=bool(ready),
                profit=production-total if ready else None,net_collections=cash[clinic_id],metrics=metrics))
        ready=all(r['ready'] for r in rows)
        return dict(rows=rows,ready=ready,year=year,month=month,as_of=now,in_progress=now<end,
            production=sum((r['production'] for r in rows),ZERO),cost=sum((r['cost'] for r in rows),ZERO),
            profit=sum((r['profit'] for r in rows),ZERO) if ready else None,
            net_collections=sum((r['net_collections'] for r in rows),ZERO),policy=POLICY)
