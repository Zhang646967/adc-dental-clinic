from pathlib import Path
import html, math, json
import cairosvg
W=Path(__file__).resolve().parent
M=W/'models'; M.mkdir(exist_ok=True)
FONT='Noto Sans CJK SC'
class SVG:
 def __init__(self,w,h):
  self.w=w;self.h=h;self.a=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">', '<rect width="100%" height="100%" fill="white"/>']
 def line(self,x1,y1,x2,y2,dash=False,width=1.7):
  self.a.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#202020" stroke-width="{width}"'+(' stroke-dasharray="7,5"' if dash else '')+'/>')
 def rect(self,x,y,w,h,r=0,fill='white',width=1.7):
  self.a.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="#202020" stroke-width="{width}"/>')
 def ellipse(self,cx,cy,rx,ry,fill='white'):
  self.a.append(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" fill="{fill}" stroke="#202020" stroke-width="1.7"/>')
 def text(self,x,y,text,size=21,anchor='middle',bold=False,under=False,white=False):
  lines=str(text).split('\n'); lh=size*1.35
  if white:
   wid=max(sum(1 if ord(c)>255 else .56 for c in l) for l in lines)*size+12
   self.a.append(f'<rect x="{x-wid/2}" y="{y-size}" width="{wid}" height="{lh*len(lines)+5}" fill="white"/>')
  for k,l in enumerate(lines):
   if under:
    uw=sum(size*(1 if ord(cc)>255 else .56) for cc in l)
    self.line(x-uw/2, y+k*lh+5, x+uw/2, y+k*lh+5, width=1)
   self.a.append(f'<text x="{x}" y="{y+k*lh}" font-family="{FONT}" font-size="{size}" text-anchor="{anchor}"'+(' font-weight="700"' if bold else '')+(' text-decoration="underline"' if under else '')+' fill="#101010">'+html.escape(l)+'</text>')
 def path(self,pts,dash=False,width=1.7):
  self.a.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in pts)+'" fill="none" stroke="#202020" stroke-width="'+str(width)+'"'+(' stroke-dasharray="7,5"' if dash else '')+'/>')
 def arrow(self,pts,dash=False,solid=False):
  self.path(pts,dash);(x0,y0),(x,y)=pts[-2:];ang=math.atan2(y-y0,x-x0);l=11
  p1=(x-l*math.cos(ang-.4),y-l*math.sin(ang-.4));p2=(x-l*math.cos(ang+.4),y-l*math.sin(ang+.4))
  if solid:self.a.append(f'<polygon points="{x},{y} {p1[0]},{p1[1]} {p2[0]},{p2[1]}" fill="#202020"/>')
  else:self.path([p1,(x,y),p2])
 def actor(self,x,y,name,business=False,size=21):
  self.ellipse(x,y+12,10,12)
  if business:self.line(x-5,y+22,x+9,y+8,width=1.1)
  self.line(x,y+24,x,y+56);self.line(x-21,y+36,x+21,y+36)
  self.line(x,y+56,x-17,y+78);self.line(x,y+56,x+17,y+78)
  self.text(x,y+108,name,size)
 def worker(self,x,y):
  self.ellipse(x,y+33,24,38);self.line(x+2,y+70,x+22,y+39,width=1.2)
  self.ellipse(x,y+14,6,8);self.line(x,y+23,x,y+44);self.line(x-10,y+31,x+10,y+31);self.line(x,y+44,x-10,y+60);self.line(x,y+44,x+10,y+60)
  self.arrow([(x+5,y-8),(x-3,y-6),(x+2,y+1)])
 def business_entity(self,x,y):
  self.ellipse(x,y+33,25,37);self.line(x-8,y+67,x+23,y+40);self.line(x-29,y+73,x+29,y+73)
 def analysis_icon(self,x,y,kind):
  self.ellipse(x,y+30,28,28)
  if kind=='boundary':self.line(x-40,y,x-40,y+60);self.line(x-40,y+30,x-28,y+30)
  elif kind=='control':self.arrow([(x+7,y+1),(x-3,y+1),(x+2,y-6)])
  elif kind=='entity':self.line(x-33,y+62,x+33,y+62)
 def note(self,x,y,w,text,size=18):
  lines=text.split('\n');h=18+len(lines)*size*1.35;self.rect(x,y,w,h,fill='#f7f7f7',width=1)
  self.text(x+12,y+size+6,text,size,anchor='start')
 def save(self,key):
  s='\n'.join(self.a+['</svg>']);(M/f'{key}.svg').write_text(s)
  cairosvg.svg2png(bytestring=s.encode(),write_to=str(M/f'{key}.png'),scale=2.7)
  cairosvg.svg2pdf(bytestring=s.encode(),write_to=str(M/f'{key}.pdf'))

