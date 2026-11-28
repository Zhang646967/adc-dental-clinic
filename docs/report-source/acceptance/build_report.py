"""Rebuild the Chinese acceptance report, retaining vector drawings and text."""
import argparse
import json
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image
from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
TARGET = REPO / "课程报告/课程报告_张加良_8210241102.pdf"
FONTS = Path("/System/Library/Fonts/Supplemental/Songti.ttc")
TITLE = "ADC 牙科连锁运营管理系统分析与设计"
W, H = A4
LEFT, RIGHT, TOP, BOTTOM = 79, 61, H - 83, 68
SPAN = W - LEFT - RIGHT
INK = colors.HexColor("#171717")


def text_style(name, size, leading, *, bold=False, center=False, indent=0):
    return ParagraphStyle(
        name, fontName="SongBold" if bold else "Song", fontSize=size,
        leading=leading, textColor=INK, firstLineIndent=indent,
        alignment=TA_CENTER if center else 0, wordWrap="CJK",
        splitLongWords=1, spaceBefore=0, spaceAfter=0,
    )


def para(text, style):
    link = re.fullmatch(r"\[([^\]]+)\]\((https://[^\s<>\"]+)\)", text)
    if link:
        label, url = link.groups()
        return Paragraph(f'<link href="{escape(url)}" color="#244958"><u>{escape(label)}</u></link>', style)
    return Paragraph(escape(text), style)


def table(rows, width, factor):
    columns = len(rows[0])
    ratios = {2: (.23, .77), 3: (.23, .355, .415), 4: (.25, .25, .25, .25),
              5: (.16, .24, .24, .27, .09)}[columns]
    if columns == 3 and rows[0][-1] == "结论":
        ratios = (.33, .57, .10)
    grid = []
    for i, row in enumerate(rows):
        if len(row) != columns:
            raise ValueError(f"Table row has {len(row)} columns, expected {columns}")
        style = text_style("table", 10.5 * factor, 15.6 * factor, bold=i == 0)
        grid.append([para(cell, style) for cell in row])
    t = Table(grid, colWidths=[width * v for v in ratios], hAlign="LEFT")
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 1, INK),
        ("LINEBELOW", (0, 0), (-1, 0), .55, INK),
        ("LINEBELOW", (0, -1), (-1, -1), 1, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5 * factor),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * factor),
    ]))
    return t


def report_pages():
    text = (HERE / "正文.md").read_text()
    evidence = json.loads((HERE / "验收记录.json").read_text())
    text = text.replace("@device", evidence["iphone"])
    rows = evidence["appointment_readability"]["confirm_page_sizes"]
    size_table = ["| 屏宽（逻辑像素） | 标准字号 16 | 较大字号 19 | 大字号 26 |"]
    for width in [375, 390, 430]:
        cells = []
        for setting in [16, 19, 26]:
            row = next(item for item in rows if (item["width"], item["setting"]) == (width, setting))
            cells.append(f'{row["title_px"]} / {row["time_px"]}')
        size_table.append("| " + " | ".join([str(width), *cells]) + " |")
    text = text.replace("@appointment_metrics", "\n".join(size_table))
    return [[s.strip() for s in part.splitlines() if s.strip()]
            for part in re.split(r"^---\s*$", text, flags=re.M)]


def runs(lines):
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            yield "table", rows
            continue
        if line.startswith("@"):
            key, label = line.split("|", 1)
            kind, name = key.split()
            yield kind[1:], (name, label.strip())
        elif line.startswith("### 表 "):
            yield "caption", line[4:]
        elif line.startswith("#"):
            depth = len(line) - len(line.lstrip("#"))
            yield f"h{depth}", line[depth:].strip()
        else:
            yield "p", line
        i += 1


def page_content(c, blocks, chapter_page, plots, overlays, factor, draw):
    y = TOP
    for kind, val in blocks:
        if kind in ("model", "screen"):
            name, title = val
            if kind == "screen":
                asset = HERE / "screens" / (name + ".png")
                with Image.open(asset) as im:
                    raw_w, raw_h = im.size
                max_height = 320 * factor
            else:
                box = plots.pages[int(name) - 1].cropbox
                raw_w, raw_h = float(box.width), float(box.height)
                max_height = 305 * factor
            scale = min((SPAN - 8) / raw_w, max_height / raw_h)
            w, h = raw_w * scale, raw_h * scale
            x = LEFT + (SPAN - w) / 2
            y -= h + 5
            if draw and kind == "screen":
                c.drawImage(str(asset), x, y, width=w, height=h)
            if draw and kind == "model":
                overlays.append((chapter_page, int(name) - 1, x, y, scale))
            y -= 7
            item = para(title, text_style("fig", 10.4, 15, center=True))
            after = 14 * factor
        elif kind == "table":
            item, after = table(val, SPAN, factor), 12 * factor
        else:
            settings = {
                "h1": (19, 28, True, True, 0, 18), "h2": (14.5, 22, True, False, 0, 9),
                "h3": (12.2, 19, True, False, 0, 5), "caption": (10.7, 16, False, True, 0, 4),
                "p": (12, 21.5, False, False, 24, 8),
            }
            size, leading, bold, center, indent, after = settings[kind]
            if kind == "p" and val.startswith("["):
                indent, size, leading = 0, 10.6, 18
            item = para(val, text_style(kind, size * factor, leading * factor,
                                        bold=bold, center=center, indent=indent * factor))
            after *= factor
        _, height = item.wrap(SPAN, H)
        y -= height
        if draw:
            item.drawOn(c, LEFT, y)
        y -= after
    return y


