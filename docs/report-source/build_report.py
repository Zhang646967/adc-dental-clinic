"""Rebuild the current course report using retained model/specification source.

The frozen RC1 file is never modified. Supplied PDF format is recorded by digest.
Run with python-docx in an explicitly selected document runtime; PDF export is
separate. --folder supplies editable report_source.json and optional toc_pages.json.
"""
from pathlib import Path
from copy import deepcopy
import argparse,hashlib,json,re,os
from docx import Document
from docx.shared import Cm,Pt,RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH,WD_BREAK
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_TABLE_ALIGNMENT,WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

SERIF='Noto Serif CJK SC';SANS='Noto Sans CJK SC';LATIN='Liberation Serif'

def font(run,size=12,bold=None,family=SERIF):
 run.font.name=LATIN;run.font.size=Pt(size);run.font.color.rgb=RGBColor(0,0,0)
 if bold is not None:run.bold=bold
 pr=run._element.get_or_add_rPr();f=pr.find(qn('w:rFonts'))
 if f is None:f=OxmlElement('w:rFonts');pr.insert(0,f)
 for key,val in [('eastAsia',family),('ascii',LATIN),('hAnsi',LATIN)]:f.set(qn('w:'+key),val)
 for key in ('position','vertAlign'):
  for old in list(pr.findall(qn('w:'+key))):pr.remove(old)

def style(st,size,bold=False,family=SERIF):
 st.font.name=LATIN;st.font.size=Pt(size);st.font.bold=bold;st.font.color.rgb=RGBColor(0,0,0)
 pr=st.element.get_or_add_rPr();f=pr.find(qn('w:rFonts'))
 if f is None:f=OxmlElement('w:rFonts');pr.insert(0,f)
 for key,val in [('eastAsia',family),('ascii',LATIN),('hAnsi',LATIN)]:f.set(qn('w:'+key),val)