# All figures have source-backed semantic metadata separate from rendered text.
inventory={}
def done(c,key,kind,pages,desc):
 c.save(key);inventory[key]={'kind':kind,'course_pages':pages,'description':desc,'width':c.w,'height':c.h}

def uc(c,x,y,ident,label,rx=154,ry=36,business=False):
 c.ellipse(x,y,rx,ry)
 if business:c.line(x+rx*.52,y+ry*.87,x+rx*.95,y-ry*.25,width=1.1)
 c.text(x,y-5,ident,17);c.text(x,y+21,label,21)

# B01 — organization boundary, not software boundary
c=SVG(960,570);c.rect(200,20,570,520);c.text(485,57,'诊所服务与运营核对业务域',24,bold=True)
c.actor(80,200,'患者',True);c.actor(870,390,'总部管理',True)
for k,label,y in [('BU-01','获得就诊服务',130),('BU-02','调整就诊安排',250),('BU-03','获取结算说明',370),('BU-04','获取运营核对结果',490)]:uc(c,485,y,k,label,175,39,True)
for y in [130,250,370]:c.arrow([(105,237),(310,y)])
c.arrow([(845,427),(660,490)])
c.text(80,335,'业务执行者',17);c.text(870,527,'业务执行者',17)
done(c,'B01','business-use-case',[85,86,87,93],'责任边界外为患者与总部管理；圈内用例是业务价值。')

