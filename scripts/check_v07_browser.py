"""Chromium checks of converted source templates; fixture data, no Django/PG server."""
import ast,json,re,shlex,sys,os
from pathlib import Path
from types import SimpleNamespace as NS
from datetime import datetime,timezone
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from guidance.catalog import GUIDES,VERSION
OUT=R/'docs/browser_v07';OUT.mkdir(parents=True,exist_ok=True)
from adc_core.route_manifest import named_routes
paths=named_routes(R)

def route(name,*args,**kw):
 path=paths[name];vals=iter(args)
 return re.sub(r'<(?:[^:>]+:)?([^>]+)>',lambda m:str(kw[m[1]] if m[1] in kw else next(vals)),path)
def convert(s):
 s=re.sub(r'{% load [^%]+%}','',s).replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="fixture">').replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture-context">').replace('{% empty %}','{% else %}').replace('forloop.counter','loop.index').replace('forloop.first','loop.first')
 def url(m):
  bits=shlex.split(m[1]);return '{{ route('+repr(bits[0])+(','+','.join(bits[1:]) if len(bits)>1 else '')+') }}'
 s=re.sub(r'{% url (.*?) %}',url,s);s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
 s=re.sub(r"\|json_script:'([^']+)'",r"|json_script('\1')",s)
 for name,target in [('date','date'),('join','join'),('default_if_none','none_default')]:
  s=re.sub(r'\|'+name+r":'([^']+)'",r'|'+target+r"('\1')",s)
 s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
 return s
sources={str(f.relative_to(R/'templates')):convert(f.read_text()) for f in (R/'templates').rglob('*.html')}
env=Environment(loader=DictLoader(sources),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda s:'/static/'+s)
env.filters['date']=lambda x,fmt: x.strftime('%Y-%m-%d %H:%M') if hasattr(x,'strftime') else str(x)
env.filters['json_script']=lambda v,i:Markup('<script type="application/json" id="'+i+'">'+json.dumps(v).replace('<','\\u003c')+'</script>')
env.filters['none_default']=lambda x,d:d if x is None else x
now=datetime(2026,9,28,9,tzinfo=timezone.utc)
nav=lambda entries:[{'url':route(n),'label':label,'active':False} for n,label in entries]
base={'user':NS(is_authenticated=True,username='multi_demo'),'workspace_label':'诊所主管','workspace_scope':'演示甲店',
 'workspace_role':'MANAGER','workspace_can_switch_role':True,'workspace_home':'/manager/','workspace_has_clinics':True,'workspace_token_value':'fixture-context','build_version':'0.7 · STATIC FIXTURE','messages':[],
 'workspace_nav':nav([('manager_home','本店概览'),('waitlist','本店候补'),('schedule_plans','排程建议'),('operations_dashboard','本店运营分析')])}
form=NS(as_div=Markup('<label><input type="checkbox" name="confirmed">我已核对本次操作及其影响</label>'))
fixtures={
 'roles':('workspaces/select_role.html',{'workspace_role':'','workspace_label':'选择工作身份','workspace_scope':'','workspace_nav':[],'workspace_has_clinics':False,'roles':[{'code':'DENTIST','label':'医生'},{'code':'MANAGER','label':'诊所主管'}]}),
 'clinics':('workspaces/clinics.html',{'workspace_nav':[],'workspace_scope':'请先选择诊所','clinics':[NS(pk=1,name='演示甲店',clinic_code='DEMO-1',postal_address='虚构地址甲'),NS(pk=2,name='演示乙店',clinic_code='DEMO-2',postal_address='虚构地址乙')]}),
 'manager':('workspaces/manager.html',{}),
 'doctor':('workspaces/doctor.html',{'workspace_label':'医生','workspace_scope':'本人负责的接诊','workspace_role':'DENTIST','workspace_home':'/doctor/','workspace_has_clinics':False,'workspace_nav':nav([('doctor_home','接诊首页'),('visits','本人接诊')]),'queue':[]}),
 'plan':('coordination/plan.html',{'plan':NS(pk=1,created_at=now,state='DRAFT',get_state_display='待确认',metadata={'notice':'固定30分钟候选图的最大匹配；非临床能力、椅位或通勤优化。','request_count':2,'cell_count':6,'unassigned':[],'algorithm':'augmenting_path_maximum_matching','status':'OPTIMAL_FOR_ENUMERATED_GRAPH'}),'rows':[{'request_id':1,'doctor':'演示牙医1','start':now,'end':now},{'request_id':2,'doctor':'演示牙医2','start':now,'end':now}],'form':form}),
 'guide':('guidance/task.html',{'base_template':'portal/base.html','workspace_role':'PATIENT','workspace_label':'患者','workspace_scope':'本人资料','workspace_has_clinics':False,'workspace_nav':nav([('portal_home','服务首页'),('portal_appointments','我的预约与账单'),('waitlist','我的候补')]),'task':{'title':GUIDES['patient-cancel'].title,'goal':GUIDES['patient-cancel'].goal,'version':VERSION,'steps':[{'title':s.title,'instruction':s.instruction,'url':route(s.route)+'?guide=patient-cancel&step='+str(i+1)} for i,s in enumerate(GUIDES['patient-cancel'].steps)]}}),
 'guided_form':('coordination/form.html',{'base_template':'portal/base.html','workspace_role':'PATIENT','workspace_label':'患者','workspace_scope':'本人资料','workspace_nav':[],'workspace_has_clinics':False,'title':'登记候补偏好','description':'仅合成数据演示；明确确认后才登记。','button':'确认登记候补','form':NS(as_div=Markup('<label for="test-field">最早可接受时间</label><input id="test-field" type="datetime-local"><label><input type="checkbox">已核对</label>')),'guide_panel':{'key':'patient-wait','title':'登记或确认候补','number':1,'total':4,'instruction':'在表单中填写希望的诊所和时间，核对后亲自提交。','selector':'#test-field','version':VERSION,'task_url':'/guide/task/patient-wait/','exit_url':'?guide=off','next':'?guide=patient-wait&step=2','previous':'','target':'/waitlist/join/?guide=patient-wait&step=1'}}),
}
notice='<div class="fixture-banner">静态检查 FIXTURE · 源码模板转换、合成数据；不是已运行的 Django 页面</div>'
checks=[]
def check(n,v,d=None):
 checks.append({'name':n,'passed':bool(v),'detail':d})
 if not v:print('FAIL',n,d)
