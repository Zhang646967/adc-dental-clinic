from pathlib import Path
from docx import Document
from docx.shared import Pt,Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from copy import deepcopy
import re,json
ROOT=Path('/mnt/data/ADC_engineering_v1.0rc1');OUT=Path('/mnt/data')
BASE=OUT/'ADC_中期报告_张加良_8210241102_R4.4_课件规范修订.docx'
d=Document(BASE);ps=list(d.paragraphs);tables=list(d.tables)
FONT='Noto Serif CJK SC';HEAD='Noto Sans CJK SC'
def font_run(run,size=12,bold=None,font=FONT):
 run.font.name='Times New Roman';run.font.size=Pt(size)
 if bold is not None:run.bold=bold
 rpr=run._element.get_or_add_rPr();f=rpr.find(qn('w:rFonts'))
 if f is None:f=OxmlElement('w:rFonts');rpr.insert(0,f)
 f.set(qn('w:eastAsia'),font);f.set(qn('w:ascii'),'Times New Roman');f.set(qn('w:hAnsi'),'Times New Roman')
 # Remove inherited vertical offsets responsible for anomalous punctuation.
 for e in list(rpr):
  if e.tag in [qn('w:position'),qn('w:vertAlign')]:rpr.remove(e)
def setp(p,text):
 p.clear();font_run(p.add_run(text));return p
def para(text='',style=None,before=None,size=12):
 p=d.add_paragraph(style=style);font_run(p.add_run(text),size,bold=style in ('Heading 1','Heading 2','Heading 3'),font=HEAD if style else FONT)
 p.paragraph_format.widow_control=True
 if before is not None:before._p.addprevious(p._p)
 return p
def heading(text,level=2,before=None,newpage=False):
 p=para(text,f'Heading {level}',before,size={1:16,2:14,3:12}[level]);p.paragraph_format.keep_with_next=True
 if newpage:p.paragraph_format.page_break_before=True
 return p
def table(headers,rows,before=None,widths=None):
 t=d.add_table(rows=1,cols=len(headers));t.autofit=False
 for cell,text in zip(t.rows[0].cells,headers):cell.text=text
 for row in rows:
  for c,text in zip(t.add_row().cells,row):c.text=str(text)
 tpr=t._tbl.tblPr
 borders=OxmlElement('w:tblBorders')
 for name in ['top','bottom','insideH']:
  e=OxmlElement('w:'+name);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'A0A0A0');borders.append(e)
 tpr.append(borders)
 for i,row in enumerate(t.rows):
  trpr=row._tr.get_or_add_trPr();no=OxmlElement('w:cantSplit');trpr.append(no)
  if i==0:trpr.append(OxmlElement('w:tblHeader'))
  for j,c in enumerate(row.cells):
   if widths:c.width=Cm(widths[j])
   for p in c.paragraphs:
    p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.space_after=Pt(4);p.paragraph_format.space_before=Pt(4);p.paragraph_format.line_spacing=Pt(16)
    for r in p.runs:font_run(r,10.5,bold=i==0,font=HEAD if i==0 else FONT)
 if before is not None:before._p.addprevious(t._tbl)
 return t
MODELS=ROOT/'docs/release_report/models'
def fig(key,title,note,before,newheading=None,maxh=18.8):
 if newheading:heading(newheading,2,before,True)
 else:
  p=para('',before=before);p.paragraph_format.page_break_before=True;p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=Pt(1)
 p=para('',before=before);p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.first_line_indent=Pt(0)
 from PIL import Image
 w,h=Image.open(MODELS/f'{key}.png').size;width=min(15.8,maxh*w/h)
 p.add_run().add_picture(str(MODELS/f'{key}.png'),width=Cm(width));p.paragraph_format.keep_with_next=True;p.paragraph_format.line_spacing=1.0;p.paragraph_format.space_after=Pt(0);p.paragraph_format.space_before=Pt(0)
 cap=para(title,'Caption',before,size=10.5);cap.alignment=WD_ALIGN_PARAGRAPH.CENTER;cap.paragraph_format.first_line_indent=Pt(0)
 para(note,before=before,size=10.5)