# Sequence rendering with receiver-owned requests and dashed replies.
def seq(key,lanes,events,pages,kind='business',bottom=''):
 width=1050; xs=[100+i*(850/(len(lanes)-1)) for i in range(len(lanes))]
 # event types: msg, reply, self, divider, alt, branch, endalt, ref.
 y=174; positions=[]
 for e in events:
  typ=e[0]
  if typ in ('msg','reply'):
   a,b,label=e[1:];dist=abs(xs[b]-xs[a]); avail=max(130,dist-30)
   maxunits=max(8,avail/20);chunks=[]
   for line in label.split('\n'):
    while line:
     units=0;cut=0
     for ch in line:
      u=1 if ord(ch)>255 else .56
      if units+u>maxunits:break
      units+=u;cut+=1
     if cut==0:cut=1
     while cut<len(line) and line[cut] in '，。、；：！？）)]》”':cut+=1
     if cut<len(line) and line[cut-1] in '（([《“':cut-=1
     chunks.append(line[:cut]);line=line[cut:]
   positions.append((e,y,chunks));y+=max(49,len(chunks)*24+16)
  elif typ=='self':positions.append((e,y,e[2].split('\n')));y+=max(73,len(e[2].split('\n'))*24+32)
  elif typ in ('alt','branch'):
   if positions and positions[-1][0][0]=='self':y+=30
   positions.append((e,y,[]));y+=45
  elif typ=='endalt':positions.append((e,y,[]));y+=(45 if key=='B04' else 20)
  elif typ=='divider':positions.append((e,y,[]));y+=42
  elif typ=='ref':positions.append((e,y,[]));y+=58
 height=y+(75 if bottom else 20);c=SVG(width,height)
 c.text(15,25,('sd '+key+'  业务序列' if kind=='business' else 'sd '+key+'  分析序列（基本路径）'),18,anchor='start')
 for x,(name,k) in zip(xs,lanes):
  if k=='actor':c.actor(x,34,'',True if kind=='business' else False)
  elif k=='worker':c.worker(x,38)
  elif k=='business_entity':c.business_entity(x,38)
  else:c.analysis_icon(x,43,k)
  c.text(x,139,':'+name,18,under=True)
  c.line(x,155,x,height-60,True,1.1)
 stack=[]
 # frame boxes under messages
 for e,yy,chunks in positions:
  if e[0]=='alt':stack.append(yy)
  if e[0]=='endalt':
   st=stack.pop();c.rect(18,st-24,1014,yy-st+26,fill='none',width=1.4);c.rect(18,st-24,62,30,fill='white');c.text(49,st-2,'alt',18)
 for e,yy,chunks in positions:
  typ=e[0]
  if typ in ('msg','reply'):
   a,b,label=e[1:];x1=xs[a];x2=xs[b];endY=yy+(len(chunks)-1)*24+6
   c.text((x1+x2)/2,yy-9,'\n'.join(chunks),20,white=True)
   if typ=='msg':c.rect(x2-5,endY-5,10,24,fill='white',width=1)
   c.arrow([(x1,endY),(x2-5 if x2>x1 else x2+5,endY)],typ=='reply',typ=='msg')
  elif typ=='self':
   a,label=e[1:];x=xs[a];endY=yy+len(chunks)*24
   side=1 if a<len(xs)-1 else -1
   c.text(x+side*36,yy-8,'\n'.join(chunks),20,anchor='start' if side>0 else 'end',white=False)
   c.rect(x-5,yy+4,10,endY-yy+25,fill='white',width=1)
   c.arrow([(x+5*side,yy+8),(x+side*33,yy+8),(x+side*33,endY+14),(x+5*side,endY+14)],solid=True)
  elif typ=='divider':
   c.line(16,yy+5,1035,yy+5,True,1);c.text(525,yy+11,e[1],18,white=True)
  elif typ in ('alt','branch'):
   if typ=='branch':c.line(18,yy-25,1032,yy-25,True,1)
   c.text(91,yy+5,'['+e[1]+']',19,anchor='start',white=False)
  elif typ=='ref':c.rect(19,yy-15,1011,44,fill='#f7f7f7');c.text(525,yy+13,'ref  '+e[1],18)
 if bottom:c.note(18,height-53,1014,bottom,17)
 done(c,key,kind+'-sequence',pages,'消息为接收者承担的责任；实例、生命线和返回分开；无额外业务能力。')

seq('B02',[('患者','actor'),('前台','worker'),('负责牙医','worker'),('本店业务记录载体','business_entity')],[
 ('msg',0,1,'受理预约(资料、意向)'),('msg',1,3,'查询既有资料与安排(识别信息)'),('reply',3,1,'本店可核对的记录'),('msg',1,2,'核对接诊安排(意向、时间)'),('reply',2,1,'可接诊安排'),('msg',1,3,'登记预约(患者、牙医、时间)'),('reply',1,0,'预约安排'),('divider','预约日到店（同一业务实例的后续时刻）'),('msg',0,1,'办理到诊(预约)'),('msg',1,2,'安排接诊(患者、主诉)'),('self',2,'复核过敏并实施\n专业治疗()'),('msg',2,3,'记录实际治疗(项目、数量、单价)'),('msg',0,1,'提供费用说明(本次就诊)'),('msg',1,3,'核对治疗费用(本次就诊)'),('reply',3,1,'本次费用明细'),('reply',1,0,'费用说明')
],[86,87,105,108,109,111],bottom='A1/A2：岗位交接及既有记录载体为分析假设，不声称经过机构现场观察。')

