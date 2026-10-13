"""Actual Chromium checks on static fixtures derived from source templates.
Does NOT import Django, connect Postgres, or call an AI provider.
"""
import re,json,shlex,threading,http.server,functools,time,sys
from pathlib import Path
from types import SimpleNamespace as NS
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];OUT=R/'docs/browser';OUT.mkdir(parents=True,exist_ok=True)
FIX=OUT/'fixtures';FIX.mkdir(exist_ok=True)
names={
'dashboard':'/staff.html','staff_assistant':'/staff_ai.html','portal_home':'/patient.html','portal_assistant':'/patient_ai.html',
'portal_slots':'/portal/slots/','portal_appointments':'/portal/appointments/','portal_help':'/portal/help/','portal_login':'/portal/login/',
'logout':'/accounts/logout/','visits':'/visits/','patients':'/patients/','patient_lookup':'/patients/lookup/','visit_create':'/visits/new/','slot_create':'/slots/new/'
}
def route(name,*args):
 if name=='assistant_api':return '/api/assistant/'+str(args[0])+'/'
 return names.get(name,'/'+name.replace('_','/')+'/'+('/'.join(map(str,args))+'/' if args else ''))
def conv(s):
 s=re.sub(r'{% load [^%]+%}','',s)
 s=s.replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture-context">')
 def url(m):
  bits=shlex.split(m.group(1));return '{{ route('+repr(bits[0])+(' ,'+','.join(bits[1:]) if len(bits)>1 else '')+') }}'
 s=re.sub(r'{% url (.*?) %}',url,s)
 s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
 s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="static-fixture-csrf">')
 s=s.replace('{% empty %}','{% else %}').replace('forloop.first','loop.first').replace('forloop.counter','loop.index')
 s=re.sub(r"\|default:'([^']+)'",r"|default('\1', true)",s)
 s=re.sub(r"\|date:'([^']+)'",r"|date('\1')",s)
 s=re.sub(r"\|join:'([^']+)'",r"|join('\1')",s)
 return s
source={str(p.relative_to(R/'templates')).replace('\\','/'):conv(p.read_text()) for p in (R/'templates').rglob('*.html')}
env=Environment(loader=DictLoader(source),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda name:'/static/'+name)
env.filters['date']=lambda value,fmt:'09月23日' if '月' in fmt else '09:00'
common={'workspace_token_value':'fixture-context','workspace_role':'PATIENT','workspace_label':'患者','workspace_scope':'本人记录','workspace_home':'/','workspace_nav':[], 'build_version':'0.7 · STATIC FIXTURE','user':NS(is_authenticated=True,username='patient_demo_a'),'messages':[], 'can_front':True,'is_dentist':False,'can_manage':False,'can_assist':True}
fixture_note='<div style="padding:6px 16px;background:#ffecc9;color:#493409;font-size:12px;text-align:center">静态交互检查 FIXTURE · 使用源码模板转换与固定数据 · 不代表 Django / 数据库已运行</div>'
def render(template,out,**ctx):
 text=env.get_template(template).render(**(common|ctx)).replace('<body','<body',1)
 text=re.sub(r'(<body[^>]*>)',r'\1'+fixture_note,text,count=1)
 (FIX/out).write_text(text,encoding='utf-8')
