from pathlib import Path
import ast,json,subprocess
SRC=Path('/mnt/data/adc_rc_work/ADC_R44/draw_models.py')
OUT=Path('/mnt/data/ADC_engineering_v1.0rc1/docs/release_report/models');OUT.mkdir(parents=True,exist_ok=True)
tree=ast.parse(SRC.read_text());nodes=[]
for n in tree.body:
 if isinstance(n,(ast.Import,ast.ImportFrom)):nodes.append(n)
 if isinstance(n,ast.ClassDef) and n.name=='SVG':nodes.append(n)
 if isinstance(n,ast.FunctionDef) and n.name in ('seq','uc'):nodes.append(n)
ns={'__file__':str(SRC),'M':OUT,'FONT':'Noto Sans CJK SC'};exec(compile(ast.Module(body=nodes,type_ignores=[]),str(SRC),'exec'),ns)
inv={}
def done(c,key,kind,pages,desc):
 c.save(key);inv[key]={'kind':kind,'course_pages':pages,'description':desc,'width':c.w,'height':c.h}
ns['done']=done;SVG=ns['SVG'];uc=ns['uc'];seq=ns['seq']
c=SVG(1050,870);c.rect(225,20,600,810);c.text(525,57,'ADC软件系统：资料与出诊维护',24,bold=True)
for i,lab,y in [(26,'更正患者联络资料',145),(27,'登记基础目录资料',290),(28,'维护牙医资格关联',435),(29,'调整未来空闲出诊',580),(30,'停用未来空闲出诊',725)]:uc(c,525,y,f'SU-{i:02}',lab,180,42)
c.actor(85,91,'前台');c.arrow([(110,127),(345,145)])
c.actor(958,320,'技术维护');
for y in (290,435):c.arrow([(934,356),(705,y)])
c.actor(85,585,'诊所主管');
for y in (580,725):c.arrow([(110,621),(345,y)])
done(c,'S04','system-use-case',[138,139,141,150,206,212],'独立用户目标；不以顺序、菜单或授权依赖充当include关系。')
c=SVG(1050,1240);c.rect(225,20,600,1180);c.text(525,57,'ADC软件系统：责任协调与站内通知',23,bold=True)
items=[(31,'核对出诊关联业务'),(32,'暂停新增接收'),(33,'恢复新增接收'),(34,'发起或撤销协调任务'),(35,'受理与办理协调任务'),(36,'独立复核协调任务'),(37,'查阅并标记本人消息'),(38,'核对派发并请求重试')]
ys={i:145+n*140 for n,(i,_) in enumerate(items)}
for i,lab in items:uc(c,525,ys[i],f'SU-{i:02}',lab,190,43)
c.actor(82,535,'前台');c.actor(965,535,'诊所主管')
for i in (31,35,37):c.arrow([(107,571),(335,ys[i])])
for i in (32,33,34,36,37,38):c.arrow([(940,571),(715,ys[i])])
done(c,'S05','system-use-case',[138,139,141,206,212],'工作台相互独立，前台与主管共享本人消息目标但不共享业务权限。')
seq('B07',[('诊所主管','worker'),('前台','worker'),('患者','actor'),('ADC系统','business_entity')],[
 ('msg',0,3,'暂停出诊新增接收(出诊编号)'),('reply',3,0,'已暂停；既有承诺保留'),
 ('msg',0,3,'发起协调任务(目标、依据)'),('reply',3,0,'任务编号；待前台受理'),
 ('msg',1,3,'查阅消息并受理任务(任务)'),('reply',3,1,'当前负责人及关联入口'),
 ('msg',1,2,'协商已有安排(服务承诺)'),('reply',2,1,'表达本人决定或尚未决定'),
 ('ref','SU-05 / SU-16：前台或患者依原授权流程分别办理；声明不替代决定'),
 ('msg',1,3,'提交协调复核(任务)'),('alt','仍有预约、有效邀约或关联异常'),
 ('reply',3,1,'拒绝提交；说明当前阻断'),('branch','核对条件满足'),('reply',3,1,'待主管复核'),
 ('msg',0,3,'独立复核任务(与提交人不同账号)'),('reply',3,0,'核对结果；不自动停用出诊'),
 ('ref','SU-29 / SU-30：主管另行核对并维护原出诊'),('endalt',)
],[87,89,108,109,112,139],bottom='新增TO-BE场景；不是对真实诊所现状的观察。通知生成不等于已读、受理或患者同意。')
# Source-backed formal state and class diagrams; Graphviz for deterministic layout.
M02=r'''digraph M02 { graph[rankdir=TB,bgcolor="white",nodesep=.6,ranksep=.75,pad=.25];node[fontname="Noto Sans CJK SC",fontsize=18,shape=box,style=rounded];edge[fontname="Noto Sans CJK SC",fontsize=14];
start[shape=point,label=""];open[label="待前台受理\nOPEN"];doing[label="前台协调中\nIN_PROGRESS"];ready[label="待主管复核\nREADY"];closed[label="协调核对已通过\nCLOSED"];cancel[label="任务已撤销\nCANCELLED"];
start->open[label="发起 [未来有效出诊且已暂停]"];
open->doing[label="受理 [当前本店前台] / 指定本人负责"];
doing->doing[label="记录办理声明 / 不改变预约事实"];
doing->ready[label="提交 [无当前业务阻断] / 保存事实摘要"];
ready->closed[label="批准 [不同账号、事实未变化且无阻断]"];
doing->open[label="本人退回或主管退回 / 解除当前受理"];
ready->open[label="主管退回 / 重新受理与核对"];
open->cancel[label="撤销 [当前本店主管]"];
doing->cancel[label="撤销 [当前本店主管]"];
ready->cancel[label="撤销 [当前本店主管]"];
note[shape=note,style="",fontsize=14,label="研究对象：CoordinationTask\nCLOSED与CANCELLED保留历史，不原地重开。\n任务终态不等于出诊已停用，也不恢复接收。"];
{rank=same;closed;cancel;}closed->note[style=invis];}
'''
D02=r'''digraph D02 {graph[rankdir=TB,bgcolor="white",nodesep=.7,ranksep=.85,pad=.2];node[shape=record,fontname="Noto Sans CJK SC",fontsize=18];edge[fontname="Noto Sans CJK SC",fontsize=15,arrowhead=none];
slot[label="{AvailabilitySlot|原出诊编号、起止时间\lbooking_paused\lintake_revision\l}"];
task[label="{CoordinationTask|目标、状态、修订\lassignee / submitted_by / reviewed_by\l提交事实摘要\l}"];
audit[label="{AuditEvent|动作、对象、发生时点\l有限变更摘要\l}"];
outbox[label="{NotificationOutbox|原任务事件、原收件授权快照\l派发状态、重试轮次\l}"];
msg[label="{InboxMessage|原事件、收件账号和授权\l首次已读标记时间\l}"];
slot->task[label="来源",taillabel="1",headlabel="0..*"];
task->outbox[label="任务变化",taillabel="1",headlabel="0..*"];
audit->outbox[label="唯一源事件",taillabel="1",headlabel="0..1"];
outbox->msg[label="站内生成",taillabel="1",headlabel="0..*"];
note[shape=note,fontsize=14,label="任务、审计及待派发事件同事务。\n通知只保存必要标识；查询时重新授权。\n未画出的账号、诊所及RoleAssignment外键保持独立。"];
msg->note[style=invis];}
'''
for key,text in [('M02',M02),('D02',D02)]:
 (OUT/f'{key}.dot').write_text(text)
 for fmt in ['svg','pdf','png']:
  subprocess.run(['dot',f'-T{fmt}','-Gdpi=190',str(OUT/f'{key}.dot'),'-o',str(OUT/f'{key}.{fmt}')],check=True)
 inv[key]={'kind':'state-machine' if key=='M02' else 'class-diagram','scope':'RC-added task/intake/notifications; no clinical authentication claim'}