seq('B03',[('患者','actor'),('前台','worker'),('负责牙医','worker'),('ADC系统','business_entity')],[
 ('msg',0,1,'受理预约(资料、意向)'),('msg',1,3,'识别或登记患者(资料、过敏)'),('reply',3,1,'可复用患者编号'),('msg',1,3,'创建预约(患者、牙医、时间、意向)'),('self',3,'核验时间与占用()'),('reply',3,1,'预约编号与安排'),('reply',1,0,'预约安排'),('divider','预约日到店'),('msg',0,1,'办理到诊(预约)'),('msg',1,3,'登记实际到诊(预约)'),('msg',0,2,'提供诊疗服务(主诉、就诊)'),('self',2,'复核过敏并实施\n专业治疗()'),('msg',2,3,'记录复核及实际治疗(就诊、明细)'),('msg',2,3,'完成就诊并开单(已核对的明细)'),('reply',3,2,'唯一结算单与当前明细'),('reply',2,0,'本次诊疗与费用说明')
],[87,89,108,109,112,139,314],bottom='前台代办主路径；患者自助是SU-04的另一入口。专业诊疗责任仍由牙医承担。')

seq('B04',[('总部管理','actor'),('财务','worker'),('各店工作人员','worker'),('本店业务记录载体','business_entity')],[
 ('msg',0,1,'编制季度核对结果(季度)'),('msg',1,2,'归集业务与成本资料(季度)'),('msg',2,3,'检索季度明细(季度)'),('reply',3,2,'本店业务明细'),('reply',2,1,'收入依据、用品成本及运营费用'),('self',1,'核对人员范围与\n资料缺失()'),('alt','发现缺失，需要补充'),('msg',1,2,'补充或解释缺失项(清单)'),('reply',2,1,'补充资料或缺失说明'),('branch','未发现缺失'),('self',1,'确认已收到资料\n可供汇总()'),('endalt',),('self',1,'汇总并说明口径()'),('reply',1,0,'季度核对结果及未决事项')
],[105,108,109,112],bottom='A2/A3：归集和追问顺序为分析假设；未收到成本不等于成本为零。')

seq('B05',[('总部管理','actor'),('财务','worker'),('ADC系统','business_entity')],[
 ('msg',0,1,'组织季度核对(季度)'),('msg',1,2,'维护并确认成本(牙医、季度、依据)'),('reply',2,1,'成本确认结果'),('msg',1,2,'确认纳入人员范围(季度、清单)'),('reply',2,1,'范围确认结果'),('msg',0,2,'查询季度核对(季度)'),('self',2,'核验人员范围及\n成本完整性()'),('alt','资料完整'),('self',2,'按当前有效结算\n测算利润与基金()'),('reply',2,0,'收入、成本、利润、期间与口径'),('branch','存在缺失或未确认项'),('reply',2,0,'缺失清单；不形成完整利润测算'),('endalt',)
],[89,108,109,139],bottom='财务写入、总部查阅；“反馈结果”使用虚线返回，不画成总部被调用的辅助功能。')

seq('B06',[('患者','actor'),('诊所主管','worker'),('ADC系统','business_entity')],[
 ('msg',0,2,'登记候补(诊所、时间偏好)'),('reply',2,0,'候补编号；尚未预约'),('msg',1,2,'生成排程建议(本店)'),('reply',2,1,'草案、未安排项及能力边界'),('msg',1,2,'发布限时邀约(已核对草案)'),('self',2,'重验约束并建立\n限时保留()'),('reply',2,1,'发布结果与确认期限'),('msg',0,2,'查询本人候补(候补编号)'),('reply',2,0,'邀约时间与确认期限'),('alt','选择接受，且邀约有效、核验通过'),('msg',0,2,'接受邀约(邀约编号)'),('reply',2,0,'已转预约；准确关联的预约编号'),('branch','选择拒绝，且邀约仍有效'),('msg',0,2,'拒绝邀约(邀约编号)'),('reply',2,0,'已释放保留；需求恢复等待'),('branch','首次接受时邀约已经过期'),('msg',0,2,'接受邀约(邀约编号)'),('reply',2,0,'拒绝首次接受；无新预约'),('endalt',)
],[89,108,139,206,212],bottom='患者主动查询；不是自动通知。过期恢复等待另走SU-17，不能把到期画成已自动回收。')