# Main metadata updates; original chapters/spec numbering are not discarded.
for i,text in {
2:'课 程 项 目 报 告',9:'报告版本：R5（v1.0发布候选整合版）',10:'冻结源码：v1.0.0-rc.1　｜　最后确认运行基线：Windows v0.7',11:'2026年10月9日',
16:'在原分析与设计基线上，本报告合并患者联络更正、基础目录、出诊替换与接收控制、前台协调、责任任务和站内消息等增量，并增加独立运营核算与两条跨模块演示路线。源码以v1.0.0-rc.1冻结，进入集中验收准备；冻结不是正式发布。报告分别标注案例事实、分析假设、设计决定、已运行的纯规则及静态检查和尚未运行的数据库、端到端、升级恢复与公网验收。',
19:'本报告以已修订中文字体和课件制图约定的R4.4为底稿，保留原业务模型及SU-01—25，合并SU-26—38形成发布候选的统一需求基线。本文“课件第×页”指《系统分析与设计-精简2026-9.pdf》的物理页码；具体角色、限额、时间和架构为本项目决定。“应当”表达需求，“已执行”仅适用于列明证据。原R4.4留作历史，不以本报告覆盖过去的测试状态。',
20:'教师必需材料映射：项目愿景见第1章；业务用例及现状／改进序列见第2章；系统用例见第3章；SU-01—25及共享核验见附录A，SU-26—38见附录B。第4—6章说明分析责任、设计取舍、验证边界和版本收敛，不替代需求主干。',
63:'范围包括资料与账号、预约到诊、实际治疗与版本化结算、季度核对、候补有限匹配和操作引导，并纳入基础目录、联络更正、出诊维护／接收控制、责任任务及任务站内消息。完整用例清单见附录A／B。',
113:'SU-01—25及SF-01规约见附录A；SU-26—38见附录B。各用例表示独立可接受的用户目标，不用用例间箭头表达业务办理顺序。原始用例编号保持稳定，新增关系只在规约支持时引入。',
143:'开发中曾发现只读模式按POST方法一律拒绝，与SU-24携带签名上下文的只读核对冲突。当前候选沿用经审核路由名的受限例外，保留CSRF、当前身份、对象、旧页面令牌和服务端写入检查；本轮再统一全角色只读提示及表单错误定位。[9-10]',
146:'常规停用要求先处理未闭合业务，以保护业务连续性；但疑似凭据泄露时继续允许访问会妨碍安全处置。SU-25因此将安全访问控制与业务责任交接分离；技术人员只能对受控普通账号操作，不开放自操作、技术账号或超级用户目标。',
154:'RC保留原生产配置候选，另增加仅面向本机合成数据的course_demo配置与独立compose.rc.yaml。RC入口使用Gunicorn和Nginx并仅向127.0.0.1开放默认18000端口；数据库不开放宿主机端口。它不是公网HTTPS生产配置；后者仍需独立角色、证书、网络及恢复验收。[9,13-14]',
164:'AT-01—25对应原SU同号验收组；新增SU-26—38使用各增量规约中的AT-D、AT-A、AT-FC、AT-I、AT-T、AT-N等组名。验收编号是目标，不是已经通过的次数。图、规约、实现路径、测试定义及真实输出必须绑定同一版本。',
166:'本轮合并此前的只读查询与安全封禁修订，并建立“业务目标—系统用例—实现责任—验收证据”统一追踪。批次A用固定合成输入和独立期望核对生产规则，另编写跨模块服务链；批次B将隔离验证、新建演示和旧数据副本升级区分为不同入口，不允许新建流程覆盖旧实例。',
171:'本轮生成环境未安装Django、psycopg、PostgreSQL或Docker；依赖获取遇到域名解析失败。已执行的纯规则、源码合同、静态浏览器检查不能替代真实框架／数据库测试。集中验证将记录实际Python、Django、psycopg、Gunicorn及其他已安装版本；requirements中的选择在解析前不是完整依赖锁。',
173:'本次范围冻结后，先在独立库执行G1，再用v0.7合成数据副本执行G2，随后执行G3真实多角色浏览器主链及通知后台故障恢复，最后单独验收G4公网部署。不再以新增大型模块推迟已有系统的实证核对。',
174:'开发阶段的可执行检查已经归档；用户本机的集中验证按约定在发布候选形成后开始。多资源、短信邮件、真实支付及Mac迁移明确延期。版本号不是成熟度指标，测试数量也不是需求覆盖率。[2,7]',
176:'以下为用户此前本地v0.7合成数据演示截图，保留版本背景；仅支持图示路径，不作为本轮RC真实运行证据。裁切仅去掉无关边缘，不改变业务状态文字。',
183:'当前形成一套冻结范围的分析、设计与候选实现。核心边界包括角色与诊所分离、预约意向与实际计费分离、当前档案与历史账单分离、出诊供给与患者承诺分离，以及任务、消息与业务事实分离。新增代码围绕这些边界衔接，而不是把更多操作集中在同一个主页。',
184:'批次A完成独立核算样本、两条服务链测试定义、操作脚本及全局错误／只读提示；批次B完成版本归一、独立实例入口、数据库准备与Web／通知后台顺序、升级副本和恢复说明，并将增量规约并入本报告。实际安装、数据库事务与并发、浏览器、升级恢复及公网检查仍是发布门槛，不因候选冻结被视为通过。',
189:'本报告是与v1.0.0-rc.1对应的课程分析与设计整合稿，供集中验收及后续答辩使用；不是已上线系统的认证材料。后续保留RC范围，只修复发现的缺陷并补充实际证据，不删除未验证标记制造完成度。',
207:'本附录继承R4.4中的SU-01—25及SF-01，编号、核心业务保证与课件表达保持。新增维护与协同用例位于附录B；共同业务约束与最新版范围见正文。交互按钮不是业务目标，AT组也不是已经通过的测试事件。'
}.items():setp(ps[i],text)
# Fix metadata fonts/cover hierarchy after textual changes.
for i,size in [(0,22),(1,17),(2,24),(3,20),(4,14),(9,11),(10,10.5),(11,12)]:
 for r in ps[i].runs:font_run(r,size,bold=i<4,font=HEAD if i<5 else FONT)
