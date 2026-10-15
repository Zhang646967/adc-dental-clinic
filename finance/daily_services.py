"""Explicit preparation, independent review and new-version reopening; no ledger edits."""
from decimal import Decimal
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from accounts.models import UserAccount, RoleAssignment
from accounts.finance_access import lock_finance_write
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError, decimal_value
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from equipment.policies import manager_clinic, equipment_scope
from finance.cash_services import _date, _reason
from finance.daily_facts import day_facts, lock_day, comparison, KINDS
from finance.daily_models import DailyClose
from registry.models import Clinic

REQUEST='adc.daily.request.v1'
REVIEW='adc.daily.review.v1'

def close_scope(actor):
    clinic=equipment_scope(actor)
    rows=DailyClose.objects.all()
    return rows.filter(clinic_id=clinic) if clinic else rows

def declarations(value):
    if type(value) is not dict or set(value)!=set(KINDS):raise RuleError('请分别填写四类凭据核对金额。')
    values={k:decimal_value(value[k],2,Decimal('99999999999999999999999999.99')) for k in KINDS}
    return {k:format(abs(v) if v==0 else v,'.2f') for k,v in values.items()}

def latest(clinic,day):
    return DailyClose.objects.filter(clinic_id=clinic,business_date=day).order_by('-version').first()

def blocker(row,current):
    if not Clinic.objects.filter(pk=row.clinic_id,is_active=True).exists():return '诊所已停用，请退回日结并核实营业范围。'
    if row.snapshot!=current:return '现金账已变化；请退回旧版本，由经办人重新核对。'
    if current['pending']:return '当天仍有待审核收退款或设备费用，请先处理后重新核对。'
    if row.declared!=current['totals']:return '四类金额存在差异；经办人须核对凭据与原始业务，不能直接通过。'
    if not UserAccount.objects.filter(pk=row.prepared_by_id,is_active=True).exists() or not RoleAssignment.objects.filter(user_id=row.prepared_by_id,role='MANAGER',scope_kind='CLINIC',clinic_id=row.clinic_id,is_active=True).exists():
        return '经办人授权已失效，请退回并由当前负责人重新提交。'
    return ''

def prepare_close(*,actor,business_date,declared,evidence,reason):
    with reporting_snapshot():
        clinic=manager_clinic(actor);day=_date(business_date);previous=latest(clinic,day)
        if previous and previous.state=='PENDING':raise RuleError('当天已有待复核版本，请先处理原申请。')
        snapshot=day_facts(clinic,day);values=declarations(declared)
        data=dict(clinic=clinic,day=day.isoformat(),previous=previous.pk if previous else None,
            snapshot=snapshot,declared=values,evidence=_reason(evidence),reason=_reason(reason))
        return dict(data,comparison=comparison(snapshot,values),version=previous.version+1 if previous else 1,
            proposal_token=proposal(actor,REQUEST,('MANAGER',),data))

def _request_data(data):
    if type(data) is not dict or set(data)!={'clinic','day','previous','snapshot','declared','evidence','reason'}:raise RuleError('日结确认内容无效。')
    if type(data['clinic']) is not int or not 0<data['clinic']<2**63:raise RuleError('诊所无效。')
    if data['previous'] is not None and (type(data['previous']) is not int or not 0<data['previous']<2**63):raise RuleError('前一版本无效。')
    declarations(data['declared']);_reason(data['evidence']);_reason(data['reason'])

@business_errors
@transaction.atomic
def confirm_close(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确确认日结交接。')
    payload=read_proposal(actor,REQUEST,('MANAGER',),proposal_token);data=payload['data'];_request_data(data)
    clinic=manager_clinic(actor,lock=True)
    if clinic!=data['clinic']:raise PermissionDenied
    day=_date(data['day']);lock_day(clinic,day)
    prior=DailyClose.objects.filter(operation_id=payload['operation'],prepared_by=actor,clinic_id=clinic).first()
    if prior:return prior,True
    previous=latest(clinic,day)
    if (previous.pk if previous else None)!=data['previous'] or previous and previous.state=='PENDING':raise RuleError('日结版本已变化，请重新预览。')
    if day_facts(clinic,day)!=data['snapshot']:raise RuleError('现金账已变化，请重新预览并核对。')
    row=DailyClose.objects.create(operation_id=payload['operation'],clinic_id=clinic,business_date=day,
        version=previous.version+1 if previous else 1,previous=previous,snapshot=data['snapshot'],
        declared=declarations(data['declared']),evidence=_reason(data['evidence']),reason=_reason(data['reason']),prepared_by=actor)
    emit(actor,'DAILY_CLOSE_PREPARED',row,summary={'version':row.version,'previous':row.previous_id})
    return row,False

def prepare_close_review(*,actor,close_id,decision,reason):
    with reporting_snapshot():
        workspace_binding(actor,('FINANCE',));row=close_scope(actor).get(pk=close_id)
        if row.prepared_by_id==actor.pk:raise RuleError('经办人与复核人必须为不同账号。')
        if row.state!='PENDING':raise RuleError('该版本已处理。')
        if decision not in ('approve','reject'):raise RuleError('复核决定无效。')
        current=day_facts(row.clinic_id,row.business_date)
        if decision=='approve' and (message:=blocker(row,current)):raise RuleError(message)
        data=dict(close=row.pk,version=row.lock_version,decision=decision,reason=_reason(reason),snapshot=current)
        return dict(row=row,decision=decision,reason=reason,proposal_token=proposal(actor,REVIEW,('FINANCE',),data))

@business_errors
@transaction.atomic
def confirm_close_review(*,actor,proposal_token,confirmed,expected_close_id=None):
    if confirmed is not True:raise RuleError('请明确确认独立复核决定。')
    payload=read_proposal(actor,REVIEW,('FINANCE',),proposal_token);data=payload['data']
    if set(data)!={'close','version','decision','reason','snapshot'} or type(data['close']) is not int or not 0<data['close']<2**63 or type(data['version']) is not int or data['version']!=0 or data['decision'] not in ('approve','reject'):raise RuleError('复核确认内容无效。')
    if expected_close_id is not None and data['close']!=expected_close_id:raise RuleError('确认内容不属于当前日结。')
    reason=_reason(data['reason']);preview=DailyClose.objects.get(pk=data['close'])
    list(UserAccount.objects.select_for_update().filter(pk__in=[actor.pk,preview.prepared_by_id]).order_by('pk'))
    lock_finance_write(actor);lock_day(preview.clinic_id,preview.business_date)
    row=DailyClose.objects.select_for_update().get(pk=preview.pk)
    if row.prepared_by_id==actor.pk:raise RuleError('经办人与复核人必须为不同账号。')
    target='APPROVED' if data['decision']=='approve' else 'REJECTED'
    if row.state!='PENDING':
        if row.state==target and row.reviewed_by_id==actor.pk and row.review_reason==reason:return row,True
        raise RuleError('该版本已有其他复核结果。')
    if target=='APPROVED':
        list(RoleAssignment.objects.select_for_update().filter(user_id=row.prepared_by_id,role='MANAGER',clinic_id=row.clinic_id).order_by('pk'))
        current=day_facts(row.clinic_id,row.business_date)
        if current!=data['snapshot']:raise RuleError('现金账已变化，请重新核对。')
        if message:=blocker(row,current):raise RuleError(message)
    row.state=target;row.lock_version=1;row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_reason=reason
    row.save(update_fields=['state','lock_version','reviewed_by','reviewed_at','review_reason'])
    emit(actor,'DAILY_CLOSE_REVIEWED',row,summary={'decision':target,'version':row.version})
    return row,False
