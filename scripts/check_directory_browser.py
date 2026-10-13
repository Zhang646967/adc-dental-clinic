"""Source-template UI fixtures; no Django runtime/DB, network or business submission.
Keep this scope distinct from a real end-to-end acceptance run.
"""
from pathlib import Path
from types import SimpleNamespace as NS
import html, json, os, re, shlex, sys
from jinja2 import Environment, DictLoader, ChainableUndefined
from markupsafe import Markup
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from adc_core.route_manifest import named_routes
from registry.directory_rules import DisplayRow
OUT=Path(os.environ.get('ADC_BROWSER_EVIDENCE_DIR',str(ROOT/'docs/evidence_v09a5/browser')));OUT.mkdir(parents=True,exist_ok=True)
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
base=dict(user=NS(is_authenticated=True,username='technical_synthetic'),workspace_label='技术管理',workspace_scope='基础资料与授权',
    workspace_role='SYSADMIN',workspace_home=route('technical_home'),workspace_nav=[{'url':route('directory_home'),'label':'基础资料目录','active':True}],
    workspace_can_switch_role=False,workspace_has_clinics=False,workspace_token_value='fixture',messages=[],build_version='0.9a5 STATIC FIXTURE')
edit_fields=[]
for key,label,typ in [('employee_no','牙医员工编号','text'),('name','牙医姓名','text'),('date_of_birth','出生日期','date'),
 ('home_address','联系地址','text'),('phone','联系电话','text'),('email','邮箱','email')]:
    value='1990-01-02' if typ=='date' else 'fixture@example.invalid' if typ=='email' else '合成文本'
    edit_fields.append(f'<p><label for="id_{key}">{label}</label><input type="{typ}" id="id_{key}" name="{key}" value="{value}" required></p>')
edit_fields.append('<p><label for="id_reason_code">登记依据</label><select id="id_reason_code" name="reason_code" required><option value="SOURCE_RECORD">已核对的合成资料</option></select></p>')
editform=NS(errors=False,as_p=Markup(''.join(edit_fields)))
confirmform=NS(errors=False,as_p=Markup('<input type="hidden" name="proposal_token" value="fixture-proposal"><p><label for="id_operator_password">再次输入你自己的技术管理密码</label><input id="id_operator_password" name="operator_password" type="password" autocomplete="current-password" required></p><p><label for="id_confirmed"><input id="id_confirmed" name="confirmed" type="checkbox" required>我已核对影响；不认证执业资格</label></p>'))
rows=(DisplayRow('牙医员工编号','DR_SYNTHETIC'),DisplayRow('姓名','<script>window.directoryInjected=true</script>'),
      DisplayRow('联系地址','合成超长地址，仅供换行验证。'*22),DisplayRow('邮箱','synthetic@example.invalid'))
obj=NS(pk=7,name='合成牙医',employee_no='DR_SYNTHETIC',is_active=True)
associations=[NS(is_active=True,qualification_id=2,qualification=NS(code='Q2',name='合成资格类别',is_active=True)),
              NS(is_active=False,qualification_id=3,qualification=NS(code='Q3',name='已撤回的合成资格类别',is_active=True))]
