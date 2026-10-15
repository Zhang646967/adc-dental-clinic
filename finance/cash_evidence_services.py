"""Append evidence versions; decisions never rewrite the cash ledger."""
from django.db import transaction
from django.utils import timezone
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal, workspace_binding
from adc_core.rules import RuleError
from adc_core.snapshots import reporting_snapshot
from care.audit import emit
from finance.cash_models import CashEntry
from finance.cash_selectors import cash_scope
from finance.reconciliation_models import PaymentAccount, CashEvidenceVersion, ReconciliationMatch
from finance.statement_csv import text
from finance.evidence_policies import lock_people, lock_finance, preparer_current

REQUEST='adc.cash-evidence.request.v1'
REVIEW='adc.cash-evidence.review.v1'

def checked_account(account_id,clinic_id,reference,*,lock=False):
    if type(account_id) is not int or account_id<=0:raise RuleError('请选择本店已启用的渠道账户。')
    qs=PaymentAccount.objects.select_for_update() if lock else PaymentAccount.objects
    account=qs.filter(pk=account_id,clinic_id=clinic_id,is_active=True).first()
    if account is None:raise RuleError('渠道账户不属于本店或已停用。')
    return account,text(reference)

def effective(entry_id):
    return CashEvidenceVersion.objects.filter(cash_entry_id=entry_id,state='APPROVED').order_by('-version').first()

def create_initial(*,entry,account_id,reference,actor):
    account,reference=checked_account(account_id,entry.clinic_id,reference,lock=True)
    return CashEvidenceVersion.objects.create(cash_entry=entry,account=account,reference=reference,version=1,initial=True,
        operation_id=entry.operation_id,prepared_by=actor,reason='随原始收付款申请提交的合成凭据')

def review_initial(*,entry,actor):
    evidence=CashEvidenceVersion.objects.select_for_update().filter(cash_entry=entry,initial=True,state='PENDING').first()
    # Pre-R1 records retain their explicit missing-evidence status.
    if evidence is None:return
    evidence.state='APPROVED' if entry.state=='POSTED' else 'REJECTED'
    evidence.reviewed_by=actor;evidence.reviewed_at=entry.reviewed_at;evidence.review_reason=entry.review_reason
    evidence.save(update_fields=['state','reviewed_by','reviewed_at','review_reason'])

def prepare_evidence(*,actor,entry_id,payment_account_id,reference,reason):
    from finance.cash_services import _request_scope,_reason
    with reporting_snapshot():
        entry=cash_scope(actor,detail=True).get(pk=entry_id)
        _request_scope(actor,'invoice' if entry.invoice_id else 'equipment',entry.clinic_id)
        if entry.state!='POSTED':raise RuleError('仅对已记账条目补证或更正；待审申请应先处理原审核。')
        previous=entry.evidence_versions.order_by('-version').first()
        if previous and previous.state=='PENDING':raise RuleError('已有待复核凭据，请先处理。')
        account,reference=checked_account(payment_account_id,entry.clinic_id,reference)
        data=dict(entry=entry.pk,previous=previous.pk if previous else None,account=account.pk,
            account_version=account.lock_version,reference=reference,reason=_reason(reason))
        return dict(entry=entry,account=account,data=data,proposal_token=proposal(actor,REQUEST,('FRONT_DESK','MANAGER'),data))

@business_errors
@transaction.atomic
def confirm_evidence(*,actor,proposal_token,confirmed,expected_entry_id):
    from finance.cash_services import _request_scope,_reason
    if confirmed is not True:raise RuleError('请明确确认凭据补证或更正。')
    p=read_proposal(actor,REQUEST,('FRONT_DESK','MANAGER'),proposal_token);d=p['data']
    if set(d)!={'entry','previous','account','account_version','reference','reason'} or d['entry']!=expected_entry_id:raise RuleError('凭据确认目标无效。')
    preview=cash_scope(actor,detail=True).get(pk=d['entry']);lock_people(actor.pk)
    _request_scope(actor,'invoice' if preview.invoice_id else 'equipment',preview.clinic_id,lock=True)
    entry=CashEntry.objects.select_for_update().get(pk=preview.pk)
    prior=CashEvidenceVersion.objects.filter(operation_id=p['operation'],prepared_by=actor,cash_entry=entry).first()
    if prior:return prior,True
    if entry.state!='POSTED':raise RuleError('原款项尚未记账。')
    previous=entry.evidence_versions.order_by('-version').first()
    if (previous.pk if previous else None)!=d['previous'] or (previous and previous.state=='PENDING'):raise RuleError('凭据历史已变化，请重新核对。')
    account,reference=checked_account(d['account'],entry.clinic_id,d['reference'],lock=True)
    if account.lock_version!=d['account_version']:raise RuleError('渠道账户已变化，请重新预览。')
    row=CashEvidenceVersion.objects.create(cash_entry=entry,account=account,reference=reference,
        previous=previous,version=previous.version+1 if previous else 1,prepared_by=actor,
        operation_id=p['operation'],reason=_reason(d['reason']))
    emit(actor,'CASH_EVIDENCE_REQUESTED',row,summary={'entry_id':entry.pk})
    return row,False

