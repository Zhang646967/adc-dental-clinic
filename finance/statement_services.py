"""Private staged imports, atomically accepted; no ledger effects."""
import hashlib
from django.db import transaction
from django.utils import timezone
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from equipment.policies import manager_clinic
from finance.evidence_policies import lock_people
from finance.cash_evidence_services import checked_account
from finance.reconciliation_models import StatementBatch, StatementLine
from finance.statement_csv import parse, unique_rows, HEADER

CONTRACT='adc.statement-import.v1'

def line_values(line):
    return dict(transaction_id=line.transaction_id,booked_on=line.booked_on.isoformat(),direction=line.direction,
        amount=format(line.amount,'.2f'),currency=line.currency,reference=line.reference)

def classify(account_id,rows):
    unique=unique_rows(rows)
    existing={r.transaction_id:r for r in StatementLine.objects.filter(account_id=account_id,transaction_id__in=[r['transaction_id'] for r in unique])}
    fresh=[]
    for row in unique:
        old=existing.get(row['transaction_id'])
        if old is None:fresh.append(row)
        elif line_values(old)!=row:raise RuleError('流水编号与已接受历史冲突；本批没有接受新流水。')
    return fresh,len(rows)-len(fresh)

@business_errors
@transaction.atomic
def prepare_import(*,actor,payment_account_id,source_bytes):
    rows=parse(source_bytes)
    lock_people(actor.pk);clinic=manager_clinic(actor,lock=True)
    account,_=checked_account(payment_account_id,clinic,'IMPORT',lock=True)
    fresh,skipped=classify(account.pk,rows)
    batch=StatementBatch.objects.create(account=account,created_by=actor,source_bytes=source_bytes,
        digest=hashlib.sha256(source_bytes).hexdigest(),normalized_rows=rows)
    emit(actor,'STATEMENT_STAGED',batch,summary={'rows':len(rows)})
    data=dict(batch=batch.pk,digest=batch.digest,account_version=account.lock_version)
    return dict(batch=batch,new_count=len(fresh),skipped_count=skipped,
        proposal_token=proposal(actor,CONTRACT,('MANAGER',),data))

@business_errors
@transaction.atomic
def confirm_import(*,actor,proposal_token,confirmed):
    if confirmed is not True:raise RuleError('请明确确认接受本批合成流水。')
    p=read_proposal(actor,CONTRACT,('MANAGER',),proposal_token);d=p['data']
    if set(d)!={'batch','digest','account_version'} or type(d['batch']) is not int:raise RuleError('导入确认无效。')
    lock_people(actor.pk);clinic=manager_clinic(actor,lock=True)
    preview=StatementBatch.objects.get(pk=d['batch'],created_by=actor,account__clinic_id=clinic)
    # One account lock serializes overlapping batches before row uniqueness.
    from finance.reconciliation_models import PaymentAccount
    account=PaymentAccount.objects.select_for_update().get(pk=preview.account_id)
    batch=StatementBatch.objects.select_for_update().get(pk=preview.pk)
    if batch.state=='IMPORTED':
        if str(batch.operation_id)==p['operation']:return batch,True
        raise RuleError('该批已有其他确认结果。')
    if not account.is_active or account.lock_version!=d['account_version']:raise RuleError('渠道账户已变化，请重新上传预览。')
    raw=bytes(batch.source_bytes);rows=parse(raw)
    if batch.parser_version!='csv-v1' or batch.digest!=d['digest'] or hashlib.sha256(raw).hexdigest()!=batch.digest or rows!=batch.normalized_rows:
        raise RuleError('导入证据摘要不一致，未接受流水。')
    fresh,skipped=classify(account.pk,rows)
    StatementLine.objects.bulk_create([StatementLine(batch=batch,account=account,**r) for r in fresh])
    batch.state='IMPORTED';batch.operation_id=p['operation'];batch.imported_at=timezone.now();batch.new_count=len(fresh);batch.skipped_count=skipped
    batch.save(update_fields=['state','operation_id','imported_at','new_count','skipped_count'])
    emit(actor,'STATEMENT_IMPORTED',batch,summary={'accepted':len(fresh),'duplicates':skipped})
    return batch,False
