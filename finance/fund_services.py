"""Independent review of retained fund bank evidence; no claim allocation yet."""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.conf import settings
from accounts.models import RoleAssignment
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from finance.evidence_policies import lock_people, lock_finance, require_live_clinic
from finance.cash_services import _reason
from finance.fund_models import FundTransfer
from finance.reconciliation_models import StatementLine
from finance.statement_use import require_available, usage_cursor

REQUEST='adc.fund.transfer.v1'
REVIEW='adc.fund.transfer.review.v1'


def _write_scope(actor):
    if not settings.ADC_CLINICAL_SYNTHETIC:
        raise PermissionDenied('本阶段只办理明确的本地合成基金流程。')
    lock_finance(actor)


def _source(line, kind):
    if kind not in ('RECEIPT','RETURN'):
        raise RuleError('请选择基金到账或退回证据。')
    if line.batch.state!='IMPORTED' or line.currency!='CNY' or line.account.method!='BANK_TRANSFER':
        raise RuleError('基金证据必须来自已确认导入的 CNY 银行转账流水。')
    if line.direction!=('IN' if kind=='RECEIPT' else 'OUT'):
        raise RuleError('基金到账需要入账流水，基金退回需要出账流水。')
    require_live_clinic(line.account.clinic_id)


def prepare_transfer(*,actor,line_id,kind,basis):
    workspace_binding(actor,('FINANCE',))
    with reporting_snapshot():
        line=StatementLine.objects.select_related('account','batch').get(pk=line_id)
        _source(line,kind); require_available(line.pk)
        d=dict(line=line.pk,kind=kind,basis=_reason(basis),usage_cursor=usage_cursor(line.pk))
        return dict(line=line,data=d,proposal_token=proposal(actor,REQUEST,('FINANCE',),d))


@business_errors
@transaction.atomic
def confirm_transfer(*,actor,proposal_token,confirmed,expected_line_id=None):
    if confirmed is not True: raise RuleError('请明确确认基金银行证据；提交后仍待另一财务账号核对。')
    p=read_proposal(actor,REQUEST,('FINANCE',),proposal_token);d=p['data']
    if expected_line_id is not None and d['line']!=expected_line_id: raise RuleError('确认内容与当前流水不同。')
    lock_people(actor.pk);_write_scope(actor)
    prior=FundTransfer.objects.filter(operation_id=p['operation'],prepared_by=actor).first()
    if prior: return prior,True
    line=StatementLine.objects.select_for_update(of=('self',)).select_related('account','batch').get(pk=d['line'])
    _source(line,d['kind']);require_available(line.pk)
    if usage_cursor(line.pk)!=d['usage_cursor']: raise RuleError('流水用途历史已变化，请核对原结果后重新预览。')
    row=FundTransfer.objects.create(line=line,kind=d['kind'],basis=d['basis'],operation_id=p['operation'],prepared_by=actor)
    emit(actor,'FUND_TRANSFER_REQUESTED',row,summary=dict(kind=row.kind,line_id=line.pk))
    return row,False


def _reviewable(actor,row,decision,*,lock=False):
    if row.prepared_by_id==actor.pk: raise PermissionDenied('基金银行证据必须由另一财务账号核对。')
    if row.state!='PENDING' or decision not in ('approve','reject'): raise RuleError('请选择待复核基金证据的明确决定。')
    if decision=='approve':
        grants=RoleAssignment.objects.filter(user_id=row.prepared_by_id,role='FINANCE',scope_kind='CHAIN',is_active=True,user__is_active=True)
        if lock: grants=grants.select_for_update(of=('self',))
        if not list(grants): raise RuleError('原办理人的财务授权失效，请退回原证据。')
        _source(row.line,row.kind);require_available(row.line_id,fund_transfer_id=row.pk)


def prepare_transfer_review(*,actor,transfer_id,decision,reason):
    workspace_binding(actor,('FINANCE',))
    with reporting_snapshot():
        row=FundTransfer.objects.select_related('line__account','line__batch').get(pk=transfer_id)
        _reviewable(actor,row,decision)
        d=dict(transfer=row.pk,decision=decision,reason=_reason(reason))
        return dict(row=row,data=d,proposal_token=proposal(actor,REVIEW,('FINANCE',),d))


@business_errors
@transaction.atomic
def confirm_transfer_review(*,actor,proposal_token,confirmed,expected_transfer_id=None):
    if confirmed is not True: raise RuleError('请明确确认基金银行证据的独立核对结果。')
    p=read_proposal(actor,REVIEW,('FINANCE',),proposal_token);d=p['data']
    if expected_transfer_id is not None and d['transfer']!=expected_transfer_id: raise RuleError('复核目标与当前证据不同。')
    initial=FundTransfer.objects.get(pk=d['transfer'])
    lock_people(actor.pk,initial.prepared_by_id);_write_scope(actor)
    # Preparer grant precedes the shared StatementLine lock.
    if d['decision']=='approve':
        list(RoleAssignment.objects.select_for_update().filter(user_id=initial.prepared_by_id,role='FINANCE',scope_kind='CHAIN').order_by('pk'))
    StatementLine.objects.select_for_update().get(pk=initial.line_id)
    row=FundTransfer.objects.select_for_update(of=('self',)).select_related('line__account','line__batch').get(pk=initial.pk)
    target='CONFIRMED' if d['decision']=='approve' else 'REJECTED'
    if row.state!='PENDING':
        if row.state==target and row.reviewed_by_id==actor.pk and row.review_reason==d['reason']: return row,True
        raise RuleError('原基金证据已有其他核对结果，请查看当前记录。')
    _reviewable(actor,row,d['decision'])
    row.state=target;row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_reason=d['reason']
    row.save(update_fields=['state','reviewed_by','reviewed_at','review_reason'])
    emit(actor,'FUND_TRANSFER_REVIEWED',row,summary=dict(state=target))
    return row,False
