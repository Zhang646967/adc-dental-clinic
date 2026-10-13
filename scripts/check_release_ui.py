"""Current base templates + real release JS; synthetic static DOM, not Django E2E."""
from pathlib import Path
import ast,json,re,shlex,sys
from types import SimpleNamespace as NS
from jinja2 import Environment,DictLoader,ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from adc_core.route_manifest import named_routes
OUT=R/'docs/evidence_rc1/ui';OUT.mkdir(parents=True,exist_ok=True)
paths=named_routes(R)
def route(name,*args,**kwargs):
    it=iter(args or kwargs.values());return re.sub(r'<(?:[^:>]+:)?[^>]+>',lambda _:str(next(it)),paths[name])
def convert(s):
    s=re.sub(r'{% load [^%]+%}','',s).replace('{% empty %}','{% else %}')
    s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="fixture">')
    s=s.replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture">')
    s=re.sub(r"{% static '([^']+)' %}",r"/static/\1",s)
    def url(m):
        t=shlex.split(m[1],posix=False);return '{{ route('+t[0]+(','+','.join(t[1:]) if len(t)>1 else '')+') }}'
    s=re.sub(r'{% url (.*?) %}',url,s)
    s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
    return s.replace('forloop.counter','loop.index')
templates={str(f.relative_to(R/'templates')):convert(f.read_text()) for f in (R/'templates').rglob('*.html')}
body='''{% extends BASE %}{% block content %}<p>STATIC FIXTURE · 非数据库运行证据</p><h1>输入核对与下一步</h1><form method="post"><input type="hidden" name="csrfmiddlewaretoken" value="fixture"><input type="hidden" name="workspace_token" value="fixture"><div class="field"><label for="id_phone">联系电话：</label><input id="id_phone" name="phone" value="" aria-describedby="phone_help"><small id="phone_help">仅输入合成联络资料。</small><ul class="errorlist"><li>请填写联系电话。</li></ul></div><div class="field"><label for="id_end">最晚结束时间：</label><input id="id_end" name="end"><ul class="errorlist"><li>请重新核对时间。</li></ul></div><button type="submit">核对，尚未保存</button></form><a href="#main">返回当前任务</a>{% endblock %}'''
templates['release_fixture.html']=body
env=Environment(loader=DictLoader(templates),autoescape=True,undefined=ChainableUndefined);env.globals['route']=route
nav_ast=ast.parse((R/'adc_core/context.py').read_text());nav=ast.literal_eval(next(n.value for n in nav_ast.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NAV' for t in n.targets)))
checks=[]
def check(name,ok):checks.append({'name':name,'passed':bool(ok)})
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
    for role,items in nav.items():
      for readonly in (False,True):
       for width in (320,390,1440):
        data=dict(BASE='portal/base.html' if role=='PATIENT' else 'base.html',user=NS(is_authenticated=True,username='synthetic'),workspace_role=role,workspace_label=role,workspace_scope='合成资料 / 当前授权范围',workspace_home=route(items[0][0]),workspace_can_switch_role=True,workspace_has_clinics=role in ('MANAGER','FRONT_DESK'),workspace_nav=[{'url':route(n),'label':v,'active':i==0} for i,(n,v) in enumerate(items)],workspace_token_value='fixture',build_version='1.0.0-rc.1 STATIC FIXTURE',adc_read_only=readonly,messages=[])
        html=env.get_template('release_fixture.html').render(**data)
        html=re.sub(r'<link[^>]*>|<script[^>]+src=[^>]*></script>','',html)
        page=browser.new_page(viewport={'width':width,'height':1000});page.set_content(html)
        css=['experience.css','workspace.css','release-ui.css'] if role=='PATIENT' else ['app.css','experience.css','management.css','workspace.css','release-ui.css']
        for c in css:page.add_style_tag(content=(R/'static'/c).read_text())
        page.evaluate('window.submits=0;document.querySelector("main form").addEventListener("submit",e=>{e.preventDefault();window.submits++})')
        page.add_script_tag(content=(R/'static/release-ui.js').read_text());page.add_script_tag(content=(R/'static/experience.js').read_text())
        for large in (False,True):
          page.evaluate('(v)=>document.documentElement.dataset.display=v?"comfortable":"standard"',large)
          tag=f'{role}/{readonly}/{width}/{large}'
          check(tag+'/viewport',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
          check(tag+'/help-label',page.locator('nav').get_by_text('逐步操作指南',exact=True).count()==1)
          check(tag+'/read-only',page.locator('.rc-mode-banner').count()==int(readonly))
          check(tag+'/linked-errors',page.locator('.rc-error-summary a').count()==2)
          check(tag+'/no-auto-submit',page.evaluate('window.submits')==0)
          check(tag+'/hidden-contract',page.locator('main [name=workspace_token]').count()==1 and page.locator('main [name=csrfmiddlewaretoken]').count()==1)
          check(tag+'/description-preserved','phone_help' in page.locator('#id_phone').get_attribute('aria-describedby'))
          page.locator('.rc-error-summary a').first.click();check(tag+'/keyboard-focus',page.evaluate('document.activeElement.id')=='id_phone')
        if role in ('FRONT_DESK','PATIENT') and width==390 and readonly:
            page.screenshot(path=str(OUT/f'{role.lower()}_390.png'),full_page=True)
        page.close()
    browser.close()
report={'scope':'Actual base templates and JS on synthetic DOM, not Django/DB','total':len(checks),'passed':sum(c['passed'] for c in checks),'checks':checks}
(OUT/'results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({k:v for k,v in report.items() if k!='checks'}))
for c in checks:
 if not c['passed']:print('FAILED',c['name'])
raise SystemExit(0 if all(c['passed'] for c in checks) else 1)
