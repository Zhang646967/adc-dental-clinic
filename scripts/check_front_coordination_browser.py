"""Static converted templates and synthetic data only, not Django E2E."""
from pathlib import Path
from types import SimpleNamespace as NS
import json,os,re,shlex,sys
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adc_core.route_manifest import named_routes
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a7/browser')));OUT.mkdir(parents=True,exist_ok=True)
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

base=dict(user=NS(is_authenticated=True,username='front_synthetic'),workspace_label='前台',workspace_role='FRONT_DESK',
 workspace_scope='合成诊所A',workspace_home=route('frontdesk_home'),workspace_nav=[],workspace_can_switch_role=True,
 workspace_has_clinics=True,workspace_token_value='fixture',messages=[],build_version='0.9.0-alpha.7 · STATIC FIXTURE')
slot=dict(id=7,clinic='合成诊所A',dentist='合成牙医一',employee_no='D-DEMO',start='2031年01月02日 09:00',end='2031年01月02日 13:00',active=True)
vr=dict(id=11,visit_no='V-SYNTHETIC-012345678901234567890123456789',patient_no='P-SYNTHETIC-ABCDEFGHIJK',
 start='2031年01月02日 09:00',end='2031年01月02日 09:30',label='已预约',group='promises',
 instruction='先核对患者意思，再到原预约办理。改到原出诊内不会解除阻断。',detail_url=route('visit_detail',11)+'?coord_slot=7',reschedule_url=route('visit_reschedule',11)+'?coord_slot=7')
offer=dict(id=21,request_id=31,visit_id=None,patient_no='P-SYNTHETIC-LMN',start=slot['start'],end=slot['end'],expires='2031年01月01日 16:10',label='有效，等待患者确认',offer=True,
 instruction='先核实患者意思，不自动拒绝或接受。',detail_url=route('wait_offer',21)+'?coord_slot=7',appointment_url='')
assessment=dict(title='仍有关联承诺需要逐条核对',explanation='这是关联列表，不是自动派发的停诊指令。',can_ask_manager_to_recheck=False)
data=dict(slot=slot,assessment=assessment,impact=NS(expired_pending=0),visits=[vr],offers=[offer],visit_count=1,offer_count=1,
 observed_at='2031年01月01日 16:00',contract='FRONT-COORDINATION-09A7.1',read_only=False,unsafe=False,
 visit_number=1,visit_pages=1,offer_number=1,offer_pages=1)
