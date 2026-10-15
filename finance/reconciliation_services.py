"""One-to-one proposals and independent review, separate from cash posting."""
from django.db import transaction
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from equipment.policies import manager_clinic
from finance.evidence_policies import reconciliation_scope, lock_people, lock_finance, preparer_current, require_live_clinic
from finance.cash_models import CashEntry
from finance.cash_evidence_services import effective
from finance.reconciliation_models import StatementLine, ReconciliationMatch, CashEvidenceVersion

REQUEST='adc.reconciliation.request.v1'
REVIEW='adc.reconciliation.review.v1'
ACTIVE=('PENDING','CONFIRMED')

def validate_match(entry,evidence,line,*,exclude=None):
    direction='IN' if entry.kind in ('RECEIPT','EXPENSE_REVERSAL') else 'OUT'
    if (entry.state!='POSTED' or evidence is None or evidence.cash_entry_id!=entry.pk or evidence.state!='APPROVED' or
        evidence.account_id!=line.account_id or entry.clinic_id!=line.account.clinic_id or line.batch.state!='IMPORTED' or
        direction!=line.direction or entry.amount!=line.amount or line.currency!='CNY' or evidence.reference!=line.reference):
        raise RuleError('只能匹配同诊所、渠道账户、凭据编号、方向、金额及CNY币种一致的已记账款项。')
    if effective(entry.pk).pk!=evidence.pk:raise RuleError('凭据已更新，请重新核对。')
    others=ReconciliationMatch.objects.filter(state__in=ACTIVE)
    if exclude is not None:others=others.exclude(pk=exclude)
    from django.db.models import Q
    if others.filter(Q(cash_entry=entry)|Q(line=line)).exists():raise RuleError('款项或流水已有待审／已复核匹配，请先查阅当前结果。')

def prepare_match(*,actor,line_id,entry_id):
    with reporting_snapshot():
        clinic=manager_clinic(actor)
        line=StatementLine.objects.select_related('account','batch').get(pk=line_id,account__clinic_id=clinic)
        entry=CashEntry.objects.get(pk=entry_id,clinic_id=clinic)
        evidence=effective(entry.pk);validate_match(entry,evidence,line)
        d=dict(line=line.pk,entry=entry.pk,evidence=evidence.pk)
        return dict(line=line,entry=entry,evidence=evidence,proposal_token=proposal(actor,REQUEST,('MANAGER',),d))

@business_errors
@transaction.atomic
def confirm_match(*,actor,proposal_token,confirmed,expected_line_id):
    if confirmed is not True:raise RuleError('请明确确认提交逐笔匹配。')
    p=read_proposal(actor,REQUEST,('MANAGER',),proposal_token);d=p['data']
    if set(d)!={'line','entry','evidence'} or any(type(v) is not int or v<=0 for v in d.values()) or d['line']!=expected_line_id:raise RuleError('匹配确认目标无效。')
    lock_people(actor.pk);clinic=manager_clinic(actor,lock=True)
    # Canonical order shared with evidence corrections and match review:
    # actor/grant -> cash entry -> evidence -> statement line -> match.
    entry=CashEntry.objects.select_for_update().get(pk=d['entry'],clinic_id=clinic)
    prior=ReconciliationMatch.objects.filter(operation_id=p['operation'],prepared_by=actor,cash_entry=entry).first()
    if prior:return prior,True
    evidence=CashEvidenceVersion.objects.select_for_update().get(pk=d['evidence'],cash_entry=entry)
    line=StatementLine.objects.select_for_update().get(pk=d['line'],account__clinic_id=clinic)
    validate_match(entry,evidence,line)
    row=ReconciliationMatch.objects.create(cash_entry=entry,evidence=evidence,line=line,prepared_by=actor,operation_id=p['operation'])
    emit(actor,'RECONCILIATION_REQUESTED',row,summary={'entry_id':entry.pk,'line_id':line.pk})
    return row,False

def prepare_match_review(*,actor,match_id,decision,reason):
    from finance.cash_services import _reason
    with reporting_snapshot():
        workspace_binding(actor,('FINANCE',));reconciliation_scope(actor)
        row=ReconciliationMatch.objects.select_related('cash_entry','evidence__account','line__account','line__batch').get(pk=match_id)
        if row.state!='PENDING' or row.prepared_by_id==actor.pk or decision not in ('approve','reject'):raise RuleError('须由不同账号复核待审匹配。')
        if decision=='approve':validate_match(row.cash_entry,row.evidence,row.line,exclude=row.pk)
        d=dict(match=row.pk,decision=decision,reason=_reason(reason))
        return dict(row=row,data=d,proposal_token=proposal(actor,REVIEW,('FINANCE',),d))

@business_errors
@transaction.atomic
def confirm_match_review(*,actor,proposal_token,confirmed,expected_match_id):
    from finance.cash_services import _reason
    if confirmed is not True:raise RuleError('请明确确认匹配独立复核。')
    p=read_proposal(actor,REVIEW,('FINANCE',),proposal_token);d=p['data']
    if set(d)!={'match','decision','reason'} or d['match']!=expected_match_id or d['decision'] not in ('approve','reject'):raise RuleError('匹配复核目标无效。')
    preview=ReconciliationMatch.objects.select_related('cash_entry').get(pk=d['match'])
    lock_people(actor.pk,preview.prepared_by_id);lock_finance(actor)
    entry=CashEntry.objects.select_for_update().get(pk=preview.cash_entry_id)
    evidence=CashEvidenceVersion.objects.select_for_update().get(pk=preview.evidence_id)
    line=StatementLine.objects.select_for_update().get(pk=preview.line_id)
    row=ReconciliationMatch.objects.select_for_update().get(pk=preview.pk)
    if row.prepared_by_id==actor.pk:raise RuleError('匹配提交人与复核人须为不同账号。')
    target='CONFIRMED' if d['decision']=='approve' else 'REJECTED'
    if row.state!='PENDING':
        if row.state==target and row.reviewed_by_id==actor.pk and row.review_reason==d['reason']:return row,True
        raise RuleError('匹配状态已变化，请核对当前结果。')
    if target=='CONFIRMED':
        from accounts.models import RoleAssignment
        list(RoleAssignment.objects.select_for_update().filter(user_id=row.prepared_by_id,role='MANAGER',clinic_id=entry.clinic_id).order_by('pk'))
        if not preparer_current(row.prepared_by_id,entry.clinic_id,'MANAGER'):raise RuleError('匹配提交人的授权已失效，请退回。')
        require_live_clinic(entry.clinic_id);validate_match(entry,evidence,line,exclude=row.pk)
    row.state=target;row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_reason=_reason(d['reason'])
    row.save(update_fields=['state','reviewed_by','reviewed_at','review_reason'])
    emit(actor,'RECONCILIATION_REVIEWED',row,summary={'decision':target})
    return row,False
