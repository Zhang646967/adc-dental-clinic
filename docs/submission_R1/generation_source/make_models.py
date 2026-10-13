from pathlib import Path
import json,subprocess,html,textwrap
import cairosvg
OUT=Path(__file__).resolve().parents[1]/'models';OUT.mkdir(parents=True,exist_ok=True)
FONT='Noto Sans CJK SC'
def seq(fid,title,participants,events):
    W=1100;n=len(participants);xs=[100+i*(900/(n-1)) for i in range(n)]
    rows=[];y=150
    for e in events:
        if isinstance(e,dict):
            rows.append(('guard',y,e));y+=58;continue
        a,b,t,ret=e
        span=abs(xs[a]-xs[b]) if a!=b else 330
        lines=textwrap.wrap(t,width=max(10,int(span/22)-2))
        h=31*len(lines)+38
        rows.append(('msg',y,(a,b,lines,ret)));y+=h
    H=y+35
    p=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">',
       '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10 Z" fill="#263c49"/></marker><marker id="reply" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M0,0 L10,5 L0,10" fill="none" stroke="#263c49" stroke-width="1.5"/></marker></defs>',
       f'<rect width="{W}" height="{H}" fill="white"/>',f'<g font-family="{FONT},sans-serif" fill="#183b48">']
    for i,label in enumerate(participants):
        lines=label.split('\n');p.append(f'<rect x="{xs[i]-94}" y="18" width="188" height="91" rx="2" fill="#edf4f4" stroke="#516e7a" stroke-width="1.8"/>')
        for j,l in enumerate(lines):p.append(f'<text x="{xs[i]}" y="{53+j*29}" font-size="21" text-anchor="middle">{html.escape(l)}</text>')
        p.append(f'<line x1="{xs[i]}" y1="109" x2="{xs[i]}" y2="{H-12}" stroke="#91a3ad" stroke-width="1.3" stroke-dasharray="8,7"/>')
    alt_start=None
    for typ,gy,ge in rows:
        if typ=='guard' and ge['guard'].startswith('alt '):alt_start=gy-8
        if typ=='guard' and ge['guard'].startswith('end') and alt_start is not None:
            p.append(f'<rect x="10" y="{alt_start}" width="1080" height="{gy-alt_start}" fill="none" stroke="#57717e" stroke-width="2"/>')
    num=0
    for typ,y,e in rows:
        if typ=='guard':
            p.append(f'<rect x="10" y="{y-8}" width="1080" height="43" fill="#f5f8fa" stroke="#8b9eaa"/>')
            p.append(f'<text x="24" y="{y+21}" font-size="20">{html.escape(e["guard"])}</text>');continue
        a,b,lines,ret=e;num+=1
        mid=(xs[a]+xs[b])/2 if a!=b else xs[a]+155
        for j,l in enumerate(lines):
            text=(str(num)+'. ' if j==0 else '')+l
            p.append(f'<text x="{mid}" y="{y+23+j*30}" text-anchor="middle" font-size="21">{html.escape(text)}</text>')
        ay=y+30*len(lines)+12
        dash='stroke-dasharray="7,5"' if ret else ''
        marker='reply' if ret else 'arrow'
        if a==b:
            p.append(f'<path d="M{xs[a]},{ay} h45 v22 h-45" stroke="#263c49" stroke-width="1.9" fill="none" marker-end="url(#{marker})" {dash}/>' )
        else:p.append(f'<line x1="{xs[a]}" y1="{ay}" x2="{xs[b]}" y2="{ay}" stroke="#263c49" stroke-width="1.9" marker-end="url(#{marker})" {dash}/>')
    p+=['</g></svg>'];svg=''.join(p)
    (OUT/f'{fid}.svg').write_text(svg,encoding='utf-8')
    cairosvg.svg2png(bytestring=svg.encode(),write_to=str(OUT/f'{fid}.png'),scale=1.5)
    (OUT/f'{fid}.json').write_text(json.dumps({'id':fid,'title':title,'participants':participants,'events':events},ensure_ascii=False,indent=2),encoding='utf-8')

