"""Revise a specified acceptance page of the published PDF.

The reviewed baseline supplies the other pages, bookmarks and numbering. This
small revision reads the maintained section source and preserves their bytes.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--proof', type=Path, required=True)
    parser.add_argument('--spec', type=Path)
    parser.add_argument('--source', type=Path)
    args = parser.parse_args()
    source_dir = args.repo / 'docs/report-source'
    spec = json.loads((args.spec or source_dir / 'pdf_revision.json').read_text())
    source = json.loads((args.source or source_dir / 'report_source.json').read_text())
    raw = subprocess.check_output(
        ['git', 'show', spec['baseline_commit'] + ':' + spec['pdf_path']], cwd=args.repo)
    assert hashlib.sha256(raw).hexdigest() == spec['baseline_sha256']
    reader = PdfReader(io.BytesIO(raw))
    page_index = spec['physical_page'] - 1
    old_page = reader.pages[page_index]
    width, height = map(float, old_page.mediabox[2:])
    assert len(reader.pages) == 293 and not old_page.get('/Annots')
    songti = Path('/System/Library/Fonts/Supplemental/Songti.ttc')
    if songti.exists():
        pdfmetrics.registerFont(TTFont('ReportBody', str(songti), subfontIndex=6))
        pdfmetrics.registerFont(TTFont('ReportBold', str(songti), subfontIndex=1))
    else:
        font = args.repo / 'clinical/fonts/NotoSansSC-Regular.ttf'
        pdfmetrics.registerFont(TTFont('ReportBody', str(font)))
        pdfmetrics.registerFont(TTFont('ReportBold', str(font)))
    pdfmetrics.registerFont(TTFont('ReportHeading', str(
        args.repo / 'clinical/fonts/NotoSansSC-Regular.ttf')))
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(width, height), initialFontName='ReportBody')
    left, right = 85.15, width - 56.7
    c.setFont('ReportBody', 9)
    c.setFillColorRGB(.25, .25, .25)
    c.drawString(left, height - 51, '中南大学 · 系统分析与设计')
    c.drawString(263.55, height - 51, 'ADC 牙科连锁运营管理系统')
    c.setStrokeColorRGB(.5, .5, .5)
    c.setLineWidth(.4)
    c.line(left, height - 60, right, height - 60)
    c.setFillColorRGB(0, 0, 0)
    body = ParagraphStyle('body', fontName='ReportBody', fontSize=12,
                          leading=spec.get('leading',22), firstLineIndent=24, alignment=TA_LEFT,
                          wordWrap='CJK')
    top = height - 79
    if spec.get('continuation'):
        style = ParagraphStyle('continuation', parent=body, firstLineIndent=0)
        p = Paragraph(spec['continuation'], style)
        _, h = p.wrap(right-left, height)
        p.drawOn(c, left, top-h)
        top -= h + 8
    blocks = []
    for title in spec['headings']:
        section = next(s for s in source['implementation'] if s['heading'] == title)
        assert pdfmetrics.stringWidth(title, 'ReportHeading', 14) < right-left
        c.setLineWidth(.2)
        title_text = c.beginText(left, top-15)
        title_text.setFont('ReportHeading', 14)
        title_text.setTextRenderMode(2)
        title_text.textOut(title)
        title_text.setTextRenderMode(0)
        c.drawText(title_text)
        top -= 34
        for text in section['paragraphs']:
            p = Paragraph(text, body)
            _, h = p.wrap(right-left, height)
            p.drawOn(c, left, top-h)
            top -= h
        top -= 10
        blocks.append(dict(heading=title, bottom_from_top=round(height-top, 2)))
    if spec.get('show_mind_map', True):
        mind = ParagraphStyle('mind', fontName='ReportBody', fontSize=10.5,
                              leading=16, wordWrap='CJK')
        p = Paragraph('思维导图　' + source['mind_maps']['5'], mind)
        _, h = p.wrap(right-left, height)
        p.drawOn(c, left, top-h)
        top -= h
    assert top > 67, 'Section text exceeds the reviewed page body'
    c.setFont('ReportBody', 9)
    c.drawCentredString(width/2, 35, f"第 {spec['printed_page']} 页")
    c.showPage()
    c.save()
    replacement = PdfReader(io.BytesIO(buffer.getvalue())).pages[0]
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    page = writer.pages[page_index]
    # Keep the existing page object so bookmark destinations remain unchanged.
    for key in ('/Contents', '/Resources'):
        page[NameObject(key)] = replacement.raw_get(key).clone(writer)
    revision_date = spec['revision_date'].replace('-', '')
    writer.add_metadata({'/ModDate': f"D:{revision_date}000000-08'00'",
                         '/Subject': spec.get('subject','病历归档与受控电子副本；患者入口与分项验收修订')})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('wb') as stream:
        writer.write(stream)
    current = PdfReader(args.output)
    assert len(current.pages) == len(reader.pages)
    assert len(current.outline) == len(reader.outline)
    unchanged = [i for i in range(len(reader.pages)) if i != page_index]
    assert all(current.pages[i].get_contents().get_data() ==
               reader.pages[i].get_contents().get_data() for i in unchanged)
    actual_text = current.pages[page_index].extract_text()
    assert all(t in actual_text for t in spec['headings'])
    assert spec['required_acceptance_text'] in actual_text.replace('\n', '')
    args.proof.write_text(json.dumps(dict(
        passed=True, pdf_only=True, word_written=False, pages=len(current.pages),
        revised_physical_pages=[page_index+1], unchanged_page_content_streams=len(unchanged),
        outline_entries=len(current.outline), sections=blocks,
        body_bottom_from_top=round(height-top, 2),
        baseline_sha256=spec['baseline_sha256'],
        pdf_sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
        **({'official_normal_entry_retest':spec['official_normal_entry_status']}
           if 'official_normal_entry_status' in spec else {'acceptance_status':spec['acceptance_status']}),
    ), ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(dict(passed=True, pdf_only=True, unchanged_pages=len(unchanged),
                          bottom=round(height-top, 2))))


if __name__ == '__main__':
    main()