render('portal/home.html','patient.html',patient=NS(name='门户体验患者1'),upcoming=[],visits_total=0)
render('assistants/chat.html','patient_ai.html',base_template='portal/base.html',audience='patient',assistant_title='预约与就诊小助手',is_remote=True,examples=['我想预约','查一下我的预约','怎么取消预约','账单怎么看','字体太小'])
render('assistants/chat.html','staff_ai.html',base_template='base.html',user=NS(is_authenticated=True,username='front_a'),audience='staff',assistant_title='员工业务助手',is_remote=True,examples=['今天的工作概览','改期有什么规则','接诊需要确认什么','结算单怎么生成','使用大字模式'])
render('dashboard.html','staff.html',user=NS(is_authenticated=True,username='front_a'),total=0,status_counts=[])
review=Markup('<input type="hidden" name="expected_version" value="1"><label for="allergy">本次询问结果</label><select id="allergy"><option>已确认无已知过敏</option><option>仍然未知</option><option>已知过敏</option></select><label for="known">已知过敏项目</label><div><input type="checkbox" id="known"> 乳胶</div><label><input type="checkbox"> 我已向患者复核上述信息。</label>')
treatment=Markup('<label for="treatment">实际提供的治疗</label><select id="treatment"><option>演示洁治 · 99.99 元 / 标准单位</option></select><label for="quantity">标准单位数量</label><input id="quantity" type="number" value="1.125"><label for="price">零价格说明（如适用）</label><input id="price"><label><input type="checkbox"> 我确认该治疗已经实际提供。</label>')
render('care/workspace.html','care.html',user=NS(is_authenticated=True,username='doctor_a'),can_front=False,is_dentist=True,visit=NS(pk=1,patient=NS(name='门户体验患者1'),clinic=NS(name='演示甲店'),dentist=NS(name='演示牙医1'),status='CHECKED_IN',get_status_display='已到诊',lock_version=2),record=NS(total_amount='112.49',allergy_review_snapshot={}),lines=[NS(pk=1,name_snapshot='演示洁治',unit_snapshot='标准单位',quantity='1.125',unit_price='99.99',line_amount='112.49')],allergy_form=NS(as_div=review),treatment_form=NS(as_div=treatment),removal_form=NS(errors=''))
# Use set_content because navigation is administratively blocked in this environment.
# Browser DOM/CSS/JS are real. fetch/storage are explicit controlled test doubles.
results=[]
def ok(name,passed,details=None):
 results.append({'check':name,'passed':bool(passed),'details':details})
 if not passed: print('FAIL',name,details)