fields='<p><label for="mode">查询范围</label><select name="mode" id="mode"><option>未来及进行中</option><option>全部（含历史）</option></select></p><p><label for="slot_id">出诊编号</label><input name="slot_id" type="number" id="slot_id" min="1"></p>'
listing=dict(form=NS(as_p=Markup(fields),errors=False),rows=[slot|dict(scheduled_count=2,care_count=0,has_effective_offer=True)],total=1,number=1,pages=1,observed_at=data['observed_at'],read_only=False)
scenarios={
 'list':('scheduling/front_coordination_list.html',listing),
 'invalid_query':('scheduling/front_coordination_list.html',listing|dict(form=NS(as_p=Markup(fields+'<p>编号必须大于0</p>'),errors=True),rows=[],total=0)),
 'empty_list':('scheduling/front_coordination_list.html',listing|dict(rows=[],total=0)),
 'mixed':('scheduling/front_coordination_detail.html',data),
 'readonly':('scheduling/front_coordination_detail.html',data|dict(read_only=True,visits=[vr|dict(reschedule_url='')])),
 'clear':('scheduling/front_coordination_detail.html',data|dict(assessment=dict(title='当前未发现维护阻断，可请主管重新核对',explanation='本页未暂停接收新预约。',can_ask_manager_to_recheck=True),visits=[],offers=[],visit_count=0,offer_count=0)),
 'expired':('scheduling/front_coordination_detail.html',data|dict(visits=[],visit_count=0,impact=NS(expired_pending=1),offers=[offer|dict(label='已到期，状态尚未回收',offer=False,detail_url='',instruction='已不占用机会，也不能首次接受。请到本店候补另行核对回收。')])),
 'accepted_history':('scheduling/front_coordination_detail.html',data|dict(visits=[vr|dict(label='已取消',reschedule_url='',instruction='这是保留的历史记录，不重复办理。')],offers=[offer|dict(label='已接受，已关联预约',offer=False,detail_url='',appointment_url=vr['detail_url'],instruction='处理对象已是对应正式预约，不再次确认邀约。原截止时间不代表预约失效。')])),
 'care':('scheduling/front_coordination_detail.html',data|dict(assessment=assessment|dict(title='包含受保护接诊，不应为排班清空记录',explanation='已到诊或已完成记录不走普通取消和改期。其他确需协调的预约仍须逐条核实患者意思。'),visits=[vr|dict(label='已到诊',group='care',reschedule_url='',instruction='受保护接诊。不得为了排班调整取消、改期或删除；由对应业务流程处理。')],offers=[],offer_count=0)),
 'inactive':('scheduling/front_coordination_detail.html',data|dict(slot=slot|dict(active=False),assessment=assessment|dict(title='原出诊已停用，保留关联历史',explanation='不能在本页恢复或改写原出诊。'),visits=[vr|dict(label='已取消',reschedule_url='',instruction='这是保留的历史记录，不重复办理。')],offers=[],offer_count=0)),
 'unsafe':('scheduling/front_coordination_detail.html',data|dict(unsafe=True,assessment=assessment|dict(title='需要受控核对，不能判断已清空'))),
 'read_error':('scheduling/front_coordination_error.html',dict(slot_id=7)),
 'escape':('scheduling/front_coordination_detail.html',data|dict(slot=slot|dict(dentist='<img src=x onerror="window.coordInjected=true">'))),
 'pagination':('scheduling/front_coordination_detail.html',data|dict(visit_number=2,visit_pages=3,visit_previous='/front/coordination/slots/7/?visit_page=1#coord-visits',visit_next='/front/coordination/slots/7/?visit_page=3#coord-visits')),
}
checks=[]
def check(name,ok):checks.append({'name':name,'passed':bool(ok)})
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,fixture) in scenarios.items():
        html=env.get_template(template).render(**(base|fixture))
        html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
        for width in (320,390,1440):
            print('CHECK',key,width,flush=True)
            page=browser.new_page(viewport={'width':width,'height':1000});page.set_content(html)
            for css in ('app.css','experience.css','management.css','workspace.css','availability.css','front_coordination.css'):
                page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for large in (False,True):
                page.evaluate('(x)=>document.documentElement.dataset.display=x?"comfortable":"standard"',large)
                tag=f'{key}/{width}/{large}'
                check(tag+'/no-horizontal-overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/one-h1',page.locator('main h1').count()==1)
                check(tag+'/no-script-injection',not page.evaluate('Boolean(window.coordInjected)'))
                check(tag+'/no-business-post',page.locator('main form[method="post"]').count()==0)
                check(tag+'/no-manager-action-links',page.locator('main a[href*="/change/"],main a[href$="/confirm/"],main a[href$="/slots/new/"]').count()==0)
                check(tag+'/no-auto-action',page.locator('main [onclick],main [onload],main script').count()==0)
                if template.endswith('_detail.html'):
                    check(tag+'/no-freeze-disclosure','不暂停接收新预约' in page.locator('main').inner_text())
                    check(tag+'/manual-reload',page.locator(f'main a[href="{route("front_coordination_detail",7)}"]').count()==1)
                if key=='mixed':
                    check(tag+'/typed-visit-origin',page.locator(f'main a[href="{vr["detail_url"]}"]').count()==1)
                    check(tag+'/typed-offer-origin',page.locator(f'main a[href="{offer["detail_url"]}"]').count()==1)
                if key in ('readonly','care','inactive','unsafe'):
                    check(tag+'/no-reschedule-action',page.locator('main a[href*="/reschedule/"]').count()==0)
                if key=='unsafe':
                    check(tag+'/no-record-identifiers',vr['patient_no'] not in page.locator('main').inner_text())
                if key=='accepted_history':
                    check(tag+'/no-repeat-offer-action',page.locator('main a[href*="/waitlist/offers/"]').count()==0)
                if key=='invalid_query':
                    check(tag+'/bad-filter-not-ignored','请更正查询条件' in page.locator('main').inner_text() and page.locator('main a[href*="/coordination/slots/"]').count()==0)
                if key=='read_error':
                    check(tag+'/unknown-is-not-failure','不代表刚才的改期或取消失败' in page.locator('main').inner_text())
            if width in (390,1440) and key in ('list','mixed','clear','care','unsafe','read_error'):
                page.evaluate('document.documentElement.dataset.display="standard"')
                page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
result={'scope':'Static converted source templates and synthetic facts only; NOT Django/HTTP/PG/E2E.',
 'total':len(checks),'passed':sum(x['passed'] for x in checks),'checks':checks}
(OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2))
for x in checks:
    if not x['passed']:print('FAILED',x['name'])
raise SystemExit(0 if result['total']==result['passed'] else 1)
