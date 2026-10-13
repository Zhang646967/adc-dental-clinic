"""Static source-template checks, synthetic facts only. No Django/HTTP/DB.
The mock form is NOT evidence for Django's field validation or POST semantics.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import json,os,re,shlex,sys
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adc_core.route_manifest import named_routes
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a6/browser')));OUT.mkdir(parents=True,exist_ok=True)
paths=named_routes(ROOT)
def route(name,*args):
    args=iter(args);return re.sub(r'<(?:[^:>]+:)?[^>]+>',lambda _:str(next(args)),paths[name])
def convert(s):
    s=re.sub(r'{% load [^%]+%}','',s).replace('{% empty %}','{% else %}')
    s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="synthetic-csrf">')
    s=s.replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="synthetic-workspace">')
    def url(m):
        tokens=shlex.split(m[1],posix=False)
        name=tokens[0];args=','.join(tokens[1:])
        return '{{ route('+name+(','+args if args else '')+') }}'
    s=re.sub(r'{% url (.*?) %}',url,s)
    s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
    s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
    s=re.sub(r'\|default:"([^"]+)"',r"|default('\1',true)",s)
    return s.replace('forloop.counter','loop.index')
env=Environment(loader=DictLoader({str(f.relative_to(ROOT/'templates')):convert(f.read_text()) for f in (ROOT/'templates').rglob('*.html')}),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda x:'/static/'+x)
base=dict(user=NS(is_authenticated=True,username='manager_synthetic'),workspace_label='诊所主管',workspace_role='MANAGER',
 workspace_scope='合成诊所A',workspace_home=route('manager_home'),workspace_nav=[],workspace_can_switch_role=True,
 workspace_has_clinics=True,workspace_token_value='fixture',messages=[],build_version='0.9.0-alpha.6 · STATIC FIXTURE')
slot=dict(id=7,clinic='合成诊所A',dentist='合成牙医一',employee_no='D-DEMO',start='2026年10月09日 09:00',end='2026年10月09日 13:00',active=True,future=True)
impact=dict(visit_count=2,blocking_visits=0,offer_count=2,effective_offers=0,expired_pending=1)
data=dict(slot=slot,impact=impact,blocked=[],observed_at='2026年10月08日 16:00',read_only=False,can_replace=True,history=[],predecessor=None)
stop_fields='<input name="state_token" type="hidden" value="synthetic"><p><label for="reason">变更依据</label><select id="reason" name="reason_code" required><option value="">请选择依据</option><option value="PLAN_CHANGED">已核对的出诊计划调整</option></select></p>'
time_fields='<p><label for="start">新开始时间（北京时间）</label><input id="start" name="start" type="datetime-local" value="2026-10-09T09:00" step="60" required></p><p><label for="end">新结束时间（北京时间）</label><input id="end" name="end" type="datetime-local" value="2026-10-09T13:00" step="60" required></p>'
confirm_fields='<input name="proposal_token" type="hidden" value="synthetic"><p><label for="confirmed"><input id="confirmed" name="confirmed" type="checkbox" required>我已核对原时段、拟变更内容及影响；此操作不代患者取消或改期，不删除历史记录</label></p>'
preview=NS(slot_id=7,clinic_name='合成诊所A',dentist_name='合成牙医一',before='2026年10月09日 09:00 — 2026年10月09日 13:00',
 after='2026年10月09日 14:00 — 2026年10月09日 18:00（新记录）',action='replace',reason_label='已核对的出诊计划调整',observed_at='2026年10月08日 16:00')
scenarios={
 'list':('scheduling/availability_list.html',dict(rows=[slot],mode='future',page=NS(number=1,paginator=NS(num_pages=1)),previous_url='',next_url='',read_only=False)),
 'empty':('scheduling/availability_list.html',dict(rows=[],mode='future',page=NS(number=1,paginator=NS(num_pages=1)),read_only=False)),
 'detail':('scheduling/availability_detail.html',data),
 'readonly':('scheduling/availability_detail.html',data|{'read_only':True}),
 'inactive':('scheduling/availability_detail.html',data|{'slot':slot|{'active':False},'blocked':['原时段已停用，历史保留。'],'can_replace':False,'history':[dict(action='调整并新建替代时段',at='2026年10月08日 15:00',reason='已核对的时间录入更正',replacement=8)]}),
 'blocked':('scheduling/availability_blocked.html',data|{'impact':impact|{'blocking_visits':2,'effective_offers':1},'blocked':['仍有2条关联预约，先由前台与患者协调。','有1条有效邀约，等待患者决定或期限结束。']}),
 'replace':('scheduling/availability_change.html',data|{'action':'replace','action_label':'调整并新建替代时段','form':NS(as_p=Markup(time_fields+stop_fields))}),
 'stop':('scheduling/availability_change.html',data|{'action':'deactivate','action_label':'停用原出诊时段','form':NS(as_p=Markup(stop_fields))}),
 'confirm':('scheduling/availability_confirm.html',dict(preview=preview,form=NS(as_p=Markup(confirm_fields)),read_only=False)),
 'recovery':('scheduling/availability_recovery.html',dict(slot_id=7,problem='暂时无法核对保存结果，不代表此前一定失败。请先查原记录。')),
 'escape':('scheduling/availability_detail.html',data|{'slot':slot|{'dentist':'<img src=x onerror="window.slotInjected=true">'}}),
}
checks=[]
def check(name,ok):checks.append({'name':name,'passed':bool(ok)})
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,fixture) in scenarios.items():
        html=env.get_template(template).render(**(base|fixture))
        html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
        for width in (320,390,1440):
            print('CHECK', key, width, flush=True)
            page=browser.new_page(viewport={'width':width,'height':1000});page.set_content(html)
            for css in ('app.css','experience.css','management.css','workspace.css','availability.css'):
                page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for large in (False,True):
                page.evaluate('(x)=>document.documentElement.dataset.display=x?"comfortable":"standard"',large)
                tag=f'{key}/{width}/{large}'
                check(tag+'/no-horizontal-overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'))
                check(tag+'/one-h1',page.locator('main h1').count()==1)
                check(tag+'/no-script-injection',not page.evaluate('Boolean(window.slotInjected)'))
                posts=page.locator('main form[method="post"]');check(tag+'/workspace-token',posts.count()==posts.locator('input[name=workspace_token]').count())
                check(tag+'/csrf-token',posts.count()==posts.locator('input[name=csrfmiddlewaretoken]').count())
                if key=='confirm':
                    check(tag+'/not-saved-disclosure','尚未保存' in page.locator('main').inner_text())
                    check(tag+'/human-confirm-required',page.locator('main input[name=confirmed][required]').count()==1)
                    check(tag+'/correct-target',posts.get_attribute('action')==route('availability_confirm',7))
                if key in ('readonly','blocked','inactive'):
                    check(tag+'/no-confirm-route',page.locator('main a[href*="/change/"]').count()==0 and posts.count()==0)
                if key=='blocked':
                    check(tag+'/coordination-next-step',page.locator(f'main a[href="{route("visits")}"]').count()==1)
                if key=='recovery':
                    check(tag+'/read-original-before-retry',page.locator(f'main a[href="{route("availability_detail",7)}"]').count()==1)
                if key=='replace':
                    page.add_script_tag(content=(ROOT/'static/availability.js').read_text())
                    check(tag+'/end-min-linked',page.locator('main input[name=end]').get_attribute('min')=='2026-10-09T09:01')
                    check(tag+'/end-not-silently-rewritten',page.locator('main input[name=end]').input_value()=='2026-10-09T13:00')
                if key=='inactive':
                    check(tag+'/successor-link',page.locator(f'main a[href="{route("availability_detail",8)}"]').count()==1)
            if width in (390,1440) and key!='escape':
                page.evaluate('document.documentElement.dataset.display="standard"')
                page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
result={'scope':'Static converted source templates + synthetic forms/facts. Not Django E2E or actual database state.',
        'total':len(checks),'passed':sum(x['passed'] for x in checks),'checks':checks}
(OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2))
for x in checks:
    if not x['passed']:print('FAILED',x['name'])
raise SystemExit(0 if result['total']==result['passed'] else 1)
