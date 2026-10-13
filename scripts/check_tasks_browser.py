"""Static template fixtures. Not real Django rendering, HTTP, database or E2E."""
from pathlib import Path
from types import SimpleNamespace as NS
import json,os,re,shlex,sys
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adc_core.route_manifest import named_routes
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a9/browser')));OUT.mkdir(parents=True,exist_ok=True)
paths=named_routes(ROOT)
def route(name,*args):
    args=iter(args);return re.sub(r'<(?:[^:>]+:)?[^>]+>',lambda _:str(next(args)),paths[name])
def convert(s):
    s=re.sub(r'{% load [^%]+%}','',s).replace('{% empty %}','{% else %}')
    s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="fixture-csrf">')
    s=s.replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture-context">')
    def url(m):
        t=shlex.split(m[1],posix=False);return '{{ route('+t[0]+(','+','.join(t[1:]) if len(t)>1 else '')+') }}'
    s=re.sub(r'{% url (.*?) %}',url,s)
    s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
    s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
    s=re.sub(r'\|default:"([^"]+)"',r"|default('\1',true)",s)
    return s.replace('forloop.counter','loop.index')
env=Environment(loader=DictLoader({str(f.relative_to(ROOT/'templates')):convert(f.read_text()) for f in (ROOT/'templates').rglob('*.html')}),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda x:'/static/'+x)
base=dict(user=NS(is_authenticated=True,username='front_fixture'),workspace_label='前台',workspace_role='FRONT_DESK',workspace_scope='合成诊所A',workspace_home=route('frontdesk_home'),workspace_nav=[],workspace_can_switch_role=True,workspace_has_clinics=True,workspace_token_value='fixture',messages=[],build_version='0.9.0-alpha.9 · STATIC FIXTURE')
impact=NS(visit_count=3,blocking_visits=2,offer_count=1,effective_offers=1,expired_pending=0)
gate=NS(clear=False,reasons=('仍有受保护预约或接诊记录；不能以声明代替处理。','仍有有效邀约；暂停新增保留原承诺。'))
history=[dict(action='记录办理声明',actor='front_fixture',at='2031年01月01日 10:00',reason='已尝试联络，尚未得到回复（本人声明）',target='预约 #11',statement=True),dict(action='受理任务',actor='front_fixture',at='2031年01月01日 09:50',reason='本人承担跟进责任',statement=False)]
data=dict(slot_id=7,clinic='合成诊所A',dentist='合成牙医一',start='2031年01月02日 09:00',end='2031年01月02日 13:00',paused=True,active=True,task_id=3,status='前台协调中',purpose='为调整原出诊协调',assignee='front_fixture',creator='manager_fixture',observed_at='2031年01月01日 10:05',impact=impact,gate=gate,actions=[dict(key='progress',label='记录办理声明'),dict(key='release',label='退回待受理队列')],blocked=[dict(action='提交主管复核',reason='仍有有效承诺')],history=history,history_total=2,terminal=False,role='FRONT_DESK')
confirm_html='<input type="hidden" name="proposal_token" value="fixture"><p><label for="confirmed"><input id="confirmed" name="confirmed" type="checkbox" required>我已核对目标及影响，不代替患者决定，也不自动维护出诊。</label></p>'
edit_html='<input type="hidden" name="state_token" value="fixture"><p><label for="reason">本次依据</label><select name="reason" id="reason" required><option value="">请选择</option><option value="NEED_HELP">需要主管协助（本人声明）</option></select></p>'
preview=dict(data)|dict(action='claim',action_label='受理任务',after='前台协调中',reason='本人受理并承担责任',proposal_token='fixture')
rows=[dict(id=3,slot_id=7,status='待前台受理',purpose='为调整原出诊协调',dentist='合成牙医一',start=data['start'],end=data['end'],assignee='尚未受理',paused=True,slot_active=True)]
result=dict(rows=rows,total=1,number=1,pages=1,mode='active',slot_filter='',role='FRONT_DESK',observed_at=data['observed_at'])
manager=base|dict(workspace_role='MANAGER',workspace_label='诊所主管',user=NS(is_authenticated=True,username='manager_fixture'))
manager_data=data|dict(role='MANAGER',actions=[dict(key='return',label='退回重新受理'),dict(key='cancel',label='撤销协调任务')],history=[{k:v for k,v in h.items() if k!='target'} for h in history])
scenes={
 'queue':('list.html',dict(result=result),base),
 'empty_queue':('list.html',dict(result=result|dict(rows=[],total=0)),base),
 'manager_queue':('list.html',dict(result=result|dict(role='MANAGER')),manager),
 'front_working':('detail.html',dict(data=data,read_only=False),base),
 'manager_blocked':('detail.html',dict(data=manager_data,read_only=False),manager),
 'front_claim':('detail.html',dict(data=data|dict(status='待前台受理',actions=[dict(key='claim',label='受理任务')],history=[],history_total=0),read_only=False),base),
 'ready_review':('detail.html',dict(data=manager_data|dict(status='待主管复核',gate=NS(clear=True,reasons=()),impact=NS(blocking_visits=0,effective_offers=0,expired_pending=1),actions=[dict(key='approve',label='确认协调核对通过')]),read_only=False),manager),
 'closed':('detail.html',dict(data=manager_data|dict(status='协调核对已通过',terminal=True,actions=[],gate=NS(clear=True,reasons=())),read_only=False),manager),
 'readonly':('detail.html',dict(data=data,read_only=True),base),
 'resumed':('detail.html',dict(data=manager_data|dict(paused=False,gate=NS(clear=False,reasons=('已恢复接收，需要重新核对，不能直接结案。',))),read_only=False),manager),
 'progress_edit':('change.html',dict(data=data,action='progress',action_label='记录办理声明',form=NS(as_p=Markup(edit_html)),read_only=False),base),
 'open_confirm':('confirm.html',dict(preview=preview|dict(task_id=None,status='尚未发起',action='open',action_label='发起协调任务',reason='已核对的出诊计划变化',after='待前台受理'),form=NS(as_p=Markup(confirm_html)),read_only=False),manager),
 'approve_confirm':('confirm.html',dict(preview=preview|dict(action='approve',status='待主管复核',action_label='确认协调核对通过',reason='已独立核对当前事实与维护条件',after='协调核对已通过'),form=NS(as_p=Markup(confirm_html)),read_only=False),manager),
 'progress_confirm':('confirm.html',dict(preview=preview|dict(action='progress',action_label='记录办理声明',reason=history[0]['reason'],target_label='预约 #11'),form=NS(as_p=Markup(confirm_html)),read_only=False),base),
 'cancel_confirm':('confirm.html',dict(preview=preview|dict(action='cancel',action_label='撤销协调任务',reason='原协调计划已撤回',after='任务已撤销'),form=NS(as_p=Markup(confirm_html)),read_only=False),manager),
 'readonly_confirm':('confirm.html',dict(preview=preview,form=NS(as_p=Markup(confirm_html)),read_only=True),base),
 'unknown':('recovery.html',dict(slot_id=7,task_id=3,problem='本次结果未知。先查询原任务；不自动重发。'),base),
 'escape':('detail.html',dict(data=data|dict(dentist='<img src=x onerror="window.taskInjected=1">'),read_only=False),base),
}
checks=[]
def check(k,b):checks.append(dict(name=k,passed=bool(b)))
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,fixture,b) in scenes.items():
        html=env.get_template('coordination/tasks/'+template).render(**(b|fixture))
        html=html.replace('<main id="main" tabindex="-1">','<main id="main" tabindex="-1"><p class="muted">STATIC FIXTURE · 合成页面检查，非真实服务端运行</p>')
        html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
        for width in (320,390,1440):
            page=browser.new_page(viewport=dict(width=width,height=1050));page.set_content(html)
            for css in ('app.css','experience.css','management.css','workspace.css','availability.css','coordination_tasks.css'):
                page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for large in (False,True):
                page.evaluate('(v)=>document.documentElement.dataset.display=v?"comfortable":"standard"',large)
                tag=f'{key}/{width}/{large}';body=page.locator('main').inner_text()
                check(tag+'/fits',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/h1',page.locator('main h1').count()==1)
                check(tag+'/safe-text',not page.evaluate('Boolean(window.taskInjected)'))
                check(tag+'/no-automatic-actions',page.locator('main [onclick],main [onload],main script').count()==0)
                check(tag+'/internal-links',all(a.startswith('/') or a.startswith('#') for a in page.locator('main a').evaluate_all('(a)=>a.map(x=>x.getAttribute("href"))')))
                if template in ('list.html','detail.html'):
                    check(tag+'/query-not-post',page.locator('main form[method="post"]').count()==0)
                if template=='detail.html':
                    check(tag+'/statements-not-consent','不证明患者已同意' in body)
                    check(tag+'/fact-state-separate','任务状态不是当前预约状态' in body)
                    if b['workspace_role']=='MANAGER':
                        check(tag+'/no-patient-reference','预约 #11' not in body)
                        check(tag+'/no-front-deep-link',page.locator('main a[href*="/front/coordination/"]').count()==0)
                if key in ('readonly','readonly_confirm'):
                    check(tag+'/no-write',page.locator('main form[method="post"]').count()==0 and page.locator('main a[href*="/act/"]').count()==0)
                if template=='confirm.html':
                    check(tag+'/not-saved','尚未保存' in body)
                    check(tag+'/no-clinical-sideeffects','不取消或改期任何预约' in body)
                    if key!='readonly_confirm':
                        check(tag+'/explicit-confirm',page.locator('main input[type="checkbox"][required]').count()==1 and not page.locator('main input[type="checkbox"]').is_checked())
                        check(tag+'/tokens',page.locator('main [name="workspace_token"]').count()==1 and page.locator('main [name="csrfmiddlewaretoken"]').count()==1)
                if key=='cancel_confirm':check(tag+'/pause-preserved','任务撤销不恢复接收' in body)
                if key=='approve_confirm':check(tag+'/no-maintenance-claim','原出诊尚未因此停用或替换' in body)
                if key=='unknown':check(tag+'/unknown-not-failure','查询失败不等于先前办理失败' in body)
            if key in ('front_working','manager_blocked','approve_confirm','cancel_confirm') and width in (390,1440):
                page.evaluate('document.documentElement.dataset.display="standard"');page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
report=dict(scope='Synthetic fixtures from converted source templates; not real Django/HTTP/PG.',total=len(checks),passed=sum(x['passed'] for x in checks),checks=checks)
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
for x in checks:
    if not x['passed']:print('FAILED',x['name'])
raise SystemExit(0 if report['passed']==report['total'] else 1)
