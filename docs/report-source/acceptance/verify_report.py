"""Read the finished PDF, its outline, editable sheets and case catalogue."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

import pypdfium2
from pypdf import PdfReader


HERE = Path(__file__).resolve().parent
TARGET = HERE.parents[2] / "课程报告/课程报告_张加良_8210241102.pdf"


def insist(condition, message):
    if not condition:
        raise ValueError(message)


def verify(path):
    reader = PdfReader(path)
    with pypdfium2.PdfDocument(path) as document:
        pages = []
        for page in document:
            extracted = page.get_textpage()
            try:
                pages.append(extracted.get_text_bounded())
            finally:
                extracted.close()
                page.close()
    complete_text = "\n".join(pages)
    forbidden = re.search(r"WorkBuddy|Codex|ChatGPT|模拟|开发者|测试|\bAI\b", complete_text, re.I)
    insist(forbidden is None, "Editorial vocabulary appears in the finished report")
    outline = [d for d in reader.outline if isinstance(d, dict)]
    chapter_names = [d.title for d in outline if re.match(r"第[一二三四五]章", d.title)]
    insist(len(chapter_names) == 5, "Five chapter bookmarks required")
    appendix = next(d for d in outline if d.title.startswith("附录"))
    appendix_start = reader.get_destination_page_number(appendix)
    cases = json.loads((HERE / "用例目录.json").read_text())
    actual_ids = re.findall(r"\b(?:SU-\d{2,3}|SF-01)\b", "\n".join(pages[appendix_start:]))
    insist(actual_ids == [entry["id"] for entry in cases], "Index numbers missing, changed or duplicated")
    for entry in cases:
        insist(entry["title"] in "".join("".join(pages[appendix_start:]).split()),
                f"Use case {entry['id']} missing its title")
    diagrams = ElementTree.parse(HERE / "门诊模型.drawio").getroot().findall("diagram")
    graph = PdfReader(HERE / "门诊模型.pdf")
    insist(len(diagrams) == len(graph.pages) == 7, "Expected seven editable drawings and vector pages")
    markers = ["取得就诊安排", "核对并登记到诊", "核对并确认改期", "检查记录版本",
               "提交已核对的提案", "核实爽约", "adc_clinical_draft"]
    model_refs = re.findall(r"@model (\d+) \| (图 \d+-\d+)", (HERE / "正文.md").read_text())
    insist(len(model_refs) == len(markers), "Seven figures must be present in the report source")
    for (ordinal, caption), marker in zip(model_refs, markers, strict=True):
        target_page = next((i for i, contents in enumerate(pages)
                            if caption in contents and marker in contents), None)
        insist(target_page is not None and len(reader.pages[target_page].images) == 0,
                f"{caption} lacks its searchable vector figure")
        cells = diagrams[int(ordinal) - 1].findall("mxGraphModel/root/mxCell")
        vertices = [n for n in cells if n.get("vertex") == "1"]
        edges = [n for n in cells if n.get("edge") == "1"]
        insist(len(vertices) >= 4 and len(edges) >= 1, f"Drawing {ordinal} lacks editable content")
    pictures = [(i + 1, len(page.images)) for i, page in enumerate(reader.pages) if len(page.images)]
    insist(len(pictures) == 3 and all(count == 1 for _, count in pictures), "Three distinct screen images required")
    observed = json.loads((HERE / "验收记录.json").read_text())
    for filename, checksum in observed["screen_sha256"].items():
        actual = hashlib.sha256((HERE / "screens" / filename).read_bytes()).hexdigest()
        insist(actual == checksum, f"Screen image changed since acceptance: {filename}")
    compact = "".join(complete_text.split())
    scope = observed["integration"]
    insist(scope["application_commit"][:12] in compact, "Accepted application version missing")
    for chain in (scope["copy_a"]["chain"], scope["copy_b"]["chain"], scope["read_only"]["existing_chain"]):
        label = "→".join(f"#{number}" for number in chain)
        insist(label in compact, "Missing observed appointment chain " + label)
    insist(len(observed["physical_foreign_keys"]) == observed["physical_fk_count_verified_in_figure_scope"],
           "Foreign-key evidence incomplete")
    toc = reader.pages[reader.get_destination_page_number(next(d for d in outline if d.title == "目录"))]
    links = [a.get_object() for a in toc.get("/Annots", [])]
    valid_pages = {p.indirect_reference.idnum for p in reader.pages}
    insist(all(a["/Dest"][0].idnum in valid_pages for a in links) and len(links) >= 20,
            "Contents links must resolve inside the PDF")
    fonts = reader.pages[0]["/Resources"]["/Font"]
    embedded = [str(f.get_object().get("/BaseFont", "")) for f in fonts.values()
                if "/FontFile2" in (f.get_object().get("/FontDescriptor") or {})]
    insist(any("Songti" in f for f in embedded), "Report must contain embedded Songti glyphs")
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "pages": len(pages),
            "chapters": len(chapter_names), "case_index_entries": len(actual_ids), "contents_links": len(links),
            "editable_vector_figures": len(diagrams), "screen_pages": [i for i, _ in pictures],
            "embedded_songti_fonts": sorted({f.split("+")[-1] for f in embedded if "Songti" in f})}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", type=Path, default=TARGET)
    report = verify(parser.parse_args().pdf)
    print(json.dumps(report, ensure_ascii=False, indent=2))