# Freeze wording without widening the original patient-invitation scope.
for p in d.paragraphs:
 if '当前实现为固定30分钟、有限候选最大匹配；没有短信、邮件或后台自动派发' in p.text:
  setp(p,'患者候补仍为固定30分钟、有限候选最大匹配，未提供患者短信、邮件或自动通知。任务站内消息另见第3.7节。邀约保留至发布后15分钟或预约开始的较早时点；这些期限与上限为项目设计。')
setp(ps[64],'仅供合成数据演示；不含真实支付、医保税务、完整病历影像、AI诊断、代理就诊、资格自动认证或自动改排。结算单不是税务发票或支付凭证，开单金额不是实收。多资源和CP-SAT延期。')
# Remove two redundant bridge notes to prevent one-sentence orphan pages.
for p in list(d.paragraphs):
 if p.text.startswith(('BR-14、BR-15为本轮风险评审','这种追踪用于定位变化影响','案例中的顾问已开展信息需求评估')):
  p._element.getparent().remove(p._element)
# Table facts and release status.
tables[0].rows[5].cells[1].text='承诺、接收控制、任务与消息分开；已有安排不会被隐式撤销'
tables[1].rows[6].cells[1].text='普通账号、基础资料登记、资格记录关联与安全处置'
tables[7].add_row().cells[0].text='notifications'
tables[7].rows[-1].cells[1].text='事务内记录派发意图、个人收件箱、显式已读和有限重试'
tables[7].rows[-1].cells[2].text='原收件授权与当前权限、去重与重试；消息不驱动任务状态。'
for row in [('G1　资料维护','S04；D01','SU-26—28','字段白名单；AT-D、联络更正测试'),('G2/G5　出诊协调','B07；S04/S05；M02','SU-29—36','AT-A／FC／I／T；原承诺与独立复核'),('G3/G5　站内消息','S05；D02','SU-37／38','AT-N；权限、去重、失败重试')]:
 for c,tx in zip(tables[10].add_row().cells,row):c.text=tx
new_ev=[('运行实例','最后确认Windows v0.7；旧截图保留历史背景。','不是RC本机运行或并发证明。'),('候选源码','1.0.0-rc.1合并alpha.10及批次A／B，功能范围冻结。','尚未在用户环境验收，不是正式发布。'),('Python基础','799个方法实际通过，包括新增12个运营规则／参考核算和20个发布合同方法。','方法数不等于业务场景数或覆盖率。'),('JavaScript契约','候补18条、出诊16条断言通过。','不是全部设备或真实表单提交。'),('静态浏览器','全局七角色672条、通知756条、任务888条检查通过。','转换源模板＋合成数据；不是真实Django会话或端到端。'),('数据库定义','680个方法已编写，新增7个跨模块服务链方法；16份迁移未修改。','未执行，不证明事务、HTTP、触发器、并发和迁移成立。'),('部署／恢复','三种RC路径及私密副本比较脚本已编写；实际Docker、恢复、负载与公网尚未执行。','配置文件或校验和不是实机验收。')]
for row,vals in zip(tables[11].rows[1:],new_ev):
 for c,tx in zip(row.cells,vals):c.text=tx