def build(folder,repo,output=None):
 output=output or repo/'课程报告';output.mkdir(parents=True,exist_ok=True)
 source=json.loads((folder/'report_source.json').read_text());base=repo/'docs/release_report/Report_R5_RC1.docx'
 assert hashlib.sha256(base.read_bytes()).hexdigest()==source['frozen_docx_sha256']
 D=Document(base);paras=list(D.paragraphs);children=list(D._element.body);positions={id(p._p):children.index(p._p) for p in paras}
 def frozen(a,b):return [deepcopy(x) for x in children[positions[id(paras[a]._p)]:positions[id(paras[b]._p)]] if x.tag!=qn('w:sectPr')]
 legacy={key:frozen(a,b) for key,a,b in [('business',50,86),('system',86,118),('design',118,164),('screens',178,185)]}
 old_goal=deepcopy(D.tables[0]._tbl);old_roles=deepcopy(D.tables[1]._tbl);old_assumptions=deepcopy(D.tables[2]._tbl)
 # The current application has separate HQ and finance workspaces.
 from docx.table import Table
 role_view=Table(old_roles,D._body)
 for row in list(role_view.rows):
  if '总部' in row.cells[0].text and '财务' in row.cells[0].text:
   copy_row=deepcopy(row._tr);row._tr.addnext(copy_row)
   for cell,value in zip(row.cells,['总部','全链汇总、季度核对与设备查阅','只读汇总；不代办财务写入或审核']):cell.text=value
   finance_row=next(r for r in Table(old_roles,D._body).rows if r._tr is copy_row)
   for cell,value in zip(finance_row.cells,['财务','渠道账户、成本、资金及匹配复核','经授权办理；不同账号独立复核']):cell.text=value
 for row in Table(old_roles,D._body).rows:
  if row.cells[0].text.strip()=='诊所主管':
   row.cells[1].text='资源规则、维修协调、独立复核与本店经营汇总'
   row.cells[2].text='当前店汇总及独立复核；日常排班由前台办理'
  if row.cells[0].text.strip()=='前台':
   row.cells[1].text='电话接待、患者档案、日周排班、出诊维护、候补发布、调班联系与到诊'
   row.cells[2].text='仅当前店；保护原承诺，不审核治疗、资产验收或资金'
 old_refs=[p.text for p in paras[197:212]]
 uc=[]
 for a,p in enumerate(paras):
  if p.style.name=='Heading 3' and re.match(r'(SU-\d+|SF-01)',p.text):
   b=next((j for j in range(a+1,len(paras)) if paras[j].style.name.startswith('Heading') and paras[j].text.strip()),len(paras))
   uc.append((p.text,[x.text for x in paras[a+1:b] if x.text.strip()]))
 for child in list(D._element.body):
  if child.tag!=qn('w:sectPr'):D._element.body.remove(child)
 # Retained drawings keep their actual package relationships; section furniture is rebuilt.
 sec=D.sections[0];sec.page_width=Cm(21);sec.page_height=Cm(29.7)
 sec.left_margin=Cm(3);sec.right_margin=Cm(2);sec.top_margin=Cm(2.5);sec.bottom_margin=Cm(2.3)
 sec.header_distance=Cm(1.3);sec.footer_distance=Cm(1.2)
 for name,size,bold,family in [('Normal',12,False,SERIF),('Title',22,True,SERIF),('Subtitle',14,False,SERIF),('Heading 1',16,True,SANS),('Heading 2',14,True,SANS),('Heading 3',12,True,SANS),('Caption',10.5,False,SERIF)]:style(D.styles[name],size,bold,family)
 for st in D.styles:
  for rule in list(st.element.iter(qn('w:pBdr'))):rule.getparent().remove(rule)
 normal=D.styles['Normal'].paragraph_format;normal.line_spacing=Pt(22);normal.space_after=Pt(0);normal.space_before=Pt(0);normal.first_line_indent=Pt(24);normal.widow_control=True
 for name in ('Heading 1','Heading 2','Heading 3'):
  pf=D.styles[name].paragraph_format;pf.first_line_indent=Pt(0);pf.line_spacing=1.25;pf.space_before=Pt(12);pf.space_after=Pt(8);pf.keep_with_next=True;pf.page_break_before=False
 D.styles['Heading 1'].paragraph_format.alignment=WD_ALIGN_PARAGRAPH.CENTER
 D.styles['Caption'].paragraph_format.first_line_indent=Pt(0)
 D.core_properties.title=source['title'];D.core_properties.subject=source['version'];D.core_properties.author=source['author']['name'];D.core_properties.keywords='系统分析与设计 预约业务 患者服务 财务 设备 用例规约'
 next_page=[False]
 toc=[];markdown=['# '+source['title'],'',source['version']+' '+source['date'],'']
 def p(text='',size=12,bold=False,center=False,indent=True,space=0):
  x=D.add_paragraph();font(x.add_run(text),size,bold)
  lang=OxmlElement('w:lang');lang.set(qn('w:val'),'en-US');lang.set(qn('w:eastAsia'),'en-US');x.runs[0]._element.get_or_add_rPr().append(lang)
  x.paragraph_format.space_after=Pt(space)
  if not text and size==1:x.paragraph_format.line_spacing=Pt(1);x.paragraph_format.space_before=Pt(0);x.paragraph_format.space_after=Pt(0)
  if size>18:x.paragraph_format.line_spacing=1.15
  if not indent:x.paragraph_format.first_line_indent=Pt(0)
  if re.match(r'^表[A-Za-z]?[0-9]+-[0-9]+',text):x.paragraph_format.keep_with_next=True
  if center:x.alignment=WD_ALIGN_PARAGRAPH.CENTER;x.paragraph_format.first_line_indent=Pt(0)
  markdown.extend([text,'']);return x
 def heading(text,level=2,add_toc=True):
  x=D.add_heading(text,level)
  if next_page[0]:x.paragraph_format.page_break_before=True;next_page[0]=False
  font(x.runs[0],{1:16,2:14,3:12}[level],True,SANS)
  if add_toc and level<3:toc.append((text,level))
  markdown.extend(['#'*(level+1)+' '+text,'']);return x
 def table(headers,rows,widths=None,case_label=None):
  if headers[0]=='标题':
   # Preserve every character, while giving long fields explicit continuation rows.
   bounded=[]
   for label,value in rows:
    chunks=[];remaining=str(value)
    while len(remaining)>900:
     stop=remaining.rfind('\n',0,900)
     if stop<450:stop=remaining.rfind('。',0,900)
     take=stop+1 if stop>=450 else 900
     chunks.append(remaining[:take]);remaining=remaining[take:]
    chunks.append(remaining);assert ''.join(chunks)==str(value)
    for n,chunk in enumerate(chunks):bounded.append([label if n==0 else label+'（续'+str(n)+'）',chunk])
   rows=bounded
  if headers[0]=='标题':
   case=rows[0][1];number=int(case[3:5]) if case.startswith('SU-') else 26;label=case_label or ('A' if case.startswith('SF-') or number<=25 else 'B');ordinal=number if label=='A' else number-(38 if label=='C' else 25)
   cap=p('表'+label+'-'+str(ordinal)+' '+case+'用例规约',10.5,False,True);cap.paragraph_format.keep_with_next=True
  widths=widths or [3.2,12.8];t=D.add_table(rows=1,cols=len(headers));t.alignment=WD_TABLE_ALIGNMENT.CENTER;t.autofit=False
  for col,w in zip(t.columns,widths):col.width=Cm(w)
  for i,values in enumerate([headers,*rows]):
   row=t.rows[0] if i==0 else t.add_row();pr=row._tr.get_or_add_trPr();pr.append(OxmlElement('w:cantSplit'))
   if i==0:pr.append(OxmlElement('w:tblHeader'))
   for j,(c,text) in enumerate(zip(row.cells,values)):
    c.width=Cm(widths[j]);c.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    cp=c._tc.get_or_add_tcPr();borders=OxmlElement('w:tcBorders')
    for edge in ('top','bottom','left','right'):
     e=OxmlElement('w:'+edge)
     for key,val in [('val','single'),('sz','4'),('color','D9D9D9')]:e.set(qn('w:'+key),val)
     borders.append(e)
    cp.append(borders);m=OxmlElement('w:tcMar')
    for edge in ('top','bottom','left','right'):
     e=OxmlElement('w:'+edge);e.set(qn('w:w'),'85' if edge in ('top','bottom') else '95');e.set(qn('w:type'),'dxa');m.append(e)
    cp.append(m)
    if i==0:s=OxmlElement('w:shd');s.set(qn('w:fill'),'F2F2F2');cp.append(s)
    pp=c.paragraphs[0];pp.paragraph_format.first_line_indent=Pt(0);pp.paragraph_format.line_spacing=Pt(15.5);pp.paragraph_format.space_after=Pt(0)
    # The long patient-replacement case spans pages; its field rows must flow.
    pp.paragraph_format.keep_with_next=(i < len(rows) if case_label=='C' and not case.startswith('SU-40') else i==0)
    run=pp.add_run(str(text));font(run,10.5,i==0)
    lang=OxmlElement('w:lang');lang.set(qn('w:val'),'en-US');lang.set(qn('w:eastAsia'),'en-US');run._element.get_or_add_rPr().append(lang)
  p('',size=1,indent=False)
  markdown.extend(['| '+' | '.join(headers)+' |','| '+' | '.join('---' for _ in headers)+' |'])
  markdown.extend('| '+' | '.join(str(v).replace('\n',' / ').replace('|','/') for v in row)+' |' for row in rows);markdown.append('')
  return t
 def add(spec):
  heading(spec['heading'])
  for text in spec.get('paragraphs',[]):p(text)
  if spec.get('table'):
   v=spec['table'];label={'3.8':'表3-7 财务与设备补充需求','3.9':'表3-8 通知进度与监测需求','5.4':'表5-1 分层测试与执行结果','5.6':'表5-2 需求至验收追踪','5.7':'表5-3 页面调研与落实','5.8':'表5-4 业务体验问题与可验证行为','6.2':'表6-1 后续工作与验收门槛'}.get(spec['heading'][:3],spec['heading'])
   p(spec.get('caption') or label,10.5,False,True);table(v['headers'],v['rows'],v['widths'])
 def figure(path,caption,width=16,max_height=None):
  if not path.exists():raise FileNotFoundError(path)
  if max_height is not None:
   from PIL import Image
   with Image.open(path) as im:width=min(width,max_height*im.width/im.height)
  x=D.add_paragraph();x.paragraph_format.first_line_indent=Pt(0);x.alignment=WD_ALIGN_PARAGRAPH.CENTER;x.paragraph_format.keep_with_next=True;x.paragraph_format.line_spacing=1.0
  x.add_run().add_picture(str(path),width=Cm(width));p(caption,10.5,False,True);markdown.extend(['!['+caption+']('+Path(os.path.relpath(path,folder)).as_posix()+')',''])
 def mind(n):p('思维导图  '+source['mind_maps'][str(n)],size=10.5,indent=False,space=6)
 def page():next_page[0]=True
 def furniture(section,front=False):
  section.header.is_linked_to_previous=False;section.footer.is_linked_to_previous=False
  section.different_first_page_header_footer=False
  hp=section.header.paragraphs[0];hp.clear();hp.paragraph_format.first_line_indent=Pt(0);hp.paragraph_format.tab_stops.clear_all();hp.paragraph_format.tab_stops.add_tab_stop(Cm(16),WD_ALIGN_PARAGRAPH.RIGHT)
  font(hp.add_run('中南大学 · 系统分析与设计\tADC 牙科连锁运营管理系统'),9)
  pr=hp._p.get_or_add_pPr();border=OxmlElement('w:pBdr');bottom=OxmlElement('w:bottom');bottom.set(qn('w:val'),'single');bottom.set(qn('w:sz'),'4');bottom.set(qn('w:space'),'6');border.append(bottom);pr.append(border)
  fp=section.footer.paragraphs[0];fp.clear();fp.alignment=WD_ALIGN_PARAGRAPH.CENTER;fp.paragraph_format.first_line_indent=Pt(0)
  if not front:font(fp.add_run('第 '),9)
  field=OxmlElement('w:fldSimple');field.set(qn('w:instr'),'PAGE');fp._p.append(field)
  if not front:font(fp.add_run(' 页'),9)
  sn=section._sectPr.find(qn('w:pgNumType'))
  if sn is None:sn=OxmlElement('w:pgNumType');section._sectPr.append(sn)
  sn.set(qn('w:start'),'1');sn.set(qn('w:fmt'),'upperRoman' if front else 'decimal')
 def fix_legacy(text):
  text=text.replace('第3.7节','第3.5.5节')
  text=re.sub(r'图2-(\d+)',lambda m:'图3-'+str({3:4,4:3}.get(int(m[1]),int(m[1]))),text)
  if text.startswith('系统边界为ADC软件。'):return '系统边界为ADC软件。患者、前台、牙医和财务等作为执行者分别达成目标，每次工作上下文只激活一个身份。实线箭头表示功能交互，include表示共享核验，不表示业务的时间先后。'
  text=text.replace('（本增量）','').replace('真实HTTP/PG验证待执行。','实现范围及业务测试见第5章。').replace('真实HTTP/PG与两连接竞争待执行。','实现范围及业务测试见第5章。')
  text=text.replace('RC共享通知规则','通知协作规则').replace('本轮不提供','本功能不提供').replace('本轮修改','该变更')
  text=text.replace('R4.2的','既有的').replace('保留R4.2的','说明').replace('当前候选','系统').replace('原RC','系统')
  text=text.replace('唯一身份直达为候选修订，待本地回归','按规则核验唯一有效身份').replace('已有候选实现；具体人工观察及验证边界见第5章','实现范围与业务测试见第5章')
  text=text.replace('仍需真实登录与数据库回归','身份与数据库约束须经测试验证').replace('须在真实数据库验收','由数据库和业务测试验证')
  text=text.replace('本图重建案例中的业务问题情境，而不是把v0.3软件当作现状系统。','本图根据案例描述重建现状业务情境。')
  if text.startswith('患者候补仍为固定30分钟'):
   return '未启用资源控制的历史模式保留固定30分钟、有限候选最大匹配；已启用资源控制的诊所按服务时长、登记先后、可行时间和稳定资源顺序生成建议，不保证全局最优。患者短信、邮件和自动确认不在本阶段范围。邀约仍保留至发布后15分钟或预约开始的较早时点。'
  if text.startswith('开发中曾发现只读模式'):
   return '只读模式按业务副作用控制写入，允许经过授权的结果核对。查询仍需有效身份、诊所和对象范围；读取结果只表示当前时点，不构成后续预约的占用承诺。'
  if text.startswith('本图保留'):
   text=text.replace('本图保留既有的','本图表达')
  if text.startswith('发布门槛：'):
   return '质量评价覆盖核心业务完整性、权限、重复提交、回滚及历史金额。公开服务和更大规模需要独立验证，不能仅凭模型或功能数量作出结论。'
  text=text.replace('主管发布后形成有限期的保留','前台发布后形成有限期的保留').replace('主管先明确暂停新增，前台协商并通过原业务流程处理','前台先明确暂停新增，再协商并通过原业务流程处理')
  text=text.replace('本轮再统一全角色只读提示及表单错误定位','界面统一提示当前只读状态并定位表单错误')
  return text
 def append_nodes(nodes,mapping=None,system=False,design=False):
  from docx.text.paragraph import Paragraph
  from docx.table import Table
  for node in nodes:
   for pr in node.xpath('.//w:sectPr'):pr.getparent().remove(pr)
   if node.tag==qn('w:p'):
    x=Paragraph(node,D._body);text=x.text
    if not text.strip() and not node.xpath('.//w:drawing'):continue
    if x.style.name.startswith('Heading'):
     if mapping is None or text not in mapping:continue
     value,level=mapping[text];x.clear();font(x.add_run(value),{1:16,2:14,3:12}[level],True,SANS);x.style=D.styles['Heading '+str(level)]
     if level<3:toc.append((value,level))
     markdown.extend(['#'*(level+1)+' '+value,''])
    elif not node.xpath('.//w:drawing'):
     if design:text=re.sub(r'图4-(\d+)',lambda m:'图4-'+str(1 if int(m[1])==1 else int(m[1])+5),text)
     if system:text=re.sub(r'图3-(\d+)',lambda m:'图3-'+str(int(m[1])+7),text)
     text=fix_legacy(text)
     text=re.sub(r'表3-(\d+)',lambda m:'表3-'+str(int(m[1])+4),text)
     text=text.replace('表2-1','表3-1')
     if text.strip():
      x.clear();font(x.add_run(text),10.5 if x.style.name=='Caption' else 12)
      markdown.extend([text,''])
    pf=x.paragraph_format
    if x.style.name=='Normal':pf.line_spacing=Pt(22);pf.keep_with_next=False
    pf.page_break_before=False;pf.space_before=Pt(0);pf.space_after=Pt(5) if x.style.name=='Caption' else Pt(0)
    if node.xpath('.//w:drawing'):
     current_models=folder/'scheduling-models'
     old_models=repo/'docs/release_report/models'
     substitutions={hashlib.sha256((old_models/(key+'.png')).read_bytes()).hexdigest():current_models/(key+'.png') for key in ('S02','S04','S05','B06','B07')}
     for blip in node.xpath('.//a:blip'):
      rid=blip.get(qn('r:embed'));part=D.part.related_parts.get(rid)
      target=substitutions.get(hashlib.sha256(part.blob).hexdigest()) if part else None
      if target:
       new_rid,image=D.part.get_or_add_image(str(target));blip.set(qn('r:embed'),new_rid)
       from PIL import Image
       with Image.open(target) as im:width=min(16,18*im.width/im.height);height=width*im.height/im.width
       for e in node.xpath('.//wp:extent')+node.xpath('.//a:xfrm/a:ext'):
        e.set('cx',str(int(Cm(width))));e.set('cy',str(int(Cm(height))))
     pf.first_line_indent=Pt(0);pf.keep_with_next=True;pf.line_spacing=1.0
     for extent in node.xpath('.//wp:extent'):
      cx,cy=int(extent.get('cx')),int(extent.get('cy'));ratio=min(1,Cm(16)/cx,Cm(18)/cy)
      extent.set('cx',str(int(cx*ratio)));extent.set('cy',str(int(cy*ratio)))
    elif x.style.name=='Caption':pf.keep_with_next=True;pf.first_line_indent=Pt(0);x.alignment=WD_ALIGN_PARAGRAPH.CENTER
    if re.match(r'^表[0-9]+-[0-9]+',x.text):pf.keep_with_next=True
   elif node.tag==qn('w:tbl'):
    t=Table(node,D._body)
    if t.rows[0].cells[0].text=='路径':p('表4-4 RC运行路径与数据保护',10.5,False,True)
    if len(t.columns)==3 and t.rows[0].cells[0].text=='配置环节':
     for cell,value in zip(t.rows[0].cells,['配置环节','现有实现','本地证据与剩余门槛']):cell.text=value
     updates={
      '环境契约':('显式阶段、目标域名和密钥契约；运行与迁移账号分开；本地数据库仅私网。','本地运行权限已有回归；实际云凭据、TLS和网络边界另验收。'),
      'HTTP服务':('非root应用、Gunicorn、Nginx和静态入口；独立HTTPS部署准备。','Mac本地启动与入口已验证；目标证书、续期及真实公网HTTPS待验收。'),
      '应用安全':('分环境关闭DEBUG、Cookie和CSRF设置、HTTPS与只读策略。','本地认证、权限和并发已回归；目标域名与完整ASVS评估仍待完成。'),
      '资源与审计':('入口限速、安全运行日志、通知心跳及私有条件监测。','R2.1限流/日志保留历史证据，R2.2有新监测验收；外部响应与主机事件待完成。'),
      '隔离验证':('compose.verify独立项目、临时数据库和合成凭据，无端口暴露。','准确提交的真实Docker完整回归与CI通过；不复用原业务卷。'),
      '升级与恢复':('保留原迁移；加密备份、独立空库恢复及原Mac保护。','合成数据恢复与金额/登录已验证；Windows原数据库未取得，恢复未完成。')}
     for row in t.rows[1:]:
      values=updates.get(row.cells[0].text)
      if values:
       row.cells[1].text=values[0];row.cells[2].text=values[1]
    for row_no,row in enumerate(t.rows):
     if row.cells[0].text.strip()=='NFR-06' and len(row.cells)==3:
      row.cells[1].text='性能目标与已测能力分开；预约、接诊及财务办理分别测量，复杂分析与导出另行记录。'
      row.cells[2].text='以可重复的预约、接诊和财务工作负载测量正常请求p95及失败率；五店已测，二十店规模仍需业务代表性验证（第5、6章）。'
     row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
     for cell in row.cells:
      for pp in cell.paragraphs:
       pp.paragraph_format.keep_with_next=(row_no==0)
       pp.paragraph_format.first_line_indent=Pt(0);pp.paragraph_format.line_spacing=Pt(15.5)
       for r in pp.runs:font(r,10.5)
    markdown.append('| '+' | '.join(c.text.replace('\n',' / ') for c in t.rows[0].cells)+' |');markdown.append('| '+' | '.join('---' for _ in t.rows[0].cells)+' |')
    markdown.extend(['| '+' | '.join(c.text.replace('\n',' / ') for c in row.cells)+' |' for row in t.rows[1:]]);markdown.append('')
   D._element.body.insert(len(D._element.body)-1,node)
 # Cover follows the supplied university page, without headers or page numbers.
 for container in (sec.header,sec.footer,sec.first_page_header,sec.first_page_footer):
  for x in container.paragraphs:x.clear()
 sec.different_first_page_header_footer=True
 p('',space=18);p('中 南 大 学',26,True,True,space=5);p('CENTRAL SOUTH UNIVERSITY',14,False,True,space=34)
 p('系统分析与设计',24,True,True,space=8);p('课 程 项 目 报 告',24,True,True,space=7);p('SYSTEMS ANALYSIS AND DESIGN REPORT',12,False,True,space=26)
 topic=p('题　目  '+source['title'],16,True,True,space=12);topic.style=D.styles['Title'];topic.paragraph_format.first_line_indent=Pt(0)
 a=source['author']
 for label,value in [('学生姓名',a['name']),('学　　号',a['student_no']),('指导教师',a['supervisor']),('学　　院',a['school']),('专业班级',a['class'])]:
  x=p(label+'  '+value,14,False,False,False,space=8);x.paragraph_format.left_indent=Cm(3.2)
 p('',11,False,True,space=12);p(source['date'],14,False,True)
 front=D.add_section(WD_SECTION_START.NEW_PAGE);furniture(front,True)
 heading(source['title'],1,False);heading('摘　要',1,False)
 for text in source['abstract_cn']:p(text)
 p('关键词  系统分析与设计；连锁诊所；预约流程；患者服务；财务管理；设备维护',10.5,True,False,False)
 page();heading('Analysis and Design of the ADC Dental Chain Operations Management System',1,False);heading('ABSTRACT',1,False)
 for text in source['abstract_en']:
  x=p(text)
  # English uses word boundaries rather than inherited CJK character breaks.
  for run in x.runs:
   lang=OxmlElement('w:lang');lang.set(qn('w:val'),'en-US');lang.set(qn('w:eastAsia'),'en-US');run._element.get_or_add_rPr().append(lang)
 p('Key words  systems analysis and design; dental chain; appointments; patient service; finance; equipment maintenance',10.5,False,False,False)
 page();heading('目　录',1,False);toc_anchor=D.add_paragraph()
 main=D.add_section(WD_SECTION_START.NEW_PAGE);furniture(main)
 heading('第1章 绪论',1)
 for item in source['introduction']:add(item)
 p('表1-1 项目目标与可观察结果',10.5,False,True);append_nodes([old_goal])
 mind(1)
 page();heading('第2章 相关方法与技术',1)
 for item in source['methods']:add(item)
 mind(2)
 page();heading('第3章 系统需求分析',1)
 heading('3.1 业务范围与现状分析')
 business_map={'2.1　业务边界与业务用例':('3.1.1 业务边界与业务用例',3),'2.2　现状业务序列：就诊服务':('3.1.2 现状就诊服务',3),'2.4　现状业务序列：季度核对':('3.1.3 现状季度核对',3)}
 append_nodes(frozen(51,62),business_map);append_nodes(frozen(67,72),business_map)
 heading('3.2 系统总体目标与改进业务流程')
 mapping={'2.3　改进后的业务序列：统一服务':('3.2.1 统一服务',3),'2.5　改进后的业务序列：季度核对':('3.2.2 季度核对',3),'2.6　改进后的业务序列：候补协同':('3.2.3 候补协同',3),'2.7　改进后的业务序列：责任协调':('3.2.4 责任协调',3)}
 append_nodes(frozen(62,67),mapping);append_nodes(frozen(72,86),mapping)
 heading('3.3 用户需求分析');p('七类工作台按当前身份及对象范围授权。一个人可以有多个授予的岗位，但一次只激活一个；切换身份不能自行审核。技术管理负责普通账号和基础目录，不因维护职责取得患者病历或财务审核权。');p('表3-2 利益相关者及职责边界',10.5,False,True);append_nodes([old_roles])
 heading('3.4 需求清单与优先级');p('表3-3 需求模块与业务结果',10.5,False,True);table(['模块','优先目标','受保护业务结果'],[['患者与临床','关键','稳定编号、到诊、过敏复核、实际治疗、明确结束。'],['财务与设备','关键','版本化账单、真实资金及凭据、独立复核、费用来源。'],['预约与服务','关键','患者明确确认，电话接待有责任，资源核对有依据，取消改期可解释。'],['排班与协调','重要','既有承诺保留、明确受理与复核、消息不代替业务事实。'],['经营与保障','重要','时段指标带分母与缺失，服务中断可识别，业务记录可恢复。']], [3,2.2,10.8])
 heading('3.5 系统用例分析')
 mapping={'3.1　系统边界与参与者':('3.5.1 患者服务与接诊用例',3),'3.2　协同与管理需求':('3.5.2 候补 财务与运营用例',3),'3.3　身份、引导与安全管理需求':('3.5.3 身份 引导与安全用例',3),'3.6　资料与出诊维护扩展需求':('3.5.4 资料与出诊维护用例',3),'3.7　协同任务与通知需求':('3.5.5 责任协调与通知用例',3)}
 append_nodes(frozen(87,100),mapping,True);append_nodes(frozen(110,118),mapping,True)
 heading('3.6 用例清单与业务完整性');p('系统共定义96项编号业务用例和1项共享核验。附录A为SU-01—25及SF-01，附录B为SU-26—38，附录C为SU-39—96。电话接待关注咨询与联系，SU-04关注正式成约；网站和原生微信小程序是预约、候补及改期的渠道路径，不按页面数量重复计数。')
 p('表3-4 用例分组及业务目标',10.5,False,True)
 table(['业务范围','编号','使用者目标'],[
 ['身份与资料','SU-01—03、21—23、25—28、64—67、83—86','账号、患者资料、基础目录、专业审核与限定转诊。'],
 ['医保结算与基金清算','SU-91—96','原费用分担、银行分配、差额跟进和撤销分别核对。'],
 ['连续诊疗','SU-68—80','自述检查、方案决定、实际执行、复诊与加工件验收。'],
 ['医保资料','SU-87—90','来源目录、门店安排、收费适配及患者待遇分别核对。'],
 ['预约与接诊','SU-04—10、19、29—33\nSU-39—40、54、57—63','预约、变更、到诊、治疗、结算与资源核对。'],
 ['候补与协作','SU-13—17、24、31、34—38','候补、邀约、任务办理、独立复核及消息。'],
 ['经营与引导','SU-11—12、18、20、41、55—56、81—82','成本利润、取消分析和操作协助。'],
 ['资金与对账','SU-42—49、53','渠道、收退款、凭据、流水、对账及日结。'],
 ['设备维护','SU-50—52','资产、维修责任和独立验收。']
 ],[3.1,5.8,7.1])
 p('分组交叉列出的协作用例只计一次。每项规约说明触发、前置、交互、替代路径、成功结果、最低保证和验收目标；待实现设计在规约和第5章明确标注。')
 heading('3.7 业务规则与非功能性需求');append_nodes(frozen(100,110),{},True)
 for item in source['requirements']:
  add(item)
  if item['heading'].startswith('3.8'):
   figure(folder/'appointment-sequence.png','图3-13 电话预约接待与最终确认的业务序列',16)
   p('接待、完整建档、服务及资源核验、明确同意与最终成约分别办理。图中查询候选不是占用；同意后仍须重检资源，接待与成约结果一并关联。',10.5)
   figure(folder/'scheduling-models/B14.png','图3-14 患者自助改期与候补替换的业务序列',16)
   p('患者选择与明确确认分开；原预约在确认成功前保留。统一资源核验、唯一后继、确认回执及必要的邀约接受在同一事务保存。真正取消仍通过原取消及原因跟进流程办理。',10.5)
 mind(3)
 page();heading('第4章 系统设计',1)
 heading('4.1 领域关系与状态模型')
 p('领域关系分为诊疗结算、接待成约及资源占用三个主要视图，状态模型分别说明就诊、接待及资源协调。端点数字为关联多重性；图中为主要业务对象，不穷举全部数据表。咨询、资源占用、实际治疗与资金分别记录。')
 figure(repo/'docs/diagrams/domain_care.png','图4-1 诊疗与结算的核心领域关系',16)
 p('一个患者可有多次就诊，每次由一个出诊时段覆盖；就诊保留诊所与医师引用并核对一致。每次就诊可形成多个记录版本，每版包含实际治疗；同次就诊至多一个逻辑结算单，指向当前发布版本。更正保留原版、拟更正版及独立依据。')
 figure(repo/'docs/diagrams/domain_reception.png','图4-2 电话接待与唯一成约的领域关系',16)
 p('接待单属于一个诊所，咨询阶段可以没有患者关联；成约前须完成建档。每次沟通只追加，责任与期限可追溯。接待可以直接成约或转候补；候补接受后关联同一成功预约。接待的已成约事实不因后续取消或改期而改写。')
 figure(repo/'docs/diagrams/domain_resources.png','图4-3 服务配置与资源占用的领域关系',16)
 p('设备资产通过排程位置确定固定诊室或本店共享；牙椅不重复建账。预约服务定义时长、医师及必要设备，资源方案保留当时快照，整段占用通过明细约束。来源框是预约与邀约的业务引用组合，不是新增来源表；接受邀约时原方案关联同一预约，替换时追加新版本。')
 figure(repo/'docs/diagrams/visit_state.png','图4-4 预约与就诊状态及业务守卫',16)
 p('箭头采用事件、条件及业务动作表达。到诊后才能完成治疗或无治疗关闭；取消、爽约和改期各有依据。改期在同一事务保留原终态并创建唯一后继；治疗后的更正通过版本和独立申请办理，不倒退就诊状态。')
 figure(repo/'docs/diagrams/reception_state.png','图4-5 电话接待的办理状态与成约条件',16)
 p('图示为接待主线及主要事件。办理中可追加沟通、重新核实、明确结束或撤回；待联系、待确认和候补等待必须有有效责任及期限。电话成约须完整建档与明确同意；候补成约关联原成功结果，不另建预约。结束状态保留事实。')
 figure(repo/'docs/diagrams/resource_state.png','图4-6 资源故障协调状态与原承诺保护',16)
 p('资源故障不自动取消预约。前台明确联系、兼容替换或核实解决，重复提交不重复替换；医师或时间变化须取得患者同意并改期。到诊仍在使用或设备不可用时不能重复接诊，治疗中故障由医护处置。')
 mapping={p.text:(p.text.replace('　',' ',1),2) for p in paras[123:146] if p.style.name=='Heading 2'}
 append_nodes(frozen(123,146),mapping,design=True)
 mapping={p.text:(p.text.replace('4.6','4.5',1).replace('4.7','4.6',1).replace('4.8','4.7',1).replace('　',' ',1),2) for p in paras[150:161] if p.style.name=='Heading 2'}
 append_nodes(frozen(150,161),mapping,design=True)
 for item in source['design']:
  if item['heading'].startswith('4.19'):
   page();heading(item['heading']);p(item['paragraphs'][0])
   figure(repo/'docs/diagrams/recall_state_print.png','图4-43 复诊责任状态与实际完成依据',16,max_height=12)
   p('\n'.join(source['state_legends']['recall']),10.5,False,False).paragraph_format.line_spacing=Pt(16)
   p(item['paragraphs'][2])
   page();p(item['paragraphs'][1])
   figure(repo/'docs/diagrams/lab_state_print.png','图4-44 加工送返周期与临床验收状态',16,max_height=14)
   p('\n'.join(source['state_legends']['lab']),10.5,False,False).paragraph_format.line_spacing=Pt(16)
   continue
  add(item)
  if item['heading'].startswith('4.11'):
   figure(repo/'docs/diagrams/domain_appointment.png','图4-13 取消跟进与改进措施的领域关系',16)
   p('每个取消预约至多一个当前原因跟进，可引用正式另约；措施按诊所、星期和时段建立，不占用患者资源。每条办理历史只能属于跟进或措施之一，不能覆盖原预约和统计事实。')
   figure(repo/'docs/diagrams/improvement_state.png','图4-14 改进措施状态与独立复核',16)
   p('执行与复核采用不同账号；后续观察窗口完整结束且不早于最近执行开始日。样本不足、不可比和变化待观察分别记录，不把统计变化当作措施的因果效果。')
  if item['heading'].startswith('4.13'):
   manifest=json.loads((repo/'docs/database/view_manifest.json').read_text())
   for number,name in enumerate(['er_booking','er_catalogue','er_resource_claims','er_finance','er_schedule_coordination','er_portal_reschedule','er_patient_relationship','er_professional_authority','er_clinical_referral','er_clinical_history','er_clinical_encounter','er_treatment_plan','er_plan_decisions','er_performed_billing','er_next_visit','er_clinical_recall','er_laboratory','er_clinic_directory','er_patient_account','er_patient_enrollment','er_insurance_policy','er_insurance_eligibility','er_insurance_settlement','er_fund_allocation','er_fund_followup','er_insurance_reversal'],15):
    if number>15:page()
    heading('4.13.'+str(number-14)+' '+manifest[name]['title'],3,False)
    figure(repo/'docs/database'/(name+'.png'),'图4-'+str(number)+' '+manifest[name]['title']+'数据库ER图',16,max_height=12.5 if number==15 else 18)
    p(manifest[name]['note'],10.5)
  if item['heading'].startswith('4.17'):
   figure(repo/'docs/diagrams/clinical_record_state.png','图4-41 检查草稿与确认版本的业务状态',16,max_height=18)
   p('状态图描述可观察的业务阶段，不增加虚构的状态列。旧确认版本在更正草稿期间继续保留；确认及保存不等于合格电子签名或实际治疗。')
  if item['heading'].startswith('4.18'):
   figure(repo/'docs/diagrams/domain_continuity.png','图4-42 连续诊疗与后续责任的领域关系',16,max_height=18)
 mind(4)
 page();heading('第5章 系统实现与测试',1)
 for item in source['implementation']:
  add(item)
  if item['heading'].startswith('5.3'):
   figure(folder/'finance-form-ux2.png','图5-1 收退款申请的分组表单',14)
 mind(5)
 page();heading('第6章 总结与展望',1)
 for item in source['conclusion']:add(item)
 mind(6)
 page();heading('参考文献',1)
 for text in old_refs+source['extra_references']:p(text,10.5,False,False,False,space=5)
 page();heading('附录A 基础系统用例规约',1)
 p('本附录给出SU-01—25及共享核验SF-01。规约以业务目标、交互、正常与异常结果为核心；验收编号为需求追踪标识，功能完成状态见第5章。',10.5)
 appendix_b=False
 p('附录中固定30分钟、200个候选格及最大匹配描述适用于未启用资源控制的历史模式。已启用资源控制的诊所按SU-54与SU-57核对服务时长、椅位和必要设备，并按登记与可行时间先后生成建议；14天候补范围、明确接受、发布重检和原承诺保护继续适用。',10.5)
 for title,texts in uc:
  if title.startswith('SU-26'):
   page();heading('附录B 维护 协调与通知用例规约',1);appendix_b=True
   p('SU-26—38说明资料维护、出诊协调和站内任务消息。消息仅提示办理，不代替患者同意、任务受理或资金事实；资料更正、出诊维护及重试按各自业务流程办理。',10.5)
  texts=source.get('use_case_overrides',{}).get(title[:5],texts)
  title=source.get('use_case_titles',{}).get(title[:5],title)
  heading(title,3,False);rows=[['用例名称',title]];group='说明';buffer=[]
  def flush():
   if buffer:rows.append([group,'\n'.join(buffer)]);buffer.clear()
  expanded=[line for value in texts for line in value.splitlines() if line.strip()]
  for text in expanded:
   text=fix_legacy(text)
   if text.startswith('追踪与状态：'):
    parts=[v for v in text.split('；') if re.search(r'(?:BR|NFR|AT)-[0-9]+',v)]
    text='；'.join(parts)+'；功能范围及业务测试见第5章。'
   if re.fullmatch(r'[A-G]\. .+',text) or text.rstrip('：:') in ('扩展','扩展路径','业务规则','基本路径','追踪与验收'):
    flush();group=re.sub(r'^[A-G]\. ','',text).rstrip('：:');continue
   match=re.match(r'^([^：]{1,22})：(.+)',text)
   if match and not re.match(r'^[•\d]',text):
    flush();rows.append([match[1],match[2]])
   else:buffer.append(text)
  flush();table(['标题','内容（'+title.split('　')[0]+'）'],rows,[3,13])
 page();heading('附录C 扩展业务用例规约',1)
 p('本附录补充SU-39—96，覆盖电话接待、统一资源、取消改进、财务设备、患者关系、专业协作及连续诊疗。每项分别列明岗位、输入、正常与异常路径、最低保证及验收目标。',10.5)
 for c in json.loads((folder/'business_use_cases.json').read_text()):
  title=c['id']+'　'+c['name'];heading(title,3,False)
  rows=[['用例名称',title],['执行者／触发',c['actor']],['实现状态',c['status']],['前置条件',c['precondition']],['主要输入',c['inputs']],['基本路径','\n'.join(str(i+1)+'）'+x for i,x in enumerate(c['flow']))],['扩展路径','\n'.join(c['alternatives'])],['成功结果',c['result']],['最低保证',c['minimum_guarantee']],['业务规则',c['rules']],['验收目标','\n'.join(c['acceptance'])]]
  table(['标题','内容（'+c['id']+'）'],rows,[3,13],case_label='C')
 # Contents is generated from actual headings; page mapping comes from latest PDF.
 pages=json.loads((folder/'toc_pages.json').read_text()) if (folder/'toc_pages.json').exists() else {}
 for text,level in toc:
  x=D.add_paragraph();x.paragraph_format.first_line_indent=Pt(0);x.paragraph_format.left_indent=Cm(0 if level==1 else .6);x.paragraph_format.line_spacing=Pt(16);x.paragraph_format.space_after=Pt(0)
  tabs=OxmlElement('w:tabs');tab=OxmlElement('w:tab');tab.set(qn('w:val'),'right');tab.set(qn('w:leader'),'dot');tab.set(qn('w:pos'),'9070');tabs.append(tab);x._p.get_or_add_pPr().append(tabs)
  font(x.add_run(text+'\t'+str(pages.get(text,'待校核'))),10.5,level==1)
  toc_anchor._p.addprevious(x._p)
 toc_anchor._p.getparent().remove(toc_anchor._p)
 stem=source['file_stem'];D.save(output/(stem+'.docx'));(folder/'REPORT.md').write_text('\n'.join(markdown).rstrip()+'\n')
 (folder/'toc_entries.json').write_text(json.dumps(toc,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'docx':stem+'.docx','use_cases_retained':len(uc),'tables':len(D.tables),'images':len(D.inline_shapes),'toc_entries':len(toc)},ensure_ascii=False))

if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--folder',type=Path,default=Path(__file__).resolve().parent);parser.add_argument('--output',type=Path);parser.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2]);a=parser.parse_args();build(a.folder.resolve(),a.repo.resolve(),a.output.resolve() if a.output else None)
