"""Arithmetic for explicit synthetic results; no reimbursement rate or cash posting."""
from decimal import Decimal, ROUND_DOWN
from adc_core.rules import RuleError
from finance.policies import money

ZERO = Decimal('0.00')


def source_fund_limit(gross, *, payment_class, pre_self_pay_percent, mapping_usable):
    gross = money(gross)
    if not mapping_usable or payment_class not in ('A', 'B') or pre_self_pay_percent is None:
        return ZERO
    share = Decimal(str(pre_self_pay_percent))
    if not share.is_finite() or not ZERO <= share <= 100:
        raise RuleError('目录先自付比例无效，继续待核对。')
    # This is only the line's upper eligible amount. An explicit simulated
    # result may allocate less or nothing; class A does not mean 100% paid.
    return (gross * (1 - share / 100)).quantize(Decimal('0.01'), rounding=ROUND_DOWN)


def checked_split(gross, *, patient_cash, personal_account, fund_amount, fund_limit, mapping_usable):
    total = money(gross)
    cash, personal, fund, limit = map(money, (patient_cash, personal_account, fund_amount, fund_limit))
    if cash + personal + fund != total:
        raise RuleError('患者现金责任、个人账户及基金承担之和须等于原收费金额。')
    if not mapping_usable and (personal or fund):
        raise RuleError('本行缺少可核对适配，须保留自付例外，不能制造医保清偿。')
    if fund > limit:
        raise RuleError('基金承担超过本行已核对的目录上限；不能用其他行平衡。')
    return dict(gross_amount=total, patient_cash=cash, personal_account=personal, fund_amount=fund, fund_limit=limit)


def patient_balance(gross, net_cash, *, personal_account=ZERO, fund_amount=ZERO):
    gross, cash, personal, fund = map(money, (gross, net_cash, personal_account, fund_amount))
    responsibility = gross - personal - fund
    if responsibility < 0:
        raise RuleError('已确认非现金承担超过原账单金额，请核对原结算。')
    return dict(billed=gross, net_received=cash, insurance_personal_account=personal,
        insurance_fund=fund, patient_responsibility=responsibility,
        remaining=max(responsibility-cash, ZERO), refund_due=max(cash-responsibility, ZERO))
