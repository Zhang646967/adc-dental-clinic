"""Bounded plan payload rules, independent of money posting and authority."""
from decimal import Decimal,InvalidOperation
import uuid
from adc_core.rules import RuleError
from clinical.tooth_rules import validate_finding


def text(value,limit,label,required=False):
    if not isinstance(value,str):raise RuleError(label+'填写格式有误。')
    value=value.strip()
    if len(value)>limit or (required and not value):raise RuleError(label+'请填写1至'+str(limit)+'字。')
    return value


def decimal_value(value,places,label,*,unknown=False,positive=True):
    if unknown and value in (None,''):return None
    try:
        number=Decimal(str(value));unit=Decimal('1').scaleb(-places)
        rounded=number.quantize(unit)
        if not number.is_finite() or rounded!=number or (number<=0 if positive else number<0) or number>=Decimal(10)**(12-places):raise ValueError
    except (ValueError,TypeError,InvalidOperation):raise RuleError(label+'请填写允许精度的有效金额或数量。')
    return format(rounded,'f')


def identity(value,label):
    try:
        number=int(value)
        if number<1 or isinstance(value,bool):raise ValueError
    except (ValueError,TypeError):raise RuleError('请选择有效的'+label+'。')
    return number


def step_fields(raw):
    try:key=str(uuid.UUID(str(raw.get('step_key',''))))
    except (ValueError,AttributeError,TypeError):raise RuleError('计划步骤标识已失效，请重新打开草稿。')
    row=dict(step_key=key,treatment_type=identity(raw.get('treatment_type'),'治疗目录'),
        service=identity(raw.get('service'),'预约服务'),description=text(raw.get('description',''),1000,'步骤说明',True),
        goal=text(raw.get('goal',''),1000,'本步骤目标',True),estimated_quantity=decimal_value(raw.get('estimated_quantity'),3,'预计数量'),
        estimated_unit_price=decimal_value(raw.get('estimated_unit_price'),2,'预计单价',unknown=True,positive=False),
        estimate_note=text(raw.get('estimate_note',''),500,'费用说明'),alternative_group=text(raw.get('alternative_group',''),32,'互斥选项组'))
    basis=raw.get('charge_basis','PER_EXECUTION')
    if basis not in ('PER_EXECUTION','ON_COMPLETION'):raise RuleError('请选择本步骤的明确计费时点。')
    row['charge_basis']=basis
    tooth=raw.get('tooth');surface=raw.get('surface','')
    if tooth in (None,''):
        if surface:raise RuleError('填写牙面时请同时明确牙位。')
        row.update(tooth=None,surface='')
    else:
        finding=validate_finding(dict(tooth=identity(tooth,'牙位'),surface=surface,kind='OBSERVATION',detail=row['goal']),'MIXED')
        row.update(tooth=finding['tooth'],surface=finding['surface'])
    if row['estimated_unit_price']=='0.00' and not row['estimate_note']:raise RuleError('预计不计费时请明确说明，未确定费用请选择待评估。')
    return row


def normalize_plan(raw,*,complete=False):
    if not isinstance(raw,dict):raise RuleError('服务器草稿需要重新核对。')
    rows=raw.get('steps',[])
    if not isinstance(rows,list) or len(rows)>30:raise RuleError('每份方案最多30个步骤，请按实际诊疗目标整理。')
    result=dict(summary=text(raw.get('summary',''),3000,'计划摘要',complete),
        discussion_note=text(raw.get('discussion_note',''),2000,'沟通说明'),
        amendment_reason=text(raw.get('amendment_reason',''),500,'版本更正依据'),steps=[step_fields(r) for r in rows])
    keys=[r['step_key'] for r in result['steps']]
    if len(set(keys))!=len(keys):raise RuleError('同一步骤不能在一个版本中重复列入。')
    if complete and not rows:raise RuleError('请至少列出一个拟讨论的步骤，再确认方案版本。')
    return result


def estimate_totals(steps):
    base=[];groups={}
    for row in steps:
        if row['alternative_group']:groups.setdefault(row['alternative_group'],[]).append(row)
        else:base.append(row)
    def subtotal(rows):
        known=Decimal('0');unknown=0
        for row in rows:
            if row['estimated_unit_price'] is None:unknown+=1
            else:known+=(Decimal(row['estimated_quantity'])*Decimal(row['estimated_unit_price'])).quantize(Decimal('.01'))
        return dict(known_subtotal=format(known,'.2f'),unknown_steps=unknown,total=None if unknown else format(known,'.2f'))
    result=subtotal(base)
    result['alternative_groups']={key:[dict(step_key=r['step_key'],**subtotal([r])) for r in rows] for key,rows in groups.items()}
    if groups:result.update(total=None,choice_required=True)
    else:result['choice_required']=False
    return result
