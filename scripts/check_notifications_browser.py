"""Static template fixtures. Not real Django rendering, HTTP, database or E2E."""
from pathlib import Path
from types import SimpleNamespace as NS
import ast,json,os,re,shlex,sys
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adc_core.route_manifest import named_routes
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a10/browser')));OUT.mkdir(parents=True,exist_ok=True)
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
base=dict(user=NS(is_authenticated=True,username='front_fixture'),workspace_label='前台',workspace_role='FRONT_DESK',workspace_scope='合成诊所A',workspace_home=route('frontdesk_home'),workspace_nav=[],workspace_can_switch_role=True,workspace_has_clinics=True,workspace_token_value='fixture',messages=[],build_version='0.9.0-alpha.10 · STATIC FIXTURE')

row=dict(id=11,task_id=3,slot_id=7,title='有新的出诊协调任务',event_state='待前台受理',current_state='前台协调中',event_revision=0,current_revision=1,occurred_at='2031年01月01日 09:00',delivered_at='2031年01月01日 09:05',read_at='',read=False)
result=dict(rows=[row],total=1,unread=1,mode='unread',number=1,pages=1,observed_at='2031年01月01日 10:00',boundary='通知不等于已受理、患者同意或业务完成；打开任务重新核对当前事实。')
status_row=dict(id=5,task_id=3,slot_id=7,title='协调任务等待独立复核',status='派发失败，待处理',occurred_at=row['occurred_at'],completed_at=row['delivered_at'],next_attempt_at='',attempts=5,retry_round=0,delivered=0,suppressed=0,error='消息写入失败，未记录原始异常内容',can_retry=True)
status=dict(rows=[status_row],total=1,counts={},number=1,pages=1,pending=0,failed=1,no_recipients=0,oldest='',observed_at=result['observed_at'])
manager=base|dict(workspace_role='MANAGER',workspace_label='诊所主管',user=NS(is_authenticated=True,username='manager_fixture'))
nav_tree=ast.parse((ROOT/'adc_core/context.py').read_text())
nav=ast.literal_eval(next(n.value for n in nav_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NAV' for t in n.targets)))
for context,role in ((base,'FRONT_DESK'),(manager,'MANAGER')):
    context['workspace_nav']=[dict(url=route(name),label=label,active=name=='notification_inbox') for name,label in nav[role]]
scenes={
 'unread':('inbox.html',dict(result=result,read_only=False),base),
 'empty':('inbox.html',dict(result=result|dict(rows=[],total=0,unread=0),read_only=False),base),
 'historical':('inbox.html',dict(result=result|dict(rows=[row|dict(read=True,read_at='2031年01月01日 09:10',current_state='任务已撤销')],mode='all'),read_only=False),base),
 'readonly_inbox':('inbox.html',dict(result=result,read_only=True),base),
 'manager_inbox':('inbox.html',dict(result=result|dict(rows=[row|dict(title='协调任务等待独立复核',event_state='待主管复核')]),read_only=False),manager),
 'failed':('status.html',dict(result=status,read_only=False),manager),
 'pending':('status.html',dict(result=status|dict(rows=[status_row|dict(status='等待后台派发',attempts=1,completed_at='',next_attempt_at='2031年01月01日 09:06',can_retry=False)],pending=1,failed=0,oldest='2031年01月01日 08:00'),read_only=False),manager),
 'no_recipients':('status.html',dict(result=status|dict(rows=[status_row|dict(status='没有符合条件的收件人',attempts=1,error='没有原始收件授权或当前授权已失效',can_retry=False)],failed=0,no_recipients=1),read_only=False),manager),
 'delivered':('status.html',dict(result=status|dict(rows=[status_row|dict(status='已生成站内消息',attempts=1,error='',can_retry=False,delivered=2)],failed=0),read_only=False),manager),
 'readonly_status':('status.html',dict(result=status,read_only=True),manager),
 'empty_status':('status.html',dict(result=status|dict(rows=[],total=0,failed=0),read_only=False),manager),
 'unknown':('recovery.html',dict(problem='消息查询不可用；不代表原任务没有保存。'),base),
 'escape':('inbox.html',dict(result=result|dict(rows=[row|dict(title='<img src=x onerror="window.noticeInjected=1">')]),read_only=False),base),
}
checks=[]
def check(k,b):checks.append(dict(name=k,passed=bool(b)))
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,fixture,b) in scenes.items():
        html=env.get_template('notifications/'+template).render(**(b|fixture))
        html=html.replace('<main id="main" tabindex="-1">','<main id="main" tabindex="-1"><p class="muted">STATIC FIXTURE · 合成页面检查，非真实服务端运行</p>')
        html=re.sub(r'<link[^>]*>','',html);html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
        for width in (320,390,1440):
            page=browser.new_page(viewport=dict(width=width,height=1050));page.set_content(html)
            for css in ('app.css','experience.css','management.css','workspace.css','notifications.css'):
                page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for large in (False,True):
                page.evaluate('(v)=>document.documentElement.dataset.display=v?"comfortable":"standard"',large)
                tag=f'{key}/{width}/{large}';body=page.locator('main').inner_text()
                check(tag+'/fits',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/h1',page.locator('main h1').count()==1)
                check(tag+'/escaped',not page.evaluate('Boolean(window.noticeInjected)'))
                check(tag+'/no-automatic-actions',page.locator('main [onclick],main [onload],main script').count()==0)
                check(tag+'/no-external-links',all(a.startswith('/') or a.startswith('#') for a in page.locator('main a').evaluate_all('(a)=>a.map(x=>x.getAttribute("href"))')))
                check(tag+'/task-recovery',page.locator('main a[href="/coordination/tasks/"]').count()>0)
                if template=='inbox.html':
                    check(tag+'/not-consent','通知不等于' in body)
                    check(tag+'/no-auto-read','不会自动标记已读' in body)
                    if fixture['result']['rows']:
                        check(tag+'/history-vs-current','事件发生时' in body and '当前查询到的任务状态' in body)
                        check(tag+'/real-task-link',page.locator('main a[href="/coordination/tasks/slots/7/3/"]').count()==1)
                if key in ('readonly_inbox','readonly_status','historical','empty','pending','delivered','no_recipients','unknown'):
                    check(tag+'/no-post-action',page.locator('main form[method="post"]').count()==0)
                for form in page.locator('main form[method="post"]').all():
                    check(tag+'/csrf-context',form.locator('[name="csrfmiddlewaretoken"]').count()==1 and form.locator('[name="workspace_token"]').count()==1)
                if key=='failed':
                    box=page.locator('main input[type="checkbox"][required]')
                    check(tag+'/retry-confirm',box.count()==1 and not box.is_checked())
                    check(tag+'/retry-not-business','不重复办理任务或预约' in body)
                if template=='status.html':
                    check(tag+'/not-health-proof','不能证明进程健康' in body)
                    check(tag+'/no-patient-data','患者姓名' not in body and '电话号码' not in body)
            if key in ('unread','failed','readonly_inbox','unknown') and width in (390,1440):
                page.evaluate('document.documentElement.dataset.display="standard"');page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
report=dict(scope='Synthetic fixtures from converted source templates; not real Django/HTTP/PG.',total=len(checks),passed=sum(x['passed'] for x in checks),checks=checks)
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
for x in checks:
    if not x['passed']:print('FAILED',x['name'])
raise SystemExit(0 if report['passed']==report['total'] else 1)
