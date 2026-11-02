"""Bounded local rendering; commit bytes only after rechecking the approved application."""
import hashlib,io,uuid
from xml.sax.saxutils import escape
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from accounts.models import UserAccount
from clinical.copy_models import RecordCopyRequest,RecordCopyFile
from clinical import record_copies as commands
from clinical.copy_projection import packet
from clinical.archive_pdf import FONT,_lock
from adc_core.operational_logging import emit_event

RENDERER='adc.patient-copy.c33b.v1.reportlab4.4.9'


def render(content):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer
    from reportlab.pdfgen import canvas
    with _lock:
        if 'ADCArchive' not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont('ADCArchive',str(FONT)))
    body=ParagraphStyle('copy-body',fontName='ADCArchive',fontSize=10.5,leading=16,wordWrap='CJK',spaceAfter=6)
    heading=ParagraphStyle('copy-heading',parent=body,fontSize=14,leading=21,spaceBefore=14,keepWithNext=True)
    small=ParagraphStyle('copy-small',parent=body,fontSize=9,leading=14)
    def p(value,style=body):return Paragraph(escape(str(value)).replace('\n','<br/>'),style)
    story=[p('病历资料电子副本',heading),p(content['clinic']),p('申请编号：'+str(content['request'])),
        p('领取人：'+content['recipient']+'（'+content['kind']+'）'),p('用途：'+content['purpose']),
        p('本电子副本不含机构证明印记或可靠电子签名；需要正式证明请联系门店办理。',small)]
    for record,source in zip(content['records'],content['sources']):
        h=record['header'];story.extend([p('就诊 '+h['visit_no']+' · 固定归档第'+str(source['package_number'])+'包',heading),
            p('患者：'+h['patient_name']+' · 患者编号：'+h['patient_no']),p('负责医师：'+h['dentist_name'])])
        if record['kind']!='ARCHIVE':story.append(p('本来源为缺项资料保全，不表示完整病历已归档。',heading))
        for missing in record['missing']:story.append(p('资料缺项：'+missing,small))
        for section in record['sections']:
            story.append(p(section['title'],heading))
            for key,value in section['rows']:story.extend([p(key,small),p(value)])
    story.append(p('仅包含本申请获准的固定版本与资料类别。后续更正另行保留，费用不表示当前现金余额。',small))
    out=io.BytesIO();doc=SimpleDocTemplate(out,pagesize=A4,leftMargin=45,rightMargin=45,topMargin=46,bottomMargin=44,title='病历资料电子副本',author=content['clinic'])
    def footer(c,d):c.setFont('ADCArchive',8);c.drawString(45,25,'病历电子副本 · 申请'+str(content['request'])+' · 第'+str(d.page)+'页')
    def stable(*args,**kw):kw['invariant']=1;return canvas.Canvas(*args,**kw)
    doc.build(story,onFirstPage=footer,onLaterPages=footer,canvasmaker=stable)
    return out.getvalue()


def generate(pk):
    if settings.ADC_READ_ONLY:return dict(id=pk,state='READ_ONLY',published=False)
    row=RecordCopyRequest.objects.select_related('patient','clinic').get(pk=pk)
    if row.state!='APPROVED':return dict(id=pk,state=row.state,published=False)
    revision=row.revision;content=packet(row);error=''
    try:
        pdf=render(content)
        if not pdf.startswith(b'%PDF-'):raise ValueError()
    except Exception:
        emit_event('command.failed');pdf=None;error='PDF_RENDER_FAILED'
    with transaction.atomic():
        list(UserAccount.objects.select_for_update().filter(pk__in=sorted({row.recipient_id,row.reviewed_by_id})).order_by('pk'))
        current=RecordCopyRequest.objects.select_for_update(of=('self',)).select_related('patient','clinic').get(pk=pk)
        if current.state!='APPROVED' or current.revision!=revision:return dict(id=pk,state=current.state,published=False)
        if not commands.review_valid(current) or commands.identity(current)!=current.identity_snapshot or current.pickup_until<=timezone.now() or commands.source_stamp(current)!=current.approval['sources']:
            error='IDENTITY_SCOPE_OR_REVIEW_CHANGED'
        if error:current.state='FAILED';current.generation_error=error
        else:
            manifest=dict(contract='adc.record-copy.c33b.v1',request=pk,recipient=current.recipient_id,
                sources=content['sources'],sha256=hashlib.sha256(pdf).hexdigest(),renderer=RENDERER)
            RecordCopyFile.objects.create(request=current,pdf=pdf,sha256=manifest['sha256'],manifest=manifest,renderer=RENDERER)
            current.state='READY';current.generation_error=''
        current.attempts+=1;current.revision+=1;current.save()
        commands.record(None,current,'GENERATION_'+current.state,uuid.uuid4(),dict(error=error,attempt=current.attempts))
        return dict(id=pk,state=current.state,published=current.state=='READY')


def generate_batch(limit=1):
    ids=list(RecordCopyRequest.objects.filter(state='APPROVED').order_by('reviewed_at','pk').values_list('pk',flat=True)[:limit])
    return [generate(pk) for pk in ids]