def header_footer(c, label, page):
    c.setFont("Song", 9)
    c.setFillColor(INK)
    c.drawString(LEFT, H - 44, "中南大学　系统分析与设计")
    c.drawRightString(W - RIGHT, H - 44, label)
    c.setStrokeColor(INK)
    c.setLineWidth(.65)
    c.line(LEFT, H - 50, W - RIGHT, H - 50)
    c.setFont("Song", 10)
    c.drawCentredString(W / 2, 37, page)


def mark(c, key, title, level=0):
    c.bookmarkPage(key)
    c.addOutlineEntry(title, key, level=level)


def front(c, pages):
    mark(c, "cover", "封面")
    for y, txt, size, font in [
        (710, "中 南 大 学", 29, "SongBold"), (681, "CENTRAL SOUTH UNIVERSITY", 12, "Times-Roman"),
        (591, "系统分析与设计", 22, "Song"), (544, "系统验收报告", 28, "SongBold"),
        (445, "ADC 牙科连锁运营管理系统", 22, "SongBold"), (410, "分析与设计", 22, "SongBold"),
    ]:
        c.setFont(font, size)
        c.drawCentredString(W / 2, y, txt)
    for n, (label, name) in enumerate([
        ("学　　院", "商学院"), ("专业班级", "信管 T2401"), ("姓　　名", "张加良"),
        ("学　　号", "8210241102"), ("指导教师", "毕文杰 教授"),
    ]):
        y = 308 - n * 30
        c.setFont("Song", 13)
        c.drawString(168, y, label)
        c.drawString(269, y, name)
    c.setFont("Song", 13)
    c.drawCentredString(W / 2, 105, "二〇二六年十一月")
    c.showPage()
    mark(c, "abstract", "摘要")
    header_footer(c, "摘　要", "I")
    intro = [
        ("h1", TITLE), ("h2", "摘　要"),
        ("p", "在连锁口腔门诊中，一次改期会同时影响患者的到店计划、前台的身份核对和医师的接诊安排。若仅保留新时间、用姓名识别人，或者把正在修订的病历作为当前确认版，三个岗位将看到互不一致的事实。"),
        ("p", "本报告以患者预约、门店接待和医师检查记录为主线，结合报告发布、复诊接续与离店结算，说明门诊中的责任移交。以业务用例和业务序列表达组织对外服务，再用系统用例、分析类、协作序列和状态机解释办理过程。物理关系图以 PostgreSQL 中的外键与唯一性约束为依据。"),
        ("p", "验收时可分别从患者、前台和医师入口核对改期前后的预约、同名患者的编号、草稿与确认版。在正式配置下，三个岗位沿同一笔就诊核对报告发布、本人提醒和复诊预约。附录收录 147 项业务用例和一项共享核验。"),
        ("h3", "关键词　口腔门诊　患者身份　预约改期　临床记录　系统验收"),
    ]
    abstract_bottom = page_content(c, intro, 1, None, [], 1, True)
    c.setFont("Times-Bold", 13)
    c.drawString(LEFT, abstract_bottom - 14, "Abstract")
    english = Paragraph(
        "An appointment change affects the patient’s arrival time, the front desk’s "
        "identification of the patient and the dentist’s view of the encounter. "
        "This report follows these three records across outpatient roles. It connects "
        "business and system use cases to admission, chart confirmation, reporting, "
        "follow-up and billing. The last chapter presents observed outcomes, "
        "including how to distinguish an original appointment from its successor, "
        "two patients with the same name and a draft from the current confirmed record. "
        "Under the production configuration, three roles trace one encounter from report publication "
        "to the patient’s in-app notice and confirmed follow-up.",
        ParagraphStyle("abstract_en", fontName="Times-Roman", fontSize=11.5, leading=17),
    )
    _, en_h = english.wrap(SPAN, H)
    english.drawOn(c, LEFT, abstract_bottom - 24 - en_h)
    c.showPage()
    mark(c, "toc", "目录")
    header_footer(c, "目　录", "II")
    c.setFont("SongBold", 20)
    c.drawCentredString(W / 2, H - 99, "目　录")
    rows = []
    for i, lines in enumerate(pages, 1):
        for line in lines:
            if line.startswith("# ") or line.startswith("## ") or re.match(r"^### \d+\.\d+", line):
                rows.append((line.split(" ", 1)[1], i, line.startswith("# ")))
    rows.append(("附录　业务用例索引", len(pages) + 1, True))
    rows.append(("系统用例 147 项、共享核验 1 项", len(pages) + 1, False))
    gap = min(25, 610 / len(rows))
    y = H - 138
    for text, number, main in rows:
        x = LEFT if main else LEFT + 18
        c.setFont("SongBold" if main else "Song", 12.8 if main else 11)
        c.drawString(x, y, text)
        c.drawRightString(W - RIGHT, y, str(number))
        key = f"part{number}" if number <= len(pages) else "appendix"
        c.linkRect("", key, (x, y - 3, W - RIGHT, y + 14), relative=0, thickness=0)
        y -= gap
    c.showPage()