seq('B02','现状：预约、接诊与费用说明',['患者','诊所前台\n业务工作者','牙医\n业务工作者','本店业务资料\n载体未指定'],[
(0,1,'电话提出预约需求',False),(1,0,'询问身份与过敏',False),(0,1,'提供资料与偏好',True),(1,2,'协调可接诊时段',False),(2,1,'反馈可接诊时间',True),(1,3,'登记安排和资料',False),(1,0,'告知约定时间',True),(0,1,'按约到达诊所',False),(1,2,'告知患者已到诊',False),(2,3,'记录治疗与计价依据',False),(1,3,'查阅并核对费用资料',False),(3,1,'反馈本次费用资料',True),(1,0,'提供费用说明',True)])
seq('B03','改进后：统一预约与接诊结算',['患者','诊所前台\n业务工作者','ADC服务系统\n业务支持者','负责牙医\n业务工作者'],[
{'guard':'预约主成功场景：先核对并复用患者档案；新患者须按SU-03建档'},(0,1,'提出时间偏好',False),(1,2,'查资料与可用时段',False),(2,1,'返回资料和时段',True),(1,0,'核对牙医、诊所和时间',False),(0,1,'明确同意安排',True),(1,2,'提交并重验时段',False),(2,1,'返回预约编号',True),{'guard':'预约成功且患者实际到达后'},(0,1,'报告到诊',False),(1,2,'登记实际到诊',False),(3,2,'复核过敏并记录治疗',False),(3,2,'核对费用并确认完成',False),(2,3,'返回结算单与状态',True),(0,2,'查阅本人账单',False),(2,0,'展示明细、金额与版本',True)])
seq('B04','现状：季度资料归集与核对',['总部管理\n结果使用者','诊所工作人员\n业务工作者','牙医\n业务工作者','分散业务资料\n载体未指定'],[
(0,1,'请求本季度业务资料',False),(1,3,'查找本店收入记录',False),(3,1,'返回已有业务资料',True),(1,2,'收集用品成本与运营费用',False),(2,1,'提交资料并说明缺项',True),(1,0,'提交本店汇总资料',True),{'guard':'分析性替代场景[A3]：总部发现缺项或口径不一致'},(0,1,'要求补充并重新核对',False),(1,0,'补交资料及说明',True)])
seq('B05','改进后：先完整性，再季度测算',['财务人员\n业务工作者','各店／牙医\n资料提供者','ADC服务系统\n业务支持者','总部管理\n结果使用者'],[
(0,1,'收集并核对成本资料',False),(1,0,'提供金额与缺项依据',True),(0,2,'建立自然季度和纳入清单',False),(0,2,'录入、逐人核对并确认成本',False),(2,0,'反馈未确认成本或遗漏牙医',True),{'guard':'资料尚不完整时：只展示缺项，不产生完整利润结论'},(0,2,'补充核对，确认纳入范围',False),(3,2,'请求获授权的季度报告',False),(2,3,'返回缺项或完整测算',True)])
# Separate exclusive alternatives instead of depicting accepted then expired in the same path.
seq('B06','改进后：候补、邀约与明确确认',['患者／代办前台\n办理者','ADC服务系统\n业务支持者','诊所主管\n协调者'],[
(0,1,'提交诊所与可接受时间范围',False),(1,0,'返回等待安排；尚无正式预约',True),(2,1,'为本店候补生成有限匹配建议',False),(1,2,'返回候选、未安排项与能力边界',True),(2,1,'核对并发布限时邀约',False),(1,2,'发布结果及实际确认期限',True),(0,1,'主动查看候补邀约',False),(1,0,'显示牙医、时段及确认期限',True),{'guard':'alt [患者在有效期内明确接受]'},(0,1,'核对后提交接受',False),(1,0,'重验成功：返回正式预约编号',True),{'guard':'else [拒绝，或到期后尝试接受]'},(0,1,'提交拒绝或已过期的接受请求',False),(1,0,'拒绝则回到等待；过期接受不建预约',True),{'guard':'end；过期请求需另由本店前台／主管手动回收，才能再次参与匹配'}])

