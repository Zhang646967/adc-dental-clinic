"""Bounded correction content. No change to patient/dentist/clinic/event time."""
from decimal import Decimal
from adc_core.rules import RuleError,decimal_value,line_amount

def correction_values(quantity,unit_price,reason):
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=500:
        raise RuleError('请填写更正原因（1至500字）。')
    q=decimal_value(quantity,3,Decimal('999999999.999'))
    p=decimal_value(unit_price,2,Decimal('9999999999.99'))
    amount=line_amount(q,p,reason)
    return q,p,amount,reason.strip()

def guard_review(requester_id,reviewer_id,status,base_id,current_id,expected_revision,actual_revision):
    if requester_id==reviewer_id:raise RuleError('申请人与审核人必须为不同账号。')
    if status!='OPEN':raise RuleError('该更正已经处理，不能再次变更。')
    if base_id!=current_id or expected_revision!=actual_revision:raise RuleError('账单版本已经变化，请重新发起更正。')