def prepare_evidence_review(*,actor,evidence_id,decision,reason):
    from finance.cash_services import _reason
    with reporting_snapshot():
        workspace_binding(actor,('FINANCE',))
        row=CashEvidenceVersion.objects.select_related('cash_entry','account').get(pk=evidence_id)
        from finance.evidence_policies import reconciliation_scope
        reconciliation_scope(actor)
        if row.initial:raise RuleError('原始凭据随收付款申请一同复核。')
        if row.state!='PENDING' or decision not in ('approve','reject') or row.prepared_by_id==actor.pk:raise RuleError('凭据须由不同账号复核待审版本。')
        data=dict(evidence=row.pk,decision=decision,reason=_reason(reason))
        return dict(row=row,data=data,proposal_token=proposal(actor,REVIEW,('FINANCE',),data))

@business_errors
@transaction.atomic
def confirm_evidence_review(*,actor,proposal_token,confirmed,expected_evidence_id):
    from finance.cash_services import _reason
    if confirmed is not True:raise RuleError('请明确确认凭据独立复核。')
    p=read_proposal(actor,REVIEW,('FINANCE',),proposal_token);d=p['data']
    if set(d)!={'evidence','decision','reason'} or d['evidence']!=expected_evidence_id or d['decision'] not in ('approve','reject'):raise RuleError('凭据复核目标无效。')
    preview=CashEvidenceVersion.objects.select_related('cash_entry').get(pk=d['evidence'])
    lock_people(actor.pk,preview.prepared_by_id);lock_finance(actor)
    entry=CashEntry.objects.select_for_update().get(pk=preview.cash_entry_id)
    row=CashEvidenceVersion.objects.select_for_update().get(pk=preview.pk)
    target='APPROVED' if d['decision']=='approve' else 'REJECTED'
    if row.prepared_by_id==actor.pk or row.initial:raise RuleError('须由不同账号复核独立补证申请。')
    if row.state!='PENDING':
        if row.state==target and row.reviewed_by_id==actor.pk and row.review_reason==d['reason']:return row,True
        raise RuleError('该凭据已有其他复核结果。')
    if target=='APPROVED':
        role='FRONT_DESK' if entry.invoice_id else 'MANAGER'
        from accounts.models import RoleAssignment
        list(RoleAssignment.objects.select_for_update().filter(user_id=row.prepared_by_id,role=role,clinic_id=entry.clinic_id).order_by('pk'))
        if entry.state!='POSTED' or not preparer_current(row.prepared_by_id,entry.clinic_id,role):raise RuleError('款项或补证人的授权已失效，请退回。')
    row.state=target;row.reviewed_by=actor;row.reviewed_at=timezone.now();row.review_reason=_reason(d['reason'])
    row.save(update_fields=['state','reviewed_by','reviewed_at','review_reason'])
    if target=='APPROVED':
        # Cash entry lock serializes corrections against both match commands.
        for match in ReconciliationMatch.objects.select_for_update().filter(cash_entry=entry,state__in=['PENDING','CONFIRMED']).order_by('pk'):
            match.state='STALE';match.invalidated_by=actor;match.invalidated_at=row.reviewed_at
            match.save(update_fields=['state','invalidated_by','invalidated_at'])
    emit(actor,'CASH_EVIDENCE_REVIEWED',row,summary={'decision':target})
    return row,False