htmls={}
for name,(t,context) in fixtures.items():
 html=env.get_template(t).render(**(base|context));html=re.sub(r'(<body[^>]*>)',r'\1'+notice,html,count=1)
 htmls[name]=html;(OUT/(name+'.html')).write_text(html)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
 for width in (1440,390,320):
  for name,html in htmls.items():
   page=browser.new_page(viewport={'width':width,'height':1000 if width==1440 else 844});errs=[];page.on('pageerror',lambda e:errs.append(str(e)))
   clean=re.sub(r'<link[^>]*>','',html);clean=re.sub(r'<script[^>]*>.*?</script>','',clean,flags=re.S);page.set_content(clean)
   for css in (['app.css'] if name not in ('guide','guided_form') else [])+['experience.css','management.css','workspace.css']:
    page.add_style_tag(content=(R/'static'/css).read_text())
   page.add_style_tag(content='.fixture-banner{font:12px/1.5 sans-serif;background:#fff0cf;text-align:center;padding:6px;overflow-wrap:anywhere}')
   for mode in ('standard','comfortable'):
    page.evaluate('(m)=>document.documentElement.dataset.display=m',mode)
    x=page.evaluate('''()=>({w:innerWidth,s:document.documentElement.scrollWidth,f:getComputedStyle(document.documentElement).fontSize,h:[...document.querySelectorAll('.button')].filter(e=>e.offsetWidth).map(e=>e.getBoundingClientRect().height)})''')
    check(f'{name}/{width}/{mode}/overflow',x['s']<=width+1,x)
    check(f'{name}/{width}/{mode}/font',x['f']==('20px' if mode=='comfortable' else '16px'))
    check(f'{name}/{width}/{mode}/targets',all(h>=(55.9 if mode=='comfortable' else 47.9) for h in x['h']))
    if (width==1440 and mode=='standard') or (width==390 and mode=='comfortable'):
     page.screenshot(path=str(OUT/f'{name}_{width}_{mode}.png'),full_page=True)
   if name=='guided_form':
    page.add_script_tag(content=(R/'static/guidance.js').read_text());check(f'guide/highlight/{width}',page.locator('#test-field').evaluate("e=>e.classList.contains('guide-highlight')"))
    page.locator('#test-field').fill('2026-09-29T09:00');page.once('dialog',lambda d:d.dismiss());page.locator('[data-switch]').click()
    check(f'guide/dirty-switch-cancel/{width}',page.locator('#test-field').input_value()=='2026-09-29T09:00')
   check(f'{name}/{width}/javascript',not errs,errs)
   page.close()
 # Actual JS text navigation contract, no live backend: inspect source-rendered step links.
 check('patient-guide-does-not-link-staff',all('/care/' not in s['url'] for s in fixtures['guide'][1]['task']['steps']))
 check('manager-home-no-care-or-finance-write', '/care/' not in htmls['manager'] and '/finance/' not in htmls['manager'])
 check('roles-do-not-include-clinics', 'DEMO-1' not in htmls['roles'] and 'DEMO-2' not in htmls['roles'])
 check('clinics-selected-after-manager-entry','name="clinic"' in htmls['clinics'])
 browser.close()
report={'scope':'Chromium set_content source-template fixtures; no Django, PostgreSQL, actual model call or clinical user study. JS confirm dialog and highlight checked.','passed':sum(x['passed'] for x in checks),'total':len(checks),'checks':checks}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
sys.exit(0 if report['passed']==report['total'] else 1)
