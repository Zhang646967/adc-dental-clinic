"""Bounded, deterministic CSV v1. Parsing has no database or file side effects."""
import csv
import io
import re
from datetime import date
from decimal import Decimal
from adc_core.rules import RuleError

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 1000
HEADER = ('transaction_id','booked_on','direction','amount','currency','reference')

def text(value, label='凭据编号', *, empty=False):
    if type(value) is not str:
        raise RuleError(label+'无效。')
    value=value.strip()
    if (not empty and not value) or len(value)>80 or any(ord(c)<32 or ord(c)==127 for c in value):
        raise RuleError(label+'须为1至80个可见字符。')
    return value

def parse(source):
    if type(source) is not bytes or not 1<=len(source)<=MAX_BYTES:
        raise RuleError('请提供不超过2 MiB的UTF-8 CSV。')
    try:
        content=source.decode('utf-8-sig',errors='strict')
        if '\x00' in content:raise ValueError
        reader=csv.reader(io.StringIO(content,newline=''),strict=True)
        if tuple(next(reader))!=HEADER:raise RuleError('CSV表头须严格使用v1模板的六列与顺序。')
        result=[];seen={}
        for number,values in enumerate(reader,2):
            if len(result)>=MAX_ROWS:raise RuleError('每批最多1000行流水。')
            if len(values)!=6:raise RuleError(f'第{number}行不是六列。')
            transaction_id,booked,direction,amount,currency,reference=[v.strip() for v in values]
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',booked):raise ValueError
            booked=date.fromisoformat(booked).isoformat()
            if direction not in ('IN','OUT') or not re.fullmatch(r'[0-9]{1,14}\.[0-9]{2}',amount) or Decimal(amount)<=0:
                raise RuleError(f'第{number}行须为IN/OUT及大于零的两位小数金额。')
            if not re.fullmatch(r'[A-Z]{3}',currency):raise RuleError(f'第{number}行币种须为三个大写英文字母。')
            row=dict(zip(HEADER,(text(transaction_id,'流水编号'),booked,direction,format(Decimal(amount),'.2f'),currency,text(reference,empty=True))))
            if transaction_id in seen and seen[transaction_id]!=row:
                raise RuleError(f'第{number}行与同批流水编号冲突；本批不接受。')
            seen[transaction_id]=row;result.append(row)
        if not result:raise RuleError('CSV至少应有一行流水。')
        return result
    except (UnicodeError,csv.Error,ValueError,StopIteration) as exc:
        raise RuleError('CSV编码、引号或日期无效；请使用UTF-8 v1模板。') from exc

def unique_rows(rows):
    return list({r['transaction_id']:r for r in rows}.values())