def appendix(c, examples, index, count):
    mark(c, "appendix" if not index else f"appendix{index}", "附录　业务用例索引" if not index else
         f"用例索引（{index + 1}）", level=0 if not index else 1)
    c.setFont("SongBold", 18)
    c.drawCentredString(W / 2, TOP - 18, "附录　业务用例索引" if not index else "业务用例索引（续）")
    c.setFont("Song", 11)
    c.drawString(LEFT, TOP - 48, f"第 {index + 1} 组，共 {count} 组。按业务编号查阅。")
    rows = [["编号", "业务目标"]] + [[i["id"], i["title"]] for i in examples]
    t = table(rows, SPAN, .94)
    _, h = t.wrap(SPAN, H)
    y = TOP - 64 - h
    if y < BOTTOM:
        raise ValueError("Appendix does not fit")
    t.drawOn(c, LEFT, y)


def build(destination, fonts):
    pdfmetrics.registerFont(TTFont("Song", str(fonts), subfontIndex=6))
    pdfmetrics.registerFont(TTFont("SongBold", str(fonts), subfontIndex=1))
    pages = report_pages()
    cases = json.loads((HERE / "用例目录.json").read_text())
    expected = {f"SU-{i:02}" for i in range(1, 148)} | {"SF-01"}
    if len(cases) != 148 or {i["id"] for i in cases} != expected:
        raise ValueError("Business-use-case index incomplete")
    group_count = (len(cases) + 23) // 24
    portions = [cases[len(cases) * i // group_count:len(cases) * (i + 1) // group_count]
                for i in range(group_count)]
    plots = PdfReader(HERE / "门诊模型.pdf")
    if len(plots.pages) != 7:
        raise ValueError("Expected seven vector drawings")
    base = BytesIO()
    c = canvas.Canvas(base, pagesize=A4, invariant=1, pageCompression=1)
    c.setAuthor("张加良")
    c.setTitle(TITLE)
    c.setSubject("门诊业务、系统设计与岗位验收")
    c.setCreator("中南大学商学院")
    front(c, pages)
    overlays, page_stats = [], []
    chapter = ""
    for i, lines in enumerate(pages, 1):
        blocks = list(runs(lines))
        new_chapter = lines[0].startswith("# ")
        if new_chapter:
            chapter = lines[0][2:]
        mark(c, f"part{i}", lines[0].split(" ", 1)[1], level=0 if new_chapter else 1)
        header_footer(c, chapter, str(i))
        for factor in (1, .98, .96, .94, .92, .9):
            last = page_content(c, blocks, i + 2, plots, [], factor, False)
            if last >= BOTTOM:
                break
        else:
            raise ValueError(f"Page {i} does not fit: {last:.1f}pt")
        page_content(c, blocks, i + 2, plots, overlays, factor, True)
        page_stats.append((i, factor, round(last, 1)))
        c.showPage()
    for i, group in enumerate(portions):
        header_footer(c, "附录　业务用例索引", str(len(pages) + i + 1))
        appendix(c, group, i, len(portions))
        c.showPage()
    c.save()
    base.seek(0)
    output = PdfWriter(clone_from=base)
    inventory = json.loads((HERE / "验收记录.json").read_text())
    site_record = json.loads((HERE / inventory["site_report_chain"]).read_text())
    server_record = json.loads((HERE / inventory["server_report_chain"]).read_text())
    captured = max(datetime.fromisoformat(timestamp.replace("Z", "+00:00")) for timestamp in
                   (site_record["capture_time_utc"], server_record["run_utc"],
                    inventory["appointment_readability"]["last_observation_utc"],
                    inventory["patient_navigation"]["last_observation_utc"])).astimezone(timezone.utc)
    output.add_metadata({"/CreationDate": "D:20261127000000Z", "/ModDate": captured.strftime("D:%Y%m%d%H%M%SZ")})
    for page_no, diagram_no, x, y, scale in overlays:
        drawing = plots.pages[diagram_no]
        box = drawing.cropbox
        matrix = Transformation().translate(-float(box.left), -float(box.bottom)).scale(scale).translate(x, y)
        output.pages[page_no].merge_transformed_page(drawing, matrix, over=True)
    if len(overlays) != 7:
        raise ValueError("Expected exactly seven placements")
    with destination.open("wb") as stream:
        output.write(stream)
    print(f"{len(output.pages)} pages; {len(overlays)} vector diagrams; {len(cases)} indexed cases")
    print("Body page, scale and text bottom (pt)", page_stats)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=TARGET)
    parser.add_argument("--songti", type=Path, default=FONTS)
    options = parser.parse_args()
    build(options.output, options.songti)