# Use-case views — same software boundary, independent use-case goals.
def actor_links(c,x,y,label,targets,side='left'):
 c.actor(x,y,label)
 root=(x+(24 if side=='left' else -24),y+36)
 for tx,ty in targets:c.arrow([root,(tx,ty)])

# S01, carefully separated left/right actor responsibilities.
c=SVG(1050,1100);c.rect(240,20,570,950);c.text(525,54,'ADC软件系统：患者服务与接诊',22,bold=True)
ys={3:138,4:263,5:388,6:513,7:638,8:763,9:888}
for i,lab in [(3,'建立与查阅患者档案'),(4,'创建预约'),(5,'调整预约结果'),(6,'登记实际到诊'),(7,'复核信息与记录实际治疗'),(8,'完成就诊并生成结算单'),(9,'查阅与打印结算单')]:uc(c,505,ys[i],f'SU-{i:02}',lab,195,38)
actor_links(c,88,185,'患者',[(310,ys[i]-8) for i in [4,5,9]])
actor_links(c,88,470,'前台',[(310,ys[i]+8) for i in [3,4,5,6,9]])
actor_links(c,948,535,'负责牙医',[(700,ys[i]) for i in [3,7,8,9]],'right')
actor_links(c,948,815,'财务',[(700,ys[9]+11)],'right')
# Shared kernel in distinct compact note rather than squeezing unreadable tiny oval.
uc(c,520,1014,'SF-01','核验时间与占用',165,32)
c.arrow([(700,263),(779,263),(779,1014),(686,1014)],dash=True)
c.text(768,966,'«include»',16,anchor='end',white=False)
c.note(245,60,555,'实线箭头：主执行者发起。用例之间不表示先后顺序。',16)
done(c,'S01','system-use-case',[138,139,141,150,206,210,212],'业务权限细分仍在规约；SF01是必执行的共享步骤，不是额外用户入口。')
# Fix boundary to include shared use case
# redraw extension border lower automatically via saved source patch below.
p=M/'S01.svg';s=p.read_text().replace('width="570" height="950"','width="570" height="1060"');p.write_text(s);cairosvg.svg2png(bytestring=s.encode(),write_to=str(M/'S01.png'),scale=2.7);cairosvg.svg2pdf(bytestring=s.encode(),write_to=str(M/'S01.pdf'))

# S02 — a large but single, consistently scoped system view.
c=SVG(1050,1210);c.rect(235,20,580,1170);c.text(525,56,'ADC软件系统：协同与经营核对',23,bold=True)
items=[(14,'生成有限排程建议'),(15,'审核并发布限时邀约'),(19,'新增牙医出诊时段'),(12,'查询运营指标'),(17,'回收过期邀约'),(13,'登记或退出候补'),(16,'接受或拒绝候补邀约'),(11,'形成季度成本与利润核对'),(23,'维护标准治疗目录与当前单价'),(10,'申请与审核账单数字更正')]
y2={i:140+j*95 for j,(i,_) in enumerate(items)}
for i,lab in items:uc(c,510,y2[i],f'SU-{i:02}',lab,192,37)
actor_links(c,85,240,'诊所主管',[(318,y2[i]-7) for i in [14,15,19,12,17]])
actor_links(c,85,650,'前台',[(318,y2[i]+8) for i in [17,13,16]])
actor_links(c,85,955,'负责牙医',[(318,y2[10])])
actor_links(c,958,250,'总部管理',[(702,y2[i]-9) for i in [12,11,23]],'right')
actor_links(c,958,570,'患者',[(702,y2[i]) for i in [13,16]],'right')
actor_links(c,958,950,'财务',[(702,y2[i]+9) for i in [11,23,10]],'right')
uc(c,510,1129,'SF-01','核验时间与占用',165,34)
c.arrow([(702,y2[15]),(783,y2[15]),(783,1129),(675,1129)],dash=True);c.text(768,1065,'«include»',16,anchor='end',white=True)
c.text(525,88,'共用用例仍按规约细分写入、只读与代办权限。',17)
done(c,'S02','system-use-case',[138,139,141,206,210,212],'包含关系仅SU15→SF01；SU16的接受分支在规约中复用，拒绝分支不误画include。')