newfuture=[('G1　隔离环境','依赖解析、实际版本记录、check、模式差异、空库迁移与完整数据库测试。','所有步骤与清理结果正确；失败先修。'),('G2　升级与恢复','停写后取得私密备份，恢复至新RC库；比较旧记录与业务金额。','不是列出备份目录；不覆盖原v0.7，不丢失RC新增数据。'),('G3　真实路径','七角色、两条主链、手机／大字／键盘、旧页、只读、worker停机与恢复。','真实会话、数据后置条件和人工独立观察。'),('G4　公网环境','域名证书、非开发服务器、私有数据库、后台监督、日志与备份。','仅合成数据；不宣称临床或支付上线。'),('后续范围','多资源占用、CP-SAT、短信邮件、专业资格认证及Mac迁移。','不阻塞本次候选验收；另行建模、实现及取证。')]
for row,vals in zip(tables[12].rows[1:],newfuture):
 for c,tx in zip(row.cells,vals):c.text=tx
# Figures inserted near their corresponding conceptual layer.
fig('B07','图2-7  改进后的出诊责任协调业务序列（B07）','主管先明确暂停新增，前台协商并通过原业务流程处理；有阻断不得提交。只在提交与独立复核成立的分支进入后续维护。该TO-BE模型不声称新增了临床停诊或患者自动同意。',ps[100],'2.7　改进后的业务序列：责任协调',18.7)
fig('S04','图3-4  资料与出诊维护系统用例（S04）','角色来自实际业务交互，不因技术管理身份而扩大临床或财务权限；用例之间不以时间先后建立include。详见附录B的SU-26—30。',ps[125],'3.6　资料与出诊维护扩展需求',18.5)
fig('S05','图3-5  责任协调与站内通知系统用例（S05）','前台和主管分别承担受理与独立复核；两者均可查看本人的当前范围消息。通知后台属于内部实现机制，不冒充业务执行者。详见SU-31—38。',ps[125],'3.7　协同任务与通知需求',18.6)
fig('D02','图4-6  出诊、任务和通知的概念关联（D02）','补充类图仅展示新增关系；类分栏与端点多重性区分归属。源审计唯一、事件与原授权消息去重等约束须在真实数据库验收。既有患者、治疗和账单关系仍见图4-1。',ps[160],'4.7　协调与通知的数据责任',18.2)
fig('M02','图4-7  协调任务状态机（M02）','研究对象为CoordinationTask；任务状态不能代替出诊、预约或消息状态。终态作为历史保存，不把对象的初始点解释为整个业务流程的开始。（课件第339—345、350页）',ps[160],'4.8　任务状态与独立复核',18.1)
heading('4.9　RC运行路径与安全边界',2,ps[160],True)
para('三种路径使用同一候选源码，但目的与数据权限不同。verify面向临时空库；new-demo仅面向全新合成实例；import-copy仅恢复可信合成备份到新的RC库。任一路径均不得从目录名猜测原v0.7数据卷，也不自动停止或改写原实例。',before=ps[160])
table(['路径','前置保护','结果与剩余验证'],[
('隔离验证','独立Compose项目、合成凭据、临时数据库；固定测试配置。','运行时记录实际依赖；验证容器以root写导出证据，不代表非rootWeb部署已验收。'),
('全新演示','无.env、无既有RC数据卷、无READY标记，显式合成确认。','空库迁移后初始化；私密文件保存演示凭据；不作用于导入副本。'),
('导入副本','可信备份，新的项目、空数据库；不调用seed或密码重置。','恢复前后／迁移前后核对范围不同；金额、授权及未覆盖表仍须人工核验。'),
('启动与停止','只有完成准备的实例可启动；停止仅针对本RC项目。','db健康→schema完成→Web及worker→本地网关。只读worker退出不写；没有删除卷命令。')],ps[160],[2.8,6.0,7.2])
para('旧就地升级入口在RC中改为停止提示，以免沿用早期脚本忽略新增通知写入端。最终切换前须人工冻结全部旧写入端，重新导出最终数据；演练备份不覆盖之后的新记录。回退也不得忽略RC期间新增数据。',before=ps[160])
# Independent accounting evidence, not financial guidance.
heading('5.6　独立核算样本与交互核对',2,ps[182],True)
para('tests/data/release_oracles.json先保存固定输入与独立期望；checks/test_release_oracles.py将整数分／千分数量参考推导与实际规则分别比较。另有7个PostgreSQL跨模块服务链测试定义，尚未执行；手动演示脚本也不是自动浏览器通过记录。',before=ps[182])
table(['检查问题','固定期望','错误实现应被发现'],[
('逐行舍入','0.500×0.01分别两行，共0.02。','先汇总未舍入的0.010再舍入，只得0.01。'),
('收入／成本不同粒度','收入199.98；两位牙医成本合计130；利润69.98，基金7.00。','遗漏没有收入牙医的100成本，或按治疗行重复计成本。'),
('更正与历史','当前版本99.99；同样成本下利润−30.01；旧版本仍199.98。','重复累计原与新版本，或目录250的新价覆盖旧账。'),
('缺失和明确零','缺失不可形成完整利润；确认零不同于未填写。','将NULL、草稿或未确认名单直接按零计算。'),
('取消与爽约分母','6到诊＋2患者取消＋1爽约＝9；取消率22.22%。','计入诊所取消、改期替代或待核实记录。'),
('季度边界','北京时间季度起点包含，下一季度起点不包含。','UTC日期直接分季，或两边都包含同一时点。')],ps[182],[3,6,7])
para('批次A对全角色增加同名“逐步操作指南”和“操作问答”，在只读模式持续显示限制。字段错误摘要链接到实际错误控件，保留隐藏上下文和CSRF字段；不自动提交、不默改输入。672条全局静态断言覆盖7角色×3宽度×2字号×2只读状态；真实辅助技术及业务页面仍在G3核对。',before=ps[182])
# Appendix B: import specs from their authoritative increment sources, no planning sections.
heading('附录B　增量用例规约（SU-26—38）',1,newpage=True)
para('以下规约从各增量的需求文件合并，沿用原编号与业务语义。实现状态统一为RC候选，验证状态见第5章。共同签名、权限、只读、审计及失败保证继续有效；任务写入在当前RC中还须同步保存通知发件箱，入队失败回滚原任务。原文件中“本增量不通知患者”仍成立：站内任务消息不是患者通知。')
filespec={
26:'increments/SU-26_contact_correction.md',27:'SU27_SU28_DIRECTORY.md',28:'SU27_SU28_DIRECTORY.md',29:'SU29_SU30_AVAILABILITY.md',30:'SU29_SU30_AVAILABILITY.md',31:'SU31_FRONT_COORDINATION.md',32:'SU32_SU33_INTAKE_CONTROL.md',33:'SU32_SU33_INTAKE_CONTROL.md',34:'SU34_SU35_SU36_COORDINATION_TASKS.md',35:'SU34_SU35_SU36_COORDINATION_TASKS.md',36:'SU34_SU35_SU36_COORDINATION_TASKS.md',37:'SU37_SU38_NOTIFICATIONS.md',38:'SU37_SU38_NOTIFICATIONS.md'}
specs={}
for num,f in filespec.items():
 text=(ROOT/'docs'/f).read_text()
 if num==26:
  title='SU-26　更正患者联络资料';body=text.split('## A.')[1].split('## D.')[0];body='## A.'+body
 elif num==31:
  title='SU-31　按出诊核对关联业务并定位协调入口';body=text.split('## 1. 用例规约')[1].split('## 2.')[0]
 else:
  m=re.search(r'^## SU-'+str(num)+r'[^\n]*\n',text,re.M);assert m,(num,f)
  title=m.group(0).strip('# \n').replace(' ', '　',1);body=text[m.end():].split('\n## ')[0]
 heading(title,3,newpage=num!=26)
 specs[num]={'title':title,'source':f,'text':body.strip()}
 lines=body.strip().splitlines();idx=0
 while idx<len(lines):
  line=lines[idx].strip();idx+=1
  if not line:continue
  if line.startswith('|'):
   rows=[line]
   while idx<len(lines) and lines[idx].lstrip().startswith('|'):rows.append(lines[idx].strip());idx+=1
   data=[[x.strip() for x in row.strip('|').split('|')] for row in rows if not re.fullmatch(r'[|:\-\s]+',row)]
   if data:table(data[0],data[1:],widths=[16/len(data[0])]*len(data[0]))
   continue
  textline=re.sub(r'\*\*|`','',line).lstrip('# ').strip()
  if textline.startswith('- '):textline='• '+textline[2:]
  p=para(textline,size=10.5)
  p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.space_after=Pt(2);p.paragraph_format.line_spacing=Pt(15)
  if line.startswith('#') or (len(textline)<30 and textline.endswith('：')):
   p.paragraph_format.keep_with_next=True
   for r in p.runs:font_run(r,11,bold=True,font=HEAD)
 if num==33:para('字段（沿用SU-32）：出诊编号、恢复依据、当前上下文与修订、状态签名、操作编号、确认签名及明确确认。',size=10.5)
 if num==36:para('字段：任务／源出诊编号、复核依据、提交事实摘要、状态与确认令牌、操作编号、当前上下文和明确确认。通过前后都须检查主管与提交人不是同一账号。',size=10.5)
 if num in (34,35,36):para('RC共享通知规则：成功任务变化、审计和NotificationOutbox同一事务保存；不向患者发送信息，派发失败不重新执行任务。',size=10.5)
