"""Bounded catalogue commands. FINANCE writes; HQ/FINANCE read.
Only NEW items and current price changes: no deletion, no clinical qualification policy,
no backdating, and no rewriting TreatmentRecord or Invoice snapshots.
"""
import hashlib
import json
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction, connection
from accounts.finance_access import require_finance_read, lock_finance_write
from workspaces.context import require_active
from adc_core.commands import business_errors
from adc_core.rules import RuleError
from care.audit import emit
from registry.models import TreatmentType
from registry.catalog_rules import validate_price, validate_definition, validate_reason, CatalogInputError

SALT='adc.catalog.current-price.v08a2'

def require_read(actor):
    require_active(actor,('FINANCE','HQ'))
    require_finance_read(actor)

def state_digest(item):
    raw=json.dumps([item.pk,item.code,item.name,item.unit_definition,str(item.standard_unit_price),item.is_active],ensure_ascii=True)
    return hashlib.sha256(raw.encode()).hexdigest()

def price_token(actor,item):
    require_read(actor)
    return signing.dumps({'actor':actor.pk,'item':item.pk,'state':state_digest(item)},salt=SALT)

@business_errors
@transaction.atomic
def create_item(*,actor,code,name,unit,price,reason):
    lock_finance_write(actor)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s,%s)",[8102,1])
    try:
        code,name,unit=validate_definition(code,name,unit)
        price=validate_price(price);reason=validate_reason(reason)
    except CatalogInputError as exc:
        raise RuleError(str(exc))
    if TreatmentType.objects.filter(code=code).exists():
        raise RuleError('项目编码已经存在；不能用新项目覆盖已有目录。')
    item=TreatmentType(code=code,name=name,unit_definition=unit,standard_unit_price=price,is_active=True)
    item.full_clean();item.save()
    emit(actor,'CATALOG_ITEM_CREATED',item,reason=reason,summary={'code':item.code,'current_price':str(price)})
    return item

@business_errors
@transaction.atomic
def change_price(*,actor,item_id,token,price,reason):
    lock_finance_write(actor)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s,%s)",[8102,1])
    item=TreatmentType.objects.select_for_update().get(pk=item_id)
    if not item.is_active:
        raise RuleError('已停用的项目不在本次价格维护范围。')
    try:
        payload=signing.loads(token,salt=SALT,max_age=900)
    except (signing.BadSignature,ValueError,TypeError):
        raise RuleError('价格确认页已过期，请刷新后重新核对。')
    if payload!={'actor':actor.pk,'item':item.pk,'state':state_digest(item)}:
        raise RuleError('目录内容或目标已变化，本次未执行。请刷新后核对。')
    try:
        price=validate_price(price);reason=validate_reason(reason)
    except CatalogInputError as exc:
        raise RuleError(str(exc))
    old=item.standard_unit_price
    if price==old:raise RuleError('新旧单价相同，无需提交变更。')
    item.standard_unit_price=price;item.full_clean();item.save(update_fields=['standard_unit_price'])
    emit(actor,'CATALOG_PRICE_CHANGED',item,reason=reason,summary={'before':str(old),'after':str(price),'historical_lines_unchanged':True})
    return item
