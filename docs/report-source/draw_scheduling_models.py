"""Current scheduling ownership, using retained report drawing primitives.

Historical generators and model files remain untouched. Only definitions are
loaded; none of the old generators' top-level authoring commands is executed.
"""
from pathlib import Path
import ast,hashlib,json
ROOT=Path(__file__).resolve().parents[2];M=Path(__file__).with_name('scheduling-models');M.mkdir(exist_ok=True)
source=ROOT/'docs/release_report/draw_models_R44.py';tree=ast.parse(source.read_text())
nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) and 'cairosvg' not in ast.unparse(n) or isinstance(n,ast.ClassDef) and n.name=='SVG' or isinstance(n,ast.FunctionDef) and n.name in ('seq','uc','actor_links')]
ns={'M':M,'FONT':'Noto Sans CJK SC'}
exec(compile(ast.Module(body=nodes,type_ignores=[]),str(source),'exec'),ns)
manifest={}
def done(c,key,kind,pages,desc):
 (M/(key+'.svg')).write_text(''.join(c.a)+'</svg>')
 manifest[key]=dict(description=desc,kind=kind,width=c.w,height=c.h,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
ns['done']=done
SVG,uc,seq=ns['SVG'],ns['uc'],ns['seq']
text=source.read_text();block=text[text.index('# S02 —'):text.index('# S03 —')]
block=block.replace("[14,15,19,12,17]","[12,17]").replace("[17,13,16]","[14,15,19,17,13,16]").replace('审核并发布限时邀约','核对并发布限时邀约')
exec(compile(block,str(source),'exec'),ns)
c=SVG(1050,870);c.rect(225,20,600,810);c.text(525,57,'ADC软件系统：资料与出诊维护',24,bold=True)
for i,lab,y in [(26,'更正患者联络资料',145),(27,'登记基础目录资料',290),(28,'维护牙医资格关联',435),(29,'调整未来空闲出诊',580),(30,'停用未来空闲出诊',725)]:uc(c,525,y,f'SU-{i:02}',lab,180,42)
c.actor(85,380,'前台')
for y in (145,580,725):c.arrow([(110,416),(345,y)])
c.actor(958,320,'技术维护')
for y in (290,435):c.arrow([(934,356),(705,y)])
done(c,'S04','system-use-case',[],'前台维护当前店出诊和患者联络；技术维护基础目录。')
rc=(ROOT/'docs/release_report/draw_rc_models.py').read_text();block=rc[rc.index('c=SVG(1050,1240)'):rc.index("seq('B07'")]
block=block.replace('(31,35,37)','(31,32,33,34,35,37)').replace('(32,33,34,36,37,38)','(34,36,37,38)')
exec(compile(block,'current coordination use cases','exec'),ns)
seq('B07',[('前台','worker'),('诊所主管','worker'),('患者','actor'),('ADC系统','business_entity')],[
 ('msg',0,3,'暂停新增并发起调班(目标、期限)'),('reply',3,0,'原承诺保留；任务待受理'),
 ('msg',0,3,'受理任务并核对下次联系期限'),('reply',3,0,'负责人及准确关联入口'),
 ('msg',0,2,'协商已有安排(服务承诺)'),('reply',2,0,'表达本人决定或尚未决定'),
 ('ref','联系未果保留原约；明确同意后经原改期或取消流程办理'),
 ('msg',0,3,'重新核对并提交协调复核'),('alt','仍有预约、有效邀约或关联异常'),
 ('reply',3,0,'拒绝提交；继续责任跟进'),('branch','核对条件满足'),('reply',3,0,'待另一账号主管复核'),
 ('msg',1,3,'独立复核任务(依据与当前事实)'),('reply',3,1,'复核结果；不自动变更出诊'),
 ('ref','SU-29 / SU-30：前台另行核对并维护原出诊'),('endalt',)
],[],bottom='任务、联系声明、患者决定与出诊维护分别留痕；不自动搬移或取消原预约。')
block=text[text.index("seq('B06'"):text.index('# S01',text.index("seq('B06'"))] if '# S01' in text[text.index("seq('B06'"):] else ''
# Extract the exact expression, avoiding any later historical authoring block.
module=ast.parse(text)
expr=next(n for n in module.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='seq' and n.value.args and isinstance(n.value.args[0],ast.Constant) and n.value.args[0].value=='B06')
block=ast.get_source_segment(text,expr).replace('诊所主管','前台')
exec(compile(block,'current waitlist sequence','exec'),ns)
(M/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'updated_models':list(manifest)},ensure_ascii=False))