(ROOT/'docs/release_report/merged_specs.json').write_text(json.dumps(specs,ensure_ascii=False,indent=2))
# Replace old static TOC by stable top-level links. Page numbers populated after first PDF render.
for p in ps[22:49]:p._element.getparent().remove(p._element)
# Headings still stable; bookmark all relevant entries.
headings=[p for p in d.paragraphs if p.style.name=='Heading 1' and not p.text.startswith(('摘','目'))]
toc_meta=[]
for i,h in enumerate(headings):
 bid=3000+i;name=f'rc_ch_{i}'
 b=OxmlElement('w:bookmarkStart');b.set(qn('w:id'),str(bid));b.set(qn('w:name'),name)
 e=OxmlElement('w:bookmarkEnd');e.set(qn('w:id'),str(bid));h._p.insert(0,b);h._p.append(e)
 p=para('',before=ps[49]);p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.space_after=Pt(8)
 p.paragraph_format.tab_stops.add_tab_stop(Cm(15.5),2,1)
 link=OxmlElement('w:hyperlink');link.set(qn('w:anchor'),name)
 r=OxmlElement('w:r');t=OxmlElement('w:t');t.text=h.text; r.append(t);link.append(r);p._p.append(link)
 font_run(p.add_run('\t—'),12)
 toc_meta.append({'title':h.text,'anchor':name})
