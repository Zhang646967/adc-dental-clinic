"""Chromium QA using translated source templates and SYNTHETIC static data.
Not Django rendering, not PostgreSQL and not remote AI. No external network.
"""
from pathlib import Path
import json,re,shlex,os,sys
from types import SimpleNamespace as NS
from datetime import datetime,timezone
from decimal import Decimal as D
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from finance.policies import CostInput,calculate_profit
from operations.policies import summarize
R=Path(__file__).resolve().parents[1];OUT=R/'docs/browser_v05';OUT.mkdir(parents=True,exist_ok=True)
def convert(s):
 s=re.sub(r'{% load [^%]+%}','',s).replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture-context">').replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="STATIC-ONLY">').replace('{% empty %}','{% else %}')
 def route(m):
  words=shlex.split(m[1]);return '{{ route('+repr(words[0])+(','+','.join(words[1:]) if len(words)>1 else '')+') }}'
 s=re.sub(r'{% url (.*?) %}',route,s)
 s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
 s=re.sub(r"\|default_if_none:'([^']+)'",r"|none_default('\1')",s)
 s=re.sub(r"\|date:'([^']+)'",r"|date('\1')",s)
 s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
 return s
sources={str(p.relative_to(R/'templates')):convert(p.read_text()) for p in (R/'templates').rglob('*.html')}
env=Environment(loader=DictLoader(sources),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=lambda name,**kw:'/'+name+'/',asset=lambda x:'/static/'+x)
env.filters['none_default']=lambda v,x:x if v is None else v
env.filters['date']=lambda v,fmt: v.strftime('%Y-%m-%d %H:%M') if hasattr(v,'strftime') else str(v)
now=datetime(2026,9,27,9,tzinfo=timezone.utc)
form=NS(as_div=Markup('<label for="amount">核对金额（合成表单）</label><input id="amount" value="100.00"><label><input type="checkbox">我已核对</label>'))
common={'workspace_label':'财务','workspace_scope':'全链财务','workspace_role':'FINANCE','workspace_home':'/','workspace_nav':[], 'user':NS(is_authenticated=True,username='finance_demo'),'messages':[],'can_finance':True,'can_correct':True,'can_operations':True,'can_assist':True,'build_version':'0.5 · STATIC FIXTURE','can_write':True}
result=calculate_profit({1:D('100000'),2:D('20000')},[CostInput(1,'CONFIRMED',D('20000'),D('30000')),CostInput(2,'CONFIRMED',D('15000'),D('15000'))],True)
rows=[NS(id=1,employee_no='D001',dentist_name='模拟牙医甲',status='CONFIRMED',invoice_count=320,income=D('100000.00'),supply=D('20000.00'),operating=D('30000.00')),NS(id=2,employee_no='D002',dentist_name='模拟牙医乙',status='CONFIRMED',invoice_count=90,income=D('20000.00'),supply=D('15000.00'),operating=D('15000.00'))]
report=NS(id=1,year=2026,number=3,policy_version='ADC-FIN-0.5',as_of=now,in_progress=True,result=result,rows=rows,unlisted=[],roster_status='CONFIRMED')
missing=NS(**report.__dict__);missing.result=calculate_profit({1:D('100000')},[CostInput(1,'MISSING',None,None)],False);missing.rows=[NS(id=1,employee_no='D001',dentist_name='模拟牙医甲',status='MISSING',invoice_count=320,income=D('100000.00'),supply=None,operating=None)]
m=summarize([('COMPLETED','',80),('CANCELLED','PATIENT',10),('NO_SHOW','',5),('CANCELLED','CLINIC',3),('SCHEDULED','',2)])
ops={'metrics':m,'rows':[{'code':'CL01','name':'模拟甲诊所','metrics':m}], 'as_of':now,'start':now.date().replace(day=1),'end':now.date(),'policy_version':'ADC-OPS-0.5','future':20,'replaced':7}
filters=NS(as_div=Markup('<div><label for="start">预约开始日期</label><input type="date" id="start" value="2026-09-01"></div><div><label for="end">结束日期</label><input type="date" id="end" value="2026-09-27"></div><div><label for="clinic">诊所</label><select id="clinic"><option>全部授权诊所</option></select></div>'))
req=NS(pk=1,requester=NS(username='doctor_a'),requested_at=now,reason='合成演示：实际一单位，原单误录两单位。',get_status_display='待审核')
fixtures={
'finance_ready':('finance/detail.html',dict(report=report,member_form=form,confirm_form=form)),
'finance_missing':('finance/detail.html',dict(report=missing,member_form=form,confirm_form=form)),
'operations':('operations/dashboard.html',dict(form=filters,report=ops)),
'correction':('care/correction_detail.html',dict(req=req,old_total=D('200.00'),new_total=D('100.00'),old_lines=[dict(line_no=1,name_snapshot='模拟项目',quantity=D('2'),unit_price=D('100'),line_amount=D('200'))],new_lines=[dict(line_no=1,name_snapshot='模拟项目',quantity=D('1'),unit_price=D('100'),line_amount=D('100'))],form=form,can_review=True)),
}
notice='<div style="background:#fff4de;padding:8px 12px;font-size:12px;text-align:center">STATIC FIXTURE · 源码模板转换 + 合成数据 · 非 Django/数据库运行截图</div>'
results=[]
def check(name,condition,detail=None):results.append({'check':name,'passed':bool(condition),'detail':detail})
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),args=['--no-sandbox'])
 for width in (1440,390,320):
  for name,(template,ctx) in fixtures.items():
   html=env.get_template(template).render(**(common|ctx));html=re.sub(r'(<body[^>]*>)',r'\1'+notice,html,count=1)
   (OUT/(name+'.html')).write_text(html)
   html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]*>.*?</script>','',html,flags=re.S)
   page=browser.new_page(viewport={'width':width,'height':1000 if width==1440 else 844});errors=[];page.on('pageerror',lambda e:errors.append(str(e)));page.set_content(html)
   for css in ('app.css','experience.css','management.css','workspace.css'):page.add_style_tag(content=(R/'static'/css).read_text())
   for mode in ('standard','comfortable'):
    page.evaluate('(m)=>document.documentElement.dataset.display=m',mode)
    data=page.evaluate('''()=>({w:innerWidth,sw:document.documentElement.scrollWidth,font:getComputedStyle(document.documentElement).fontSize,
      heights:[...document.querySelectorAll('button,.button')].filter(e=>e.offsetWidth).map(e=>e.getBoundingClientRect().height)})''')
    check(f'{name}/{width}/{mode}/overflow',data['sw']<=width+1,data)
    check(f'{name}/{width}/{mode}/font',data['font']==('20px' if mode=='comfortable' else '16px'))
    check(f'{name}/{width}/{mode}/targets',all(h>=47.9 for h in data['heights']))
    if width==1440 and mode=='standard':page.screenshot(path=str(OUT/(name+'_desktop.png')),full_page=True)
    if width==390 and mode=='comfortable' and name in ('operations','finance_ready'):page.screenshot(path=str(OUT/(name+'_mobile.png')),full_page=True)
   check(f'{name}/{width}/js',not errors,errors)
   page.close()
 browser.close()
summary={'scope':'Static translated templates with synthetic data; no Django/PG/API execution','total':len(results),'passed':sum(x['passed'] for x in results),'checks':results}
(OUT/'results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in summary.items() if k!='checks'},ensure_ascii=False))
for x in results:
 if not x['passed']:print('FAIL',x)
sys.exit(0 if all(x['passed'] for x in results) else 1)
