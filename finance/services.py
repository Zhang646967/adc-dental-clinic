"""UC-08 write commands. Quarter lock serializes roster/cost updates.
Authorization -> quarter lock -> stale token -> validate -> write -> audit.
"""
from django.db import transaction
from django.utils import timezone
from adc_core.commands import business_errors, assert_revision
from adc_core.rules import RuleError, quarter_bounds
from care.audit import emit
from finance.models import Quarter, DentistQuarterCost
from accounts.finance_access import lock_finance_write
from finance.policies import money
from registry.models import Dentist

def _touch(q, invalidate_roster=False):
    if invalidate_roster:
        q.roster_status='DRAFT';q.roster_confirmed_by=None;q.roster_confirmed_at=None
    q.lock_version+=1
    q.save(update_fields=['roster_status','roster_confirmed_by','roster_confirmed_at','lock_version'])

@business_errors
@transaction.atomic
def create_quarter(*,actor,year,quarter_no):
    lock_finance_write(actor);quarter_bounds(year,quarter_no)
    obj,created=Quarter.objects.get_or_create(year=year,quarter_no=quarter_no)
    if created: emit(actor,'QUARTER_CREATED',obj,summary={'year':year,'quarter':quarter_no})
    return obj

@business_errors
@transaction.atomic
def add_member(*,actor,quarter_id,expected_version,dentist_id):
    lock_finance_write(actor)
    q=Quarter.objects.select_for_update().get(pk=quarter_id);assert_revision(q,expected_version)
    dentist=Dentist.objects.get(pk=dentist_id) # Inactive historical staff may still incur costs.
    row,created=DentistQuarterCost.objects.get_or_create(quarter=q,dentist=dentist)
    if not created: raise RuleError('该牙医已在本季度清单中。')
    _touch(q,True);emit(actor,'QUARTER_MEMBER_ADDED',row,summary={'quarter_id':q.pk,'dentist_id':dentist.pk})
    return row

@business_errors
@transaction.atomic
def confirm_roster(*,actor,quarter_id,expected_version):
    from care.ledger import income_by_dentist
    lock_finance_write(actor)
    q=Quarter.objects.select_for_update().get(pk=quarter_id);assert_revision(q,expected_version)
    ids=set(q.dentist_costs.values_list('dentist_id',flat=True))
    if not ids: raise RuleError('请先加入至少一名纳入牙医。')
    start,end=quarter_bounds(q.year,q.quarter_no)
    earners={r.dentist_id for r in income_by_dentist(start,end,timezone.now())}
    if earners-ids: raise RuleError('仍有已开单牙医未纳入，请检查收入缺口。')
    q.roster_status='CONFIRMED';q.roster_confirmed_by=actor;q.roster_confirmed_at=timezone.now()
    _touch(q);emit(actor,'QUARTER_ROSTER_CONFIRMED',q,summary={'member_count':len(ids),'revision':q.lock_version})
    return q

@business_errors
@transaction.atomic
def save_cost(*,actor,quarter_id,cost_id,expected_version,supply_cost,operating_expense,notes=''):
    lock_finance_write(actor)
    q=Quarter.objects.select_for_update().get(pk=quarter_id);assert_revision(q,expected_version)
    c=DentistQuarterCost.objects.select_for_update().get(pk=cost_id,quarter=q)
    if not isinstance(notes,str) or not 1<=len(notes.strip())<=500: raise RuleError('请填写成本依据或修改说明（1至500字）。')
    c.supply_cost=money(supply_cost);c.operating_expense=money(operating_expense)
    c.notes=notes.strip();c.cost_status='DRAFT';c.confirmed_by=None;c.confirmed_at=None
    c.save(update_fields=['supply_cost','operating_expense','notes','cost_status','confirmed_by','confirmed_at'])
    _touch(q);emit(actor,'QUARTER_COST_SAVED',c,reason=notes.strip(),summary={'quarter_id':q.pk,'status':'DRAFT'})
    return c

@business_errors
@transaction.atomic
def confirm_cost(*,actor,quarter_id,cost_id,expected_version):
    lock_finance_write(actor)
    q=Quarter.objects.select_for_update().get(pk=quarter_id);assert_revision(q,expected_version)
    c=DentistQuarterCost.objects.select_for_update().get(pk=cost_id,quarter=q)
    if c.supply_cost is None or c.operating_expense is None or c.cost_status!='DRAFT':
        raise RuleError('只有已填写两项金额的成本草稿可以确认。零值也需明确确认。')
    money(c.supply_cost);money(c.operating_expense)
    c.cost_status='CONFIRMED';c.confirmed_by=actor;c.confirmed_at=timezone.now();c.save()
    _touch(q);emit(actor,'QUARTER_COST_CONFIRMED',c,summary={'quarter_id':q.pk})
    return c
