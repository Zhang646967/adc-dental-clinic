"""Visual/source-template smoke checks with synthetic fields, not Django E2E.
No actual HTTP POST, business record, or remote AI is invoked.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import html
import json
import os
import re
import shlex
import sys
from jinja2 import Environment, DictLoader, ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from adc_core.route_manifest import named_routes
from patients.contact_rules import CONTACT_LABELS, ContactDifference
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a3/contacts_regression')));OUT.mkdir(parents=True,exist_ok=True)
paths=named_routes(ROOT)
def route(name,*args):
    args=iter(args)
    return re.sub(r'<(?:[^:>]+:)?[^>]+>',lambda _:str(next(args)),paths[name])
def convert(s):
    s=re.sub(r'{% load [^%]+%}','',s).replace('{% empty %}','{% else %}')
    s=s.replace('{% csrf_token %}','<input type="hidden" name="csrfmiddlewaretoken" value="fixture">')
    s=s.replace('{% workspace_token %}','<input type="hidden" name="workspace_token" value="fixture">')
    def url(m):
        b=shlex.split(m[1]);return '{{ route('+repr(b[0])+(','+','.join(b[1:]) if len(b)>1 else '')+') }}'
    s=re.sub(r'{% url (.*?) %}',url,s)
    s=re.sub(r"{% static '([^']+)' %}",r"{{ asset('\1') }}",s)
    s=re.sub(r"\|default:'([^']+)'",r"|default('\1',true)",s)
    s=re.sub(r'\|default:"([^"]+)"',r"|default('\1',true)",s)
    return s.replace('forloop.counter','loop.index')
env=Environment(loader=DictLoader({str(f.relative_to(ROOT/'templates')):convert(f.read_text())
    for f in (ROOT/'templates').rglob('*.html')}),autoescape=True,undefined=ChainableUndefined)
env.globals.update(route=route,asset=lambda n:'/static/'+n)
base=dict(user=NS(is_authenticated=True,username='front_synthetic'),workspace_label='前台',workspace_scope='合成诊所A',
          workspace_role='FRONT_DESK',workspace_home='/workspace/frontdesk/',workspace_nav=[],workspace_can_switch_role=False,
          workspace_has_clinics=True,workspace_token_value='fixture',messages=[],build_version='0.9a3 STATIC FIXTURE',
          patient=NS(pk=7,name='合成患者（页面测试）',patient_no='P-SYNTHETIC-NOT-A-LIVE-PATIENT'))
fields=['<input type="hidden" name="state_token" value="fixture-state">']
for name,label in CONTACT_LABELS.items():
    fields.append(f'<p><label for="id_{name}">{label}</label><input id="id_{name}" name="{name}" value="合成占位"'+(' required' if name!='email' else '')+'></p>')
fields.append('<p><label for="id_reason_code">更正依据</label><select id="id_reason_code" name="reason_code" required><option value="">请选择</option><option value="PATIENT_UPDATE">患者提供新的联络资料</option></select></p>')
edit_form=NS(errors=False,as_p=Markup(''.join(fields)))
confirm_form=NS(as_p=Markup('<input type="hidden" name="proposal_token" value="fixture-proposal"><p><label><input type="checkbox" name="confirmed" required>我已与患者核对差异，确认只更正上述联络资料</label></p>'))
rows=(ContactDifference('phone','联系电话','000-1111','000-2222'),
      ContactDifference('billing_address','账单地址','旧虚构地址','新的虚构课程测试地址'*12),
      ContactDifference('email','邮箱','old@example.invalid',''),
      ContactDifference('emergency_name','紧急联系人','旧合成联系人','<script>window.testInjected=true</script>'))
scenarios={
 'edit':('patients/contact_edit.html',{'form':edit_form,'read_only':False}),
 'readonly':('patients/contact_edit.html',{'form':edit_form,'read_only':True}),
 'preview':('patients/contact_confirm.html',{'form':confirm_form,'rows':rows,'reason_label':'患者提供新的联络资料'}),
 'recovery':('patients/contact_recovery.html',{'problem':'联络资料已经变化，请核对当前资料；此前成功操作不会撤销。'}),
}
checks=[]
def check(name,ok):checks.append({'name':name,'passed':bool(ok)})
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,data) in scenarios.items():
        rendered=env.get_template(template).render(**(base|data))
        rendered=re.sub(r'<link[^>]*>','',rendered)
        rendered=re.sub(r'<script[^>]+src=[^>]*></script>','',rendered)
        for width in (320,390,1440):
            page=browser.new_page(viewport={'width':width,'height':1000});page.set_content(rendered)
            for css in ('app.css','experience.css','management.css','workspace.css'):
                page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for comfortable in (False,True):
                page.evaluate('(v)=>document.documentElement.dataset.display=v?"comfortable":"standard"',comfortable)
                tag=f'{key}/{width}/{comfortable}'
                check(tag+'/no-horizontal-overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/one-heading',page.locator('h1').count()==1)
                check(tag+'/no-injected-script',not page.evaluate('Boolean(window.testInjected)'))
                check(tag+'/form-context',page.locator('main form input[name="workspace_token"]').count()==(0 if key=='recovery' else 1))
                if key=='preview':
                    check(tag+'/manual-confirm-required',page.locator('main input[name="confirmed"][required]').count()==1)
                    check(tag+'/correct-target',page.locator('main form').get_attribute('action')=='/patients/7/contact/confirm/')
                if key=='readonly':check(tag+'/write-disabled',page.locator('main button[type="submit"]').is_disabled())
                if key=='recovery':check(tag+'/safe-recovery',page.locator('main a[href="/patients/7/"]').count()==1)
            if width in (390,1440):
                page.evaluate('document.documentElement.dataset.display="standard"')
                page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
result={'scope':'Source-template Chromium checks with synthetic fields; no Django, database, real form validation or network AI',
        'total':len(checks),'passed':sum(x['passed'] for x in checks),'checks':checks}
(OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2))
for x in checks:
    if not x['passed']:print('FAILED',x['name'])
raise SystemExit(0 if result['total']==result['passed'] else 1)
