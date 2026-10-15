import re
from django.db import transaction
from adc_core.commands import business_errors
from adc_core.proposals import proposal, read_proposal
from adc_core.rules import RuleError
from care.audit import emit
from finance.reconciliation_models import PaymentAccount, METHODS
from finance.evidence_policies import reconciliation_scope, lock_finance, lock_people, require_live_clinic

CONTRACT='adc.payment-account.v1'

def prepare_account(*,actor,clinic_id=None,code='',method='',account_id=None,active=None):
    reconciliation_scope(actor)
    if actor._adc_workspace.role!='FINANCE':
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('由财务维护收付款渠道账户。')
    if account_id is None:
        if type(clinic_id) is not int:raise RuleError('请选择诊所。')
        require_live_clinic(clinic_id);code=code.strip().upper() if type(code) is str else ''
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{1,39}',code) or method not in dict(METHODS):raise RuleError('账户代码或方式无效。')
        if PaymentAccount.objects.filter(clinic_id=clinic_id,code=code).exists():raise RuleError('本店渠道账户代码已存在。')
        data=dict(clinic=clinic_id,code=code,method=method)
    else:
        account=PaymentAccount.objects.get(pk=account_id)
        if type(active) is not bool or active==account.is_active:raise RuleError('请选择不同于当前状态的启用状态。')
        data=dict(account=account.pk,version=account.lock_version,active=active)
    return dict(data=data,proposal_token=proposal(actor,CONTRACT,('FINANCE',),data))

@business_errors
@transaction.atomic
def confirm_account(*,actor,proposal_token,confirmed,expected_account_id=None):
    if confirmed is not True:raise RuleError('请明确确认渠道账户安排。')
    p=read_proposal(actor,CONTRACT,('FINANCE',),proposal_token);d=p['data']
    lock_people(actor.pk);lock_finance(actor)
    if set(d)=={'clinic','code','method'}:
        if expected_account_id is not None:raise RuleError('确认目标不匹配。')
        prior=PaymentAccount.objects.filter(operation_id=p['operation'],created_by=actor).first()
        if prior:return prior,True
        # Serialize account-code creation per clinic, including concurrent previews.
        from registry.models import Clinic
        Clinic.objects.select_for_update().get(pk=d['clinic'],is_active=True)
        prepare_account(actor=actor,clinic_id=d['clinic'],code=d['code'],method=d['method'])
        row=PaymentAccount.objects.create(clinic_id=d['clinic'],code=d['code'],method=d['method'],created_by=actor,
            operation_id=p['operation'],last_operation_id=p['operation'])
    elif set(d)=={'account','version','active'} and type(d['active']) is bool:
        if expected_account_id!=d['account']:raise RuleError('确认目标不匹配。')
        row=PaymentAccount.objects.select_for_update().get(pk=d['account'])
        if str(row.last_operation_id)==p['operation']:return row,True
        if row.lock_version!=d['version'] or row.is_active==d['active']:raise RuleError('账户状态已变化，请重新预览。')
        row.is_active=d['active'];row.lock_version+=1;row.last_operation_id=p['operation']
        row.save(update_fields=['is_active','lock_version','last_operation_id'])
    else:raise RuleError('渠道账户确认内容无效。')
    emit(actor,'PAYMENT_ACCOUNT_CHANGED',row,summary={'active':row.is_active})
    return row,False