# S03 — role sets explicitly labeled; concrete personal/result roles separate.
c=SVG(1050,1100);c.rect(235,20,580,1010);c.text(525,56,'ADC软件系统：身份、引导与账号安全',22,bold=True)
items=[(1,'登录、选择与切换身份'),(20,'选择显示方式与非聊天帮助'),(22,'修改本人密码'),(2,'选择与切换诊所'),(18,'获取操作引导'),(24,'核对候补是否已转预约'),(21,'维护普通账号与业务授权'),(25,'紧急安全封禁普通账号')]
y3={i:138+j*117 for j,(i,_) in enumerate(items)}
for i,lab in items:uc(c,510,y3[i],f'SU-{i:02}',lab,197,37)
actor_links(c,88,180,'账号使用者\n（角色概括）',[(313,y3[i]) for i in [1,20,22]])
actor_links(c,88,490,'前台',[(313,y3[i]+8) for i in [2,24]])
actor_links(c,88,730,'业务用户\n（角色概括）',[(313,y3[18]+8)])
actor_links(c,950,340,'诊所主管',[(707,y3[2])],'right')
actor_links(c,950,680,'患者',[(707,y3[24])],'right')
actor_links(c,950,905,'技术管理员',[(707,y3[i]) for i in [21,25]],'right')
c.actor(950,475,'外部意图模型\n（可选辅执行者）')
c.arrow([(707,y3[18]),(926,511)])
c.text(796,571,'识别意图',17,white=True)
c.text(525,86,'实线：功能交互；模型服务为辅助，不决定授权或办理结果。',16)
c.note(18,1042,1014,'角色概括仅压缩图面：账号使用者含七类身份；业务用户不含技术身份，均不产生新授权。',16)
done(c,'S03','system-use-case',[138,141,142,150,206,212],'外部模型仅作为SU18的可选辅执行者；角色概括不等于安全角色继承。')

# D01 class view: domain concepts and multiplicities, not database tables.
c=SVG(1050,850)
boxes={
 'patient':(30,30,230,98,'患者','姓名；出生日期'),
 'dentist':(410,30,230,98,'牙医','姓名'),
 'clinic':(790,30,230,98,'诊所','地址；面积'),
 'visit':(390,262,270,104,'就诊','计划时段；实际到诊时间'),
 'wait':(30,420,265,98,'候补请求','可接受时间窗口'),
 'offer':(30,652,265,100,'候补邀约','候选时间；确认期限'),
 'invoice':(775,420,245,98,'结算单','结算单号'),
 'version':(390,652,270,100,'就诊版本','复核结果'),
 'line':(775,652,245,100,'治疗明细','数量；单价快照')}
