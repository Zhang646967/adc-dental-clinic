"""Real Chromium + source templates/JS, synthetic form fields; NOT server-side E2E."""
import sys,json,re,shlex,os
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace as NS
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from adc_core.route_manifest import named_routes
from coordination.windows import window_bounds
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(R/'docs/evidence_v09a3/interaction_regression')));OUT.mkdir(parents=True,exist_ok=True)
paths=named_routes(R)
def route(name,*args,**kwargs):
    it=iter(args)
    return re.sub(r'<(?:[^:>]+:)?([^>]+)>',lambda m:str(kwargs[m[1]] if m[1] in kwargs else next(it)),paths[name])
def convert(s):
    s=re.sub(r'{% load [^%]+%}','',s).replace('{% empty %}','{% else %}')
    s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="fixture">').replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture-context">')
    def url(m):
        b=shlex.split(m[1]);return '{{ route('+repr(b[0])+(','+','.join(b[1:]) if len(b)>1 else '')+') }}'
    s=re.sub(r'{% url (.*?) %}',url,s)
    s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
    for f in ('date','join','json_script'):
        s=re.sub(r'\|'+f+r":'([^']+)'",r'|'+f+r"('\1')",s)
    s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
    return s.replace('forloop.counter','loop.index')
sources={str(f.relative_to(R/'templates')):convert(f.read_text()) for f in (R/'templates').rglob('*.html')}
env=Environment(loader=DictLoader(sources),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda n:'/static/'+n)
env.filters['json_script']=lambda x,i:Markup('<script type="application/json" id="'+i+'">'+json.dumps(x).replace('<','\\u003c')+'</script>')
env.filters['date']=lambda x,f:x.strftime('%Y-%m-%d %H:%M') if hasattr(x,'strftime') else str(x)
base=dict(user=NS(is_authenticated=True,username='patient_demo_a'),workspace_label='患者',workspace_scope='本人资料',workspace_role='PATIENT',workspace_home='/portal/',workspace_nav=[],workspace_can_switch_role=False,workspace_has_clinics=False,workspace_token_value='fixture',workspace_revision=1,build_version='0.9.0-alpha.3 STATIC FIXTURE',messages=[],base_template='portal/base.html')
now=datetime(2026,9,27,7,20,31,tzinfo=timezone.utc)
fields=Markup('''<label for="id_clinic">希望就诊的诊所</label><select id="id_clinic" name="clinic"><option value="1">演示诊所1</option></select><label for="id_preferred_dentist">希望的牙医</label><select id="id_preferred_dentist" name="preferred_dentist"><option value="">不限</option></select><label for="id_earliest">最早可开始就诊（北京时间）</label><input id="id_earliest" type="datetime-local" name="earliest" required><label for="id_latest">最晚必须结束就诊（北京时间）</label><input id="id_latest" type="datetime-local" name="latest" required><label><input type="checkbox" name="confirmed" required>已核对偏好；不是正式预约</label>''')
ctx=base|dict(title='登记候补偏好',description='选择未来14天内的时间范围。结束至少晚30分钟。',button='确认登记候补',form=NS(as_div=fields),window_limits=window_bounds(now).as_dict())
html=env.get_template('coordination/form.html').render(**ctx)
html=re.sub(r'<link[^>]*>','',html)
html=re.sub(r'<script[^>]+src=[^>]*></script>','',html)
html=html.replace('<body class="patient-body">','<body class="patient-body"><p class="notice">STATIC FIXTURE · 真实模板与JS，固定表单数据；不是Django端到端。</p>')
(OUT/'wait_form.fixture.html').write_text(html)
results=[]
def check(name,ok,detail=None):
    results.append({'name':name,'passed':bool(ok),'detail':detail})
    if not ok:print('FAIL',name,detail)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for zone in ('Asia/Shanghai','America/Chicago'):
      for width in (1440,390,320):
        context=browser.new_context(viewport={'width':width,'height':900},timezone_id=zone)
        page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.set_content(html)
        for css in ('experience.css','workspace.css'):page.add_style_tag(content=(R/'static'/css).read_text())
        page.evaluate("""() => {window._store={};Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:k=>window._store[k]||null,setItem:(k,v)=>window._store[k]=String(v)}}); window.submits=0;document.querySelector('form[data-wait-window]').addEventListener('submit',e=>{window.submits++;e.preventDefault();});}""")
        page.add_script_tag(content=(R/'static/experience.js').read_text());page.add_script_tag(content=(R/'static/wait-window.js').read_text())
        tag=f'{zone}/{width}'
        check(tag+'/enhanced',page.locator('form[data-wait-window]').get_attribute('data-window-enhanced')=='true')
        check(tag+'/end-disabled-until-start',page.locator('#id_latest').is_disabled() and page.locator('#id_latest_time').is_disabled())
        check(tag+'/submit-disabled-empty',page.locator('form[data-wait-window] button[type=submit]').is_disabled())
        values=page.locator('#id_earliest option').evaluate_all('(es)=>es.map(x=>x.value)')
        check(tag+'/no-past-day','2026-09-26' not in values and '2026-09-27' in values)
        page.locator('#id_earliest').select_option('2026-09-27');vals=page.locator('#id_earliest_time option').evaluate_all('(es)=>es.map(x=>x.value)')
        check(tag+'/server-beijing-not-browser-zone','15:30' in vals and '15:15' not in vals)
        page.locator('#id_earliest').select_option('2026-09-28');page.locator('#id_earliest_time').select_option('14:00')
        page.locator('#id_latest').select_option('2026-09-28');vals=page.locator('#id_latest_time option').evaluate_all('(es)=>es.map(x=>x.value)')
        check(tag+'/end-before-plus30-not-listed','14:15' not in vals and '13:00' not in vals and '14:30' in vals)
        page.locator('#id_latest_time').select_option('15:00')
        check(tag+'/valid-serialization',page.locator('[name=earliest]').input_value()=='2026-09-28T14:00' and page.locator('[name=latest]').input_value()=='2026-09-28T15:00')
        check(tag+'/no-auto-submit',page.evaluate('window.submits')==0)
        page.locator('#id_earliest_time').select_option('15:00')
        check(tag+'/changing-start-clears-invalid-end',page.locator('[name=latest]').input_value()=='' and page.locator('form[data-wait-window] button[type=submit]').is_disabled())
        check(tag+'/clearing-is-explained','清空' in page.locator('[data-window-feedback]').inner_text())
        page.locator('#id_latest_time').select_option('16:00')
        check(tag+'/valid-enables-submit',not page.locator('form[data-wait-window] button[type=submit]').is_disabled())
        page.locator('#id_earliest').select_option('2026-10-11');vals=page.locator('#id_earliest_time option').evaluate_all('(es)=>es.map(x=>x.value)')
        check(tag+'/start-needs-end-room','15:00' not in vals and '14:45' in vals)
        page.locator('#id_earliest_time').select_option('14:45');page.locator('#id_latest').select_option('2026-10-11');vals=page.locator('#id_latest_time option').evaluate_all('(es)=>es.map(x=>x.value)')
        check(tag+'/rolling-last-date-boundary','15:15' in vals and '15:30' not in vals)
        for mode in ('standard','comfortable'):
            if mode=='comfortable':page.locator('.mode-toggle').click()
            sizes=page.evaluate("""()=>({scroll:document.documentElement.scrollWidth,width:innerWidth,h:[...document.querySelectorAll('.wait-controls select')].map(e=>e.getBoundingClientRect().height)})""")
            check(tag+'/'+mode+'/no-overflow',sizes['scroll']<=width+1,sizes)
            check(tag+'/'+mode+'/targets',min(sizes['h'])>=48,sizes['h'])
        page.locator('#id_earliest').focus();page.keyboard.press('Tab')
        check(tag+'/keyboard-order',page.locator('#id_earliest_time').evaluate('(e)=>e===document.activeElement'))
        check(tag+'/no-js-errors',not errors,errors)
        if zone=='Asia/Shanghai' and width in (1440,390):page.screenshot(path=str(OUT/f'wait_{width}_large.png'),full_page=True)
        page.close();context.close()
    # Account management screen: render real templates with synthetic state and no secret fields.
    tech=base|dict(base_template='base.html',workspace_label='技术管理',workspace_role='SYSADMIN',workspace_scope='账号与技术配置',workspace_can_switch_role=False,user=NS(is_authenticated=True,username='tech_demo'),target=NS(pk=11,username='new_demo',is_active=True),protected=False,roles=['诊所主管'],actions=[('grant','授予身份'),('reset_password','重置密码'),('disable','常规业务停用'),('security_suspend','紧急安全封禁')])
    doc=env.get_template('accounts/manage_detail.html').render(**tech)
    doc=re.sub(r'<link[^>]*>','',doc);doc=re.sub(r'<script[^>]+src=[^>]*></script>','',doc)
    for width in (1440,390,320):
        page=browser.new_page(viewport={'width':width,'height':900});page.set_content(doc)
        for css in ('app.css','experience.css','management.css','workspace.css'):page.add_style_tag(content=(R/'static'/css).read_text())
        size=page.evaluate('({scroll:document.documentElement.scrollWidth,width:innerWidth})')
        check(f'accounts/{width}/layout',size['scroll']<=width+1,size)
        check(f'accounts/{width}/self-password-route',page.locator('a[href="/accounts/password/"]').count()==1)
        check(f'accounts/{width}/technical-actions',page.locator('a[href="/technical/accounts/11/reset_password/"]').count()==1)
        check(f'accounts/{width}/security-action',page.locator('a[href="/technical/accounts/11/security_suspend/"]').count()==1)
        check(f'accounts/{width}/separate-meaning','安全' in page.locator('main').inner_text() and '预约' in page.locator('main').inner_text())
        if width==1440:page.screenshot(path=str(OUT/'account_detail_1440.png'),full_page=True)
        page.close()
    browser.close()
report={'scope':'Chromium source-template fixtures with fixed form fields; no Django/DB, no remote AI', 'passed':sum(r['passed'] for r in results),'total':len(results),'checks':results}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='checks'},ensure_ascii=False))
sys.exit(0 if report['passed']==report['total'] else 1)
