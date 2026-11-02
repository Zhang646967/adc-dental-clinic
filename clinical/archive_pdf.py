"""Local fixed PDF rendering from an approved immutable source, without external services."""
import hashlib,io,threading
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,KeepTogether
from clinical.archive_display import sections,scalar

RENDERER='adc.archive-pdf.c33a.v1.reportlab4.4.9'
FONT=Path(__file__).parent/'fonts/NotoSansSC-Regular.ttf'
_lock=threading.Lock()


def render(snapshot,*,number,kind,review):
    with _lock:
        if 'ADCArchive' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('ADCArchive',str(FONT)))
    body=ParagraphStyle('archive-body',fontName='ADCArchive',fontSize=10.5,leading=16,wordWrap='CJK',spaceAfter=6)
    small=ParagraphStyle('archive-small',parent=body,fontSize=9,leading=13,textColor=colors.HexColor('#536562'))
    heading=ParagraphStyle('archive-heading',parent=body,fontSize=14,leading=21,spaceBefore=15,spaceAfter=10,keepWithNext=True)
    title=ParagraphStyle('archive-title',parent=heading,fontSize=21,leading=29,spaceAfter=16)
    def p(value,style=body):return Paragraph(escape(str(value)).replace('\n','<br/>'),style)
    header=snapshot['header'];out=io.BytesIO();story=[]
    doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=45,rightMargin=45,topMargin=49,bottomMargin=44,
        title='门诊病历归档' if kind=='ARCHIVE' else '缺项资料保全',author=header['clinic_name'],allowSplitting=True)
    story.append(p('门诊病历归档' if kind=='ARCHIVE' else '缺项资料保全',title))
    story.append(p(header['clinic_name'],heading))
    if kind!='ARCHIVE':story.append(p('存在下列材料缺项。本文件保留现有资料，不表示完整归档或事前手续已补齐。'))
    for k in ('patient_name','patient_no','visit_no','dentist_name','employee_no'):
        from clinical.archive_display import label
        story.append(p(label(k)+'：'+str(header.get(k,''))))
    story.append(p('固定文件第'+str(number)+'包；历史姓名及机构信息按原文书快照保存。',small))
    signoff=review.get('signoff',{})
    story.append(p('独立审核：'+str(signoff.get('name',''))+'；审核时间：'+scalar(signoff.get('recorded_at')),small))
    story.append(p('账号确认、纸质原件引用与可靠电子签名分别管理；本文件不代替未完成的原件手续。',small))
    for section in sections(snapshot):
        story.append(p(section['title'],heading))
        for key,value in section['rows']:
            # Separate label/value paragraphs can split cleanly even for a long medical note.
            story.append(p(key,small));story.append(p(value))
    story.append(p('收费记录按选定的已发布版本保存；付款及后续更正请在结算记录中核对。',small))
    def page(c,d):
        c.setFont('ADCArchive',8);c.setFillColor(colors.HexColor('#536562'))
        c.drawString(45,25,'固定版本 · 第'+str(d.page)+'页')
    def stable_canvas(*a,**kw):kw['invariant']=1;return canvas.Canvas(*a,**kw)
    doc.build(story,onFirstPage=page,onLaterPages=page,canvasmaker=stable_canvas)
    data=out.getvalue()
    if not data.startswith(b'%PDF-'):raise ValueError('PDF_NOT_READY')
    return data,dict(renderer=RENDERER,font_sha256=hashlib.sha256(FONT.read_bytes()).hexdigest())