def usecase(fid,title,actors,cases,links,boundary):
    def q(s):return json.dumps(s,ensure_ascii=False)
    s=['digraph G {',f'graph [rankdir=LR,bgcolor="white",pad="0.25",nodesep="0.23",ranksep="0.55",fontname="{FONT}",fontsize=18];',f'node [fontname="{FONT}",fontsize=16,color="#45616d",penwidth=1.3]; edge [color="#78909a",arrowhead=none,penwidth=1.2];']
    for aid,label in actors.items():s.append(f'{aid} [shape=box,style="rounded",margin="0.15,0.10",label={q("«actor»\\n".replace("\\n","\n")+label)}];')
    s.append(f'subgraph cluster_system {{label={q(boundary)};labelloc=t;fontname="{FONT}";fontsize=19;color="#496c78";penwidth=1.5;style=rounded;')
    for cid,label in cases.items():s.append(f'{cid} [shape=ellipse,style=filled,fillcolor="#f1f6f7",margin="0.15,0.09",label={q(label)}];')
    s.append('}')
    for a,c in links:s.append(f'{a} -> {c};')
    s.append('}')
    txt='\n'.join(s);(OUT/f'{fid}.dot').write_text(txt,encoding='utf-8')
    for fmt in ['svg','png']:subprocess.run(['dot',f'-T{fmt}','-Gdpi=180',str(OUT/f'{fid}.dot'),'-o',str(OUT/f'{fid}.{fmt}')],check=True)
    (OUT/f'{fid}.json').write_text(json.dumps({'id':fid,'title':title,'actors':actors,'cases':cases,'links':links},ensure_ascii=False,indent=2))
usecase('B01','业务用例图',{'p':'患者','h':'总部运营结果使用者'},
{'b1':'BU-01 获得就诊服务','b2':'BU-02 调整就诊安排','b3':'BU-03 获取结算说明','b4':'BU-04 获取运营核对结果'},
[('p','b1'),('p','b2'),('p','b3'),('h','b4')],'ADC诊所服务与运营核对作业域')
usecase('S01','系统用例：服务主线',{'p':'患者','f':'前台','d':'牙医','fi':'财务'},
{f'u{i}':text for i,text in [(3,'SU-03 建立／查阅患者档案'),(4,'SU-04 创建预约'),(5,'SU-05 调整预约结果'),(6,'SU-06 登记实际到诊'),(7,'SU-07 复核与记录实际治疗'),(8,'SU-08 完成接诊并开单'),(9,'SU-09 查阅与打印结算单')]},
[('p','u4'),('p','u5'),('p','u9'),('f','u3'),('f','u4'),('f','u5'),('f','u6'),('f','u9'),('d','u3'),('d','u7'),('d','u8'),('d','u9'),('fi','u9')],'ADC信息系统｜服务主线（分视图）')
usecase('S02','系统用例：协同与管理',{'p':'患者','fr':'前台','m':'诊所主管','h':'总部管理','f':'财务','d':'牙医'},
{f'u{i}':text for i,text in [(10,'SU-10 管理账单数字更正'),(11,'SU-11 形成季度成本与利润核对'),(12,'SU-12 查询运营指标'),(13,'SU-13 登记／退出候补'),(14,'SU-14 生成有限排程建议'),(15,'SU-15 审核并发布限时邀约'),(16,'SU-16 接受／拒绝邀约'),(17,'SU-17 回收过期邀约'),(19,'SU-19 新增牙医出诊时段')]},
[('p','u13'),('p','u16'),('fr','u13'),('fr','u16'),('fr','u17'),('m','u14'),('m','u15'),('m','u17'),('m','u19'),('m','u12'),('h','u12'),('h','u11'),('f','u11'),('f','u10'),('d','u10')],'ADC信息系统｜协同与管理（分视图）')
usecase('S03','系统用例：身份、引导与基础管理',{'u':'系统用户（通用角色）','m':'前台／主管','t':'技术管理','f':'财务／总部','llm':'外部语言模型\n可选支持者'},
{f'u{i}':text for i,text in [(1,'SU-01 登录、选择与切换身份'),(2,'SU-02 选择与切换诊所'),(18,'SU-18 获取手动操作引导'),(20,'SU-20 选择显示与帮助方式'),(21,'SU-21 创建普通演示账号'),(22,'SU-22 管理角色与患者绑定'),(23,'SU-23 管理账号状态与重置'),(24,'SU-24 修改本人密码'),(25,'SU-25 维护／查阅标准价格目录')]},
[('u','u1'),('u','u20'),('m','u2'),('u','u18'),('llm','u18'),('t','u21'),('t','u22'),('t','u23'),('u','u24'),('f','u25')],'ADC信息系统｜公共与管理（分视图）')
print('Models:',len(list(OUT.glob('*.png'))))