pageinfo=NS(number=1,paginator=NS(num_pages=1),has_previous=False,has_next=False)
scenarios={
 'home':('registry/directory_home.html',{'counts':[{'kind':'clinic','label':'诊所','count':2},{'kind':'dentist','label':'牙医','count':3},{'kind':'qualification','label':'资格类别','count':2}],'read_only':False}),
 'list':('registry/directory_list.html',{'kind':'dentist','label':'牙医','rows':[{'pk':7,'code':'DR_A','name':'<script>window.directoryInjected=true</script>','active':True}],'page':pageinfo,'q':'','read_only':False}),
 'empty':('registry/directory_list.html',{'kind':'dentist','label':'牙医','rows':[],'page':pageinfo,'q':'查无结果','read_only':False}),
 'detail':('registry/directory_detail.html',{'object':obj,'kind':'dentist','label':'牙医','rows':rows,'associations':associations,'read_only':False}),
 'readonly_detail':('registry/directory_detail.html',{'object':obj,'kind':'dentist','label':'牙医','rows':rows,'associations':associations,'read_only':True}),
 'edit':('registry/directory_form.html',{'form':editform,'kind':'dentist','title':'登记牙医','read_only':False}),
 'readonly_edit':('registry/directory_form.html',{'form':editform,'kind':'dentist','title':'登记牙医','read_only':True}),
 'confirm':('registry/directory_confirm.html',{'preview':NS(title='核对并登记牙医',rows=rows,reason_label='已核对的合成资料',kind='dentist'),'form':confirmform}),
 'recovery':('registry/directory_recovery.html',{'problem':'暂时无法核对保存结果，不代表此前一定没有保存。请先核对当前目录。'}),
}
checks=[]
def check(name,passed):checks.append({'name':name,'passed':bool(passed)})
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path=os.environ.get('ADC_CHROMIUM_PATH','/usr/bin/chromium'),headless=True,args=['--no-sandbox'])
    for key,(template,data) in scenarios.items():
        rendered=env.get_template(template).render(**(base|data))
        rendered=re.sub(r'<link[^>]*>','',rendered);rendered=re.sub(r'<script[^>]+src=[^>]*></script>','',rendered)
        for width in (320,390,1440):
            page=browser.new_page(viewport={'width':width,'height':1000});page.set_content(rendered)
            for css in ('app.css','experience.css','management.css','workspace.css'):page.add_style_tag(content=(ROOT/'static'/css).read_text())
            for comfortable in (False,True):
                page.evaluate('(v)=>document.documentElement.dataset.display=v?"comfortable":"standard"',comfortable)
                tag=f'{key}/{width}/{comfortable}'
                check(tag+'/no-horizontal-overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                check(tag+'/one-h1',page.locator('h1').count()==1)
                check(tag+'/escaping',not page.evaluate('Boolean(window.directoryInjected)'))
                check(tag+'/post-context',page.locator('main form[method="post"]').count()==page.locator('main form[method="post"] input[name="workspace_token"]').count())
                check(tag+'/no-external-frames',page.locator('iframe').count()==0)
                if key=='confirm':
                    check(tag+'/not-saved-disclosure','尚未保存' in page.locator('main').inner_text())
                    check(tag+'/explicit-confirm',page.locator('main input[name="confirmed"][required]').count()==1)
                    check(tag+'/password-required',page.locator('main input[type="password"][required]').count()==1)
                    check(tag+'/confirm-target',page.locator('main form').get_attribute('action')==route('directory_confirm'))
                if key=='readonly_edit':check(tag+'/write-disabled',page.locator('main button[type="submit"]').is_disabled())
                if key=='readonly_detail':check(tag+'/no-mutation-form',page.locator('main form[method="post"]').count()==0)
                if key=='detail':check(tag+'/withdraw-preview-not-confirm',page.locator('main form').get_attribute('action')==route('directory_withdraw_preview',7,2))
                if key=='recovery':check(tag+'/recovery-path',page.locator(f'main a[href="{route("directory_home")}"]').count()==1)
            if width in (390,1440):
                page.evaluate('document.documentElement.dataset.display="standard"')
                page.screenshot(path=str(OUT/f'{key}_{width}.png'),full_page=True)
            page.close()
    browser.close()
result={'scope':'Source templates + synthetic form fields in Chromium. No Django, database, actual HTTP POST, external AI or user session.',
    'total':len(checks),'passed':sum(c['passed'] for c in checks),'checks':checks}
(OUT/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False,indent=2))
for c in checks:
    if not c['passed']:print('FAILED:',c['name'])
raise SystemExit(0 if result['total']==result['passed'] else 1)