# edges drawn before nodes, label placements in gutters
for pts in [[(145,128),(445,262)],[(525,128),(525,262)],[(905,128),(605,262)],[(145,128),(145,420)],[(160,518),(160,652)],[(295,702),(334,702),(334,318),(390,318)],[(660,315),(895,420)],[(525,366),(525,652)],[(845,518),(845,561),(600,561),(600,652)],[(660,702),(775,702)]]:c.path(pts)
# multiplicities and relation labels
for x,y,t in [(193,161,'1'),(396,252,'0..*'),(543,155,'1'),(543,246,'0..*'),(845,163,'1'),(661,250,'0..*'),(160,155,'1'),(163,403,'0..*'),(176,545,'1'),(178,634,'0..*'),(305,688,'0..1'),(352,305,'0..1'),(677,330,'1'),(876,407,'0..1'),(543,389,'1'),(543,636,'1..*'),(866,544,'0..1'),(618,636,'1'),(679,687,'1'),(742,687,'0..*')]:c.text(x,y,t,17)
c.text(327,173,'接受服务',18,white=True);c.text(566,205,'负责',18,white=True);c.text(735,169,'发生于',18,white=True)
c.text(163,296,'提出',18,anchor='start',white=False);c.text(177,589,'形成机会',18,anchor='start');c.text(341,474,'接受后关联',18,anchor='start')
c.text(768,354,'结算',18,white=True);c.text(543,472,'保留',18,anchor='start');c.text(720,547,'当前发布版本',18,white=True)
# ownership diamond for version-line only (physical rows aren't used as an excuse)
c.a.append('<polygon points="660,702 671,695 682,702 671,709" fill="#202020"/>')
for x,y,w,h,name,attrs in boxes.values():
 c.rect(x,y,w,h);c.line(x,y+43,x+w,y+43);c.text(x+w/2,y+29,name,24,bold=True);c.text(x+14,y+73,attrs,20,anchor='start')
c.note(22,785,1008,'图示为概念类及关键关联；省略物理主键与状态码。就诊版本组合其治疗明细，不暗示其他关系均为组合。',17)
done(c,'D01','analysis-concept-class',[287,288,291,295,296,305,306],'普通关联以实线与端点多重性；只在版本-明细给出拥有责任明确的组合。')

# M01 wait-request lifecycle; expiry does not automatically restore stored request state.
c=SVG(1050,755);c.text(25,34,'stm 候补请求',24,anchor='start',bold=True)
c.a.append('<circle cx="100" cy="116" r="10" fill="#202020"/>');c.arrow([(110,116),(175,116)],solid=True)
c.rect(175,70,250,90,r=16);c.text(300,107,'等待安排',26);c.text(300,139,'WAITING',19)
c.rect(645,70,250,90,r=16);c.text(770,107,'等待确认',26);c.text(770,139,'OFFERED',19)
c.rect(645,470,250,90,r=16);c.text(770,507,'已转预约',26);c.text(770,539,'BOOKED',19)
c.rect(175,470,250,90,r=16);c.text(300,507,'已退出',26);c.text(300,539,'WITHDRAWN',19)
c.arrow([(425,111),(645,111)],solid=True);c.text(535,42,'发布邀约[核验通过]\n/ 建立限时保留',19)
c.arrow([(700,160),(700,237),(372,237),(372,160)],solid=True);c.text(527,211,'拒绝邀约[尚有效] / 释放保留',18,white=True)
c.arrow([(839,160),(839,303),(235,303),(235,160)],solid=True);c.text(527,280,'回收过期邀约[已到期] / 标记过期并恢复等待',18,white=True)
c.arrow([(895,137),(981,137),(981,513),(895,513)],solid=True);c.text(974,354,'接受邀约\n[尚有效且核验通过]\n/ 建立关联预约',18,anchor='end')
c.arrow([(255,160),(255,470)],solid=True);c.text(152,375,'退出候补\n/ 保留历史',19,white=True)
c.arrow([(645,142),(606,142),(606,420),(355,420),(355,470)],solid=True);c.text(533,398,'退出候补 / 撤回未接受邀约',18,white=True)
c.note(25,603,1000,'状态所属对象是“候补请求”，不是整个办理流程。\n邀约到期先改变其有效性；没有执行SU-17前，请求可能仍存为OFFERED。\n已转预约后的取消改变“就诊”，不删除候补历史；新候补是另一个对象。',19)
done(c,'M01','state-machine',[339,340,341,345,350,351],'迁移采用事件[警戒]/动作；保留历史状态，不将已转预约画成被销毁的终节点。')

