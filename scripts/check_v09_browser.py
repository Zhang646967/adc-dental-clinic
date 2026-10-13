"""Source-template fixture checks in Chromium. NOT Django/DB end-to-end testing."""
import json, os, re, shlex, sys
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from jinja2 import Environment, DictLoader, ChainableUndefined
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from adc_core.route_manifest import named_routes
from guidance.result_rules import WaitFact,OfferFact,VisitFact,assess_wait,CONTRACT_VERSION
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(R/'docs/evidence_v09a3/results_regression')));OUT.mkdir(parents=True,exist_ok=True)
paths=named_routes(R)
def route(name,*args):
    it=iter(args);return re.sub(r'<(?:[^:>]+:)?[^>]+>',lambda m:str(next(it)),paths[name])
def convert(s):
    s=re.sub(r'{% load [^%]+%}','',s).replace('{% empty %}','{% else %}')
    s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="fixture">').replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture">')
    def url(m):
        b=shlex.split(m[1]);return '{{ route('+repr(b[0])+(','+','.join(b[1:]) if len(b)>1 else '')+') }}'
    s=re.sub(r'{% url (.*?) %}',url,s)
    s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
    s=re.sub(r"\|date:'([^']+)'",r"|date('\1')",s)
    return s.replace('forloop.counter','loop.index')
sources={str(f.relative_to(R/'templates')):convert(f.read_text()) for f in (R/'templates').rglob('*.html')}
env=Environment(loader=DictLoader(sources),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda n:'/static/'+n)
env.filters['date']=lambda value,fmt:value.astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S') if isinstance(value,datetime) else str(value)
base=dict(user=NS(is_authenticated=True,username='patient_demo_a'),workspace_label='患者',workspace_scope='本人范围',workspace_role='PATIENT',workspace_home='/portal/',workspace_nav=[],workspace_can_switch_role=False,workspace_has_clinics=False,workspace_token_value='fixture',build_version='0.9.0-alpha.3 STATIC FIXTURE',messages=[],base_template='portal/base.html',contract=CONTRACT_VERSION,entry_id=3)
now=datetime(2026,9,27,7,tzinfo=timezone.utc);start=now+timedelta(days=1)
v=VisitFact(8,'V-SYNTHETIC-THIS-IS-NOT-A-LIVE-BOOKING',1,1,1,start,start+timedelta(minutes=30),'SCHEDULED')
o=OfferFact(9,'PENDING',1,1,v.start,v.end,now+timedelta(minutes=15))
from dataclasses import replace
w=WaitFact(3,1,1,'OFFERED',start,start+timedelta(hours=2),(o,))
scenarios={
 'waiting':base|dict(result=assess_wait(replace(w,state='WAITING',offers=()),now),observed_at=now,target_url='/waitlist/'),
 'pending':base|dict(result=assess_wait(w,now),observed_at=now,target_url='/waitlist/offer/9/'),
 'expired':base|dict(result=assess_wait(w,now+timedelta(minutes=15)),observed_at=now,target_url='/waitlist/'),
 'booked':base|dict(result=assess_wait(replace(w,state='BOOKED',offers=(replace(o,state='ACCEPTED',visit=v),)),now),observed_at=now,target_url='/portal/visits/8/'),
 'cancelled':base|dict(result=assess_wait(replace(w,state='BOOKED',offers=(replace(o,state='ACCEPTED',visit=replace(v,status='CANCELLED')),)),now),observed_at=now,target_url='/portal/visits/8/'),
 'inconsistent':base|dict(result=assess_wait(replace(w,state='BOOKED',offers=()),now),observed_at=now,target_url='/waitlist/'),
 'unavailable':base|dict(problem='暂时无法核对。这不代表之前的确认失败；不要重复接受邀约。',error_code='UNAVAILABLE'),
 'stale':base|dict(problem='身份或诊所已经变化，请返回当前工作台。',error_code='CONTEXT_CHANGED')}
results=[]
def check(name,yes):results.append({'name':name,'passed':bool(yes)})
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for name,data in scenarios.items():
        html=env.get_template('guidance/result_unavailable.html' if name=='unavailable' else 'guidance/result.html').render(**(data|{'home_url':'/'}))
        html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
        html=html.replace('<body class="patient-body">','<body class="patient-body"><p class="notice">静态合成数据／真实模板检查，不是运行数据库截图。</p>')
        for width in (320,390,1440):
            page=browser.new_page(viewport={'width':width,'height':950});page.set_content(html)
            for css in ('experience.css','workspace.css'):page.add_style_tag(content=(R/'static'/css).read_text())
            for comfortable in (False,True):
                page.evaluate('(v)=>document.documentElement.dataset.display=v?"comfortable":"standard"',comfortable)
                tag=f'{name}/{width}/{comfortable}'
                check(tag+'/no-overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/font-size',page.evaluate('getComputedStyle(document.documentElement).fontSize')==('20px' if comfortable else '16px'))
                check(tag+'/heading',page.locator('h1').count()==1)
                check(tag+'/no-accept-form',page.locator('form[action*="/offer/"]').count()==0)
                check(tag+'/no-business-accept-button',page.locator('button[value="accept"]').count()==0)
            if name in ('booked','cancelled','unavailable') and width==390:page.screenshot(path=str(OUT/f'{name}_{width}.png'),full_page=True)
            if name=='booked':check(f'{name}/{width}/exact-link',page.locator('a[href="/portal/visits/8/"]').count()==1)
            if name in ('unavailable','stale'):check(f'{name}/{width}/alert',page.locator('[role="alert"]').count()==1)
            page.close()
    browser.close()
report={'scope':'Chromium source-template / synthetic data, no Django, no PostgreSQL, no external AI','total':len(results),'passed':sum(r['passed'] for r in results),'checks':results}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='checks'}));sys.exit(0 if report['passed']==report['total'] else 1)