def mount(page,name,reset=True):
 text=(FIX/name).read_text()
 text=re.sub(r'<link[^>]*>', '', text)
 text=re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.S)
 page.set_content(text)
 if name in ('staff.html','staff_ai.html','care.html'):page.add_style_tag(content=(R/'static/app.css').read_text())
 page.add_style_tag(content=(R/'static/experience.css').read_text())
 page.add_style_tag(content=(R/'static/management.css').read_text())
 page.add_style_tag(content=(R/'static/workspace.css').read_text())
 if reset:
  page.evaluate("""() => {
   window._storage={}; Object.defineProperty(window,'localStorage',{configurable:true,value:{
    getItem:k=>window._storage[k]||null,setItem:(k,v)=>window._storage[k]=String(v),removeItem:k=>delete window._storage[k]}});
   window._requests=[];window._status=200;window._body={
    mode_label:'演示响应 · 非真实AI调用',title:'<img src=x onerror=alert(1)>',answer:'系统规则说明',facts:['本人数据测试样本'],
    links:[{label:'禁止外链',url:'//evil.example'},{label:'我的预约',url:'/portal/appointments/'}],source:'FIXTURE-ONLY',
    as_of:'2026-09-22T12:00:00Z',notice:'未执行业务写入'};
   window.fetch=async (url,opts)=>{window._requests.push({url,headers:opts.headers,body:JSON.parse(opts.body)});
    return {ok:window._status===200,status:window._status,json:async()=>window._body};};
  }""")
 page.add_script_tag(content=(R/'static/experience.js').read_text())
 if 'ai.html' in name: page.add_script_tag(content=(R/'static/assistant.js').read_text())
 page.wait_for_timeout(50)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=__import__('os').environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
 for width in (1440,390,320):
  context=browser.new_context(viewport={'width':width,'height':1000 if width==1440 else 844},device_scale_factor=1)
  errors=[]
  for name in ('patient.html','patient_ai.html','staff_ai.html','care.html'):
   page=context.new_page();page.on('pageerror',lambda err:errors.append(str(err)));mount(page,name)
   for mode in ('standard','comfortable'):
    if mode=='comfortable':page.locator('.mode-toggle').click();page.wait_for_timeout(50)
    measurements=page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,fontsize:getComputedStyle(document.documentElement).fontSize,
      targets:[...document.querySelectorAll('button.button,a.button')].filter(x=>x.offsetWidth).map(x=>({h:x.getBoundingClientRect().height,t:x.textContent.trim()}))})""")
    ok(f'{name}/{width}/{mode}/no-horizontal-overflow',measurements['scroll']<=width+1,measurements if measurements['scroll']>width+1 else None)
    ok(f'{name}/{width}/{mode}/primary-targets',all(x['h']>=47.9 for x in measurements['targets']))
    ok(f'{name}/{width}/{mode}/font',measurements['fontsize']==('20px' if mode=='comfortable' else '16px'))
   if width==1440 and name in ('patient.html','staff_ai.html'):
    page.locator('.mode-toggle').click();page.screenshot(path=str(OUT/(name.replace('.html','')+'_desktop.png')),full_page=True)
   if width==390 and name in ('patient_ai.html','patient.html'):
    page.screenshot(path=str(OUT/(name.replace('.html','')+'_large_mobile.png')),full_page=True)
   page.close()
  ok(f'javascript-no-errors/{width}',not errors,errors);context.close()
 context=browser.new_context(viewport={'width':1280,'height':1000});page=context.new_page();mount(page,'patient_ai.html')
 page.locator('.quick-prompt').first.click();ok('quick-prompt-requires-explicit-send',page.evaluate('window._requests.length')==0)
 page.locator('input[name=consent]').check();page.locator('.assistant-form button[type=submit]').click();page.wait_for_selector('.message.assistant')
 req=page.evaluate('window._requests[0]')
 ok('fetch-mock-check-csrf-and-payload',req['body']=={'message':'我想预约','consent':True} and req['headers']['X-CSRFToken']=='static-fixture-csrf')
 ok('answer-text-not-html',page.locator('.message.assistant img').count()==0 and '<img' in page.locator('.message.assistant h3').inner_text())
 ok('external-link-rejected',page.locator('a[href="//evil.example"]').count()==0)
 ok('local-voice-fallback-no-auto-read',page.locator('.read-answer').is_disabled())
 page.locator('.clear-chat').click();ok('clear-removes-dom-content',page.locator('.chat-log').inner_text()=='')
 stored=page.evaluate('JSON.stringify(window._storage)');ok('mock-storage-no-transcript','预约' not in stored and 'fixture' not in stored)
 page.locator('.mode-toggle').click();mount(page,'patient_ai.html',reset=False)
 ok('mock-storage-restores-mode-on-reinitialize',page.locator('.mode-toggle').get_attribute('aria-pressed')=='true')
 page.evaluate("window._status=429;window._body={error:'请求次数已达上限'}")
 before=page.evaluate('window._requests.length')
 page.locator('#assistant-message').fill('预约');page.locator('.assistant-form button[type=submit]').click();page.wait_for_function("document.querySelector('.request-status').textContent.includes('上限')")
 ok('quota-error-visible-retry-not-automatic',not page.locator('.assistant-form button[type=submit]').is_disabled() and page.evaluate('window._requests.length')==before+1)
 page.close();page=context.new_page();mount(page,'patient.html');page.keyboard.press('Tab')
 ok('keyboard-skip-link-first',page.evaluate("document.activeElement.classList.contains('skip')"))
 page.keyboard.press('Enter');ok('keyboard-skip-target',page.evaluate("document.activeElement.id")=='main')
 page.emulate_media(reduced_motion='reduce');ok('reduced-motion-rule',page.evaluate("getComputedStyle(document.documentElement).scrollBehavior")=='auto')
 context.close();browser.close()
report={'scope':'Chromium set_content on translated source templates. fetch/localStorage controlled doubles; NO Django/PG end-to-end, real browser-origin storage, or live AI.',
        'passed':sum(x['passed'] for x in results),'total':len(results),'checks':results}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
sys.exit(0 if all(x['passed'] for x in results) else 1)