para('阅读定位：第2章含7张业务模型；第3章含5张系统用例图；第4章含核心与增量模型。用例主干在附录A，增量在附录B。页码按本次PDF生成后核对，修改后须重新生成。',before=ps[49],size=10.5)
# Normalize existing table text and first-line indents without destroying structure/images.
for t in d.tables:
 for i,row in enumerate(t.rows):
  for c in row.cells:
   for p in c.paragraphs:
    p.paragraph_format.first_line_indent=Pt(0);p.paragraph_format.space_before=Pt(2);p.paragraph_format.space_after=Pt(2);p.paragraph_format.line_spacing=Pt(16)
    for r in p.runs:font_run(r,10.5,bold=i==0,font=HEAD if i==0 else FONT)
for sec in d.sections:
 for p in sec.header.paragraphs:
  if '中期报告' in p.text:setp(p,p.text.replace('中期报告','课程报告 · RC1'))
  for r in p.runs:font_run(r,9,font=HEAD)
# Preserve body formula baseline; explicitly selected CJK fonts are installed for local rendering.
for p in d.paragraphs:
 if p.style.name in ('Heading 1','Heading 2','Heading 3'):
  for r in p.runs:font_run(r,{'Heading 1':16,'Heading 2':14,'Heading 3':12}[p.style.name],True,HEAD)
 d.core_properties.author='张加良';d.core_properties.title='ADC牙科连锁运营管理系统课程报告';d.core_properties.subject='v1.0.0-rc.1分析、需求、设计与集中验收准备'
out=OUT/'ADC_课程报告_张加良_8210241102_R5_RC1.docx';d.save(out)
(ROOT/'docs/release_report/toc.json').write_text(json.dumps(toc_meta,ensure_ascii=False,indent=2))
print(out, 'specs',len(specs),'tables',len(d.tables),'paragraphs',len(d.paragraphs))
