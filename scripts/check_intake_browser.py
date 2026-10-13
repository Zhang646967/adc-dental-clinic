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
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a8/browser')));OUT.mkdir(parents=True,exist_ok=True)
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
 workspace_has_clinics=True,workspace_token_value='fixture',messages=[],build_version='0.9.0-alpha.8 · STATIC FIXTURE')
slot=dict(id=7,clinic='合成诊所A',dentist='合成牙医一',employee_no='D-DEMO',start='2031年01月02日 09:00',end='2031年01月02日 13:00',active=True,future=True,paused=False,intake_editable=True)
impact=NS(visit_count=2,blocking_visits=2,offer_count=2,effective_offers=1,expired_pending=1)
data=dict(slot=slot,impact=impact,blocked=['仍有既有预约和有效邀约，不允许直接停用'],observed_at='2031年01月01日 16:00',read_only=False,can_replace=False,history=[],predecessor=None)
reason_fields='<input name="state_token" type="hidden" value="synthetic"><p><label for="reason">已核对的操作依据</label><select name="reason" id="reason" required><option value="">请选择</option><option value="COORDINATION">为已核对的出诊协调暂停新增</option></select></p>'
confirm_fields='<input name="proposal_token" type="hidden" value="synthetic"><p><label for="confirmed"><input type="checkbox" name="confirmed" id="confirmed" required>我已核对接收状态及影响；已有预约和有效邀约不被取消。</label></p>'
change=dict(slot_id=7,clinic=slot['clinic'],dentist=slot['dentist'],start=slot['start'],end=slot['end'],paused=False,
 action='pause',action_label='暂停接收新预约',form=NS(as_p=Markup(reason_fields)),impact=impact,read_only=False)
preview=dict(slot_id=7,clinic=slot['clinic'],dentist=slot['dentist'],start=slot['start'],end=slot['end'],
 action='pause',action_label='暂停接收新预约',before='接收新预约',after='已暂停新增',reason='为已核对的出诊协调暂停新增',impact=impact,observed_at='2031年01月01日 16:00')
confirm=dict(preview=preview,form=NS(as_p=Markup(confirm_fields)),read_only=False)
front=dict(slot=slot|dict(paused=True),observed_at=data['observed_at'],contract='FRONT-COORDINATION-09A7.1',
 assessment=NS(title='仍有关联承诺需要逐条核对',explanation='暂停不等于已协调完成。',can_ask_manager_to_recheck=False),
 impact=impact,visits=[],offers=[],visit_count=2,offer_count=2,unsafe=False,read_only=False,
 visit_number=1,visit_pages=1,offer_number=1,offer_pages=1)
scenarios={
 'manager_open':('scheduling/availability_detail.html',data),
 'manager_paused':('scheduling/availability_detail.html',data|dict(slot=slot|dict(paused=True))),
 'manager_inactive':('scheduling/availability_detail.html',data|dict(slot=slot|dict(active=False,intake_editable=False))),
 'manager_ended':('scheduling/availability_detail.html',data|dict(slot=slot|dict(future=False,intake_editable=False))),
 'manager_readonly':('scheduling/availability_detail.html',data|dict(read_only=True)),
 'pause_edit':('scheduling/intake_change.html',change),
 'resume_edit':('scheduling/intake_change.html',change|dict(paused=True,action='resume',action_label='恢复接收新预约')),
 'confirm_pause':('scheduling/intake_confirm.html',confirm),
 'confirm_resume':('scheduling/intake_confirm.html',confirm|dict(preview=preview|dict(action='resume',action_label='恢复接收新预约',before='已暂停新增',after='接收新预约'))),
 'confirm_readonly':('scheduling/intake_confirm.html',confirm|dict(read_only=True)),
 'front_paused':('scheduling/front_coordination_detail.html',front),
 'front_open':('scheduling/front_coordination_detail.html',front|dict(slot=slot)),
 'escape':('scheduling/intake_change.html',change|dict(dentist='<img src=x onerror="window.intakeInjected=1">')),
 'unknown':('scheduling/availability_recovery.html',dict(slot_id=7,problem='暂时无法核对接收状态，不代表前次操作失败；请先查看原出诊，不自动重发。')),
}
checks=[]
def check(name,value):checks.append(dict(name=name,passed=bool(value)))
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,fixture) in scenarios.items():
        role=base if not key.startswith('front_') else base|dict(workspace_role='FRONT_DESK',workspace_label='前台')
        html=env.get_template(template).render(**(role|fixture))
        html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
        for width in (320,390,1440):
            page=browser.new_page(viewport=dict(width=width,height=1050));page.set_content(html)
            for css in ['app.css','experience.css','management.css','workspace.css','availability.css','front_coordination.css']:
                page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for comfortable in (False,True):
                page.evaluate('(x)=>document.documentElement.dataset.display=x?"comfortable":"standard"',comfortable)
                tag=f'{key}/{width}/{comfortable}';text=page.locator('main').inner_text()
                check(tag+'/fits',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/heading',page.locator('main h1').count()==1)
                check(tag+'/no-injection',not page.evaluate('Boolean(window.intakeInjected)'))
                check(tag+'/no-inline-action',page.locator('main [onclick],main [onload],main script').count()==0)
                if key in ('manager_open','manager_paused'):
                    check(tag+'/right-action',page.locator('main a[href="'+route('intake_change',7,'pause' if key=='manager_open' else 'resume')+'"]').count()==1)
                    check(tag+'/no-empty-slot-maintenance',page.locator('main a[href*="/change/"]').count()==0)
                if key in ('manager_readonly','manager_inactive','manager_ended'):
                    check(tag+'/no-intake-action',page.locator('main a[href*="/intake/"]').count()==0)
                if key.startswith('confirm_'):
                    check(tag+'/not-yet-saved','尚未保存' in text)
                    check(tag+'/promises-preserved','已有预约与有效邀约保留' in text)
                    check(tag+'/no-notification-claim','不会自动通知患者' in text)
                    if key!='confirm_readonly':
                        check(tag+'/explicit-confirm',page.locator('main input[type="checkbox"][required]').count()==1 and not page.locator('main input[type="checkbox"]').is_checked())
                        check(tag+'/two-tokens',page.locator('main [name="workspace_token"]').count()==1 and page.locator('main [name="csrfmiddlewaretoken"]').count()==1)
                    else:check(tag+'/no-form',page.locator('main form').count()==0)
                if key.startswith('front_'):
                    check(tag+'/no-manager-action',page.locator('main a[href*="/intake/"]').count()==0)
                    check(tag+'/query-only',page.locator('main form[method="post"]').count()==0)
                    check(tag+'/saved-state','主管已暂停' in text if key=='front_paused' else '当前仍接收' in text)
            if width in (390,1440) and key in ('manager_open','manager_paused','confirm_pause','confirm_resume','front_paused'):
                page.evaluate('document.documentElement.dataset.display="standard"')
                page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
result=dict(scope='Converted actual templates with synthetic fixtures; NOT Django/HTTP/PG/E2E.',total=len(checks),passed=sum(c['passed'] for c in checks),checks=checks)
(OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2))
for x in checks:
    if not x['passed']:print('FAILED',x['name'])
raise SystemExit(0 if result['passed']==result['total'] else 1)