c=SVG(1120,1180)
c.text(560,42,'stm M02　协调任务的状态与责任',25,bold=True)
states=[('待前台受理\nOPEN',180),('前台协调中\nIN_PROGRESS',410),('待主管复核\nREADY',640),('核对已通过\nCLOSED',900)]
for name,y in states:
 c.rect(370,y,350,96,r=18);c.text(545,y+36,name,24)
c.ellipse(545,83,8,8,fill='#202020');c.arrow([(545,92),(545,180)],solid=True)
c.text(725,119,'发起 [未来有效且已暂停]',18)
c.arrow([(545,276),(545,410)],solid=True);c.text(545,322,'受理 [当前本店前台]\n／指定本人负责',19,white=True)
c.arrow([(545,506),(545,640)],solid=True);c.text(545,550,'提交 [无当前业务阻断]\n／保存事实摘要',19,white=True)
c.arrow([(545,736),(545,900)],solid=True);c.text(545,791,'批准 [不同账号、事实未变\n且当前无业务阻断]',19,white=True)
c.arrow([(370,443),(185,443),(185,222),(370,222)],solid=True)
c.text(181,316,'本人或主管退回\n／解除当前受理',18,white=True)
c.arrow([(370,685),(82,685),(82,249),(370,249)],solid=True)
c.text(154,585,'主管退回\n／重新受理',18,white=True)
c.arrow([(720,449),(806,449),(806,484),(720,484)],solid=True)
c.text(862,393,'办理声明\n／不改变预约',18,white=True)
c.rect(826,887,250,105,r=18);c.text(951,923,'任务已撤销\nCANCELLED',22)
# Branches share a visual trunk only; explicit source states are preserved.
for y in (206,433,665):c.path([(720,y),(1045,y)])
c.arrow([(1045,206),(1045,850),(952,850),(952,887)],solid=True)
c.text(972,761,'撤销 [本店主管]\n任一未结束状态',18,white=True)
c.note(50,1040,1020,'研究对象：CoordinationTask。终态保留历史，不原地重开。\n“核对已通过”不自动停用出诊；“撤销任务”不恢复新增接收。',20)
done(c,'M02','state-machine',[339,341,350],'限定任务对象；迁移为事件、警戒与动作。各状态事实与原预约状态分开。')
(OUT/'inventory.json').write_text(json.dumps(inv,ensure_ascii=False,indent=2))
print(list(inv))