# A01 package responsibility view using dependency dashed arrows, not sequence.
c=SVG(1050,565);c.text(25,34,'pkg 模块责任视图',23,anchor='start',bold=True)
for x,y,w,h,title,desc in [(35,95,265,127,'guidance / assistants','说明与受限结果查询'),(390,95,300,127,'coordination / scheduling','候补、预约与占用'),(780,95,230,127,'care / finance','治疗与结算'),(215,375,310,123,'accounts / workspaces','账号、身份与范围'),(645,375,330,123,'operations / 查询层','授权指标与事实查询')]:
 c.rect(x,y,w,h);c.rect(x,y-23,min(w-20,200),23);c.text(x+w/2,y+40,title,20);c.text(x+w/2,y+82,desc,20)
c.arrow([(300,158),(390,158)],dash=True);c.text(344,139,'受限查询',15,white=True)
c.arrow([(690,158),(780,158)],dash=True);c.text(735,139,'业务关联',15,white=True)
c.arrow([(165,222),(300,375)],dash=True);c.arrow([(516,222),(465,375)],dash=True)
c.arrow([(886,222),(495,375)],dash=True);c.text(522,315,'使用身份与范围合同',18,white=True)
c.arrow([(810,375),(886,222)],dash=True);c.text(902,293,'事实读取',16,white=True)
c.note(25,509,1000,'代表性依赖（使用方 → 被依赖方），并非源代码全部导入，也不表示办理顺序。',17)
done(c,'A01','package-responsibility-view',[295,314,389,395],'限定为设计层责任视图；不冒称完整软件组件图或实现自动生成。')

# X03 one primary actor and one boundary class for that actor, per lecture.
seq('X03',[('患者','actor'),('患者接口','boundary'),('核对候补结果控制','control'),('工作上下文','entity'),('候补请求','entity'),('就诊','entity')],[
 ('msg',0,1,'核对候补结果(所选请求)'),('msg',1,2,'核对结果(主体、请求)'),('msg',2,3,'校验工作上下文()'),('msg',2,4,'核对转换结果(读取时点)'),('self',4,'核验相关邀约\n及准确关联()'),('msg',4,5,'判定当前安排(关联预约)'),('reply',5,4,'当前安排结论'),('reply',4,2,'历史转换与当前安排摘要'),('msg',2,3,'复核当前授权()'),('reply',2,1,'结论与操作入口'),('reply',1,0,'核对结果、时点与下一步')
],[287,314,316,318,320],kind='analysis',bottom='分析责任分配：不是逐行代码调用或多次SQL查询。前台路径换用前台接口，并核验本店范围。')

# A02 account state view distinguishes credentials and enabled flag without claiming account deletion.
c=SVG(1050,640);c.text(25,34,'stm 受控普通账号（安全访问维度）',24,anchor='start',bold=True)
for x,y,label,sub in [(55,103,'可登录','启用且凭据可用'),(727,103,'已安全封禁','停用且原凭据不可用'),(727,390,'已重置待启用','停用且新凭据可用')]:
 c.rect(x,y,267,93,r=17);c.text(x+133.5,y+38,label,25);c.text(x+133.5,y+72,sub,19)
c.arrow([(322,148),(727,148)],solid=True);c.text(525,94,'紧急封禁[授权、确认和依据有效]\n/ 停用、失效原凭据及旧上下文',19)
c.arrow([(860,196),(860,390)],solid=True);c.text(655,285,'重置密码[重新核验通过]\n/ 保存新凭据，保持停用',18,anchor='middle',white=True)
c.arrow([(727,438),(191,438),(191,196)],solid=True);c.text(472,414,'明确启用[复核通过且新凭据可用]\n/ 恢复新登录，旧会话不复活',19,white=True)
c.note(24,533,1001,'本图只刻画账号的访问维度；不表示预约、接诊或账单被取消。\n正常业务退役仍需单独交接；“封禁 → 重置 → 启用”各次操作均独立确认与审计。',18)
done(c,'A02','state-machine',[340,341,342,350],'由启用标记和凭据共同决定状态，恢复是分阶段操作，不混成一次必然成功的消息链。')
(M/'inventory.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2))
print('Rendered',len(inventory),'models')
