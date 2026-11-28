"""Read the finished PDF, its outline, editable sheets and case catalogue."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

import pypdfium2
from PIL import Image, ImageChops
from pypdf import PdfReader


HERE = Path(__file__).resolve().parent
TARGET = HERE.parents[2] / "课程报告/课程报告_张加良_8210241102.pdf"


def insist(condition, message):
    if not condition:
        raise ValueError(message)


def bookmarks(items):
    for item in items:
        if isinstance(item, list):
            yield from bookmarks(item)
        else:
            yield item


def verify_appointment_readability(reader, pages, observed):
    run = observed["appointment_readability"]
    section = next(item for item in bookmarks(reader.outline) if item.title.startswith("5.6　"))
    text = "".join(pages[reader.get_destination_page_number(section)].split())
    rows = run["confirm_page_sizes"]
    positions = {(row["width"], row["setting"]) for row in rows}
    insist(len(rows) == 9 and positions == {(w, s) for w in (375, 390, 430) for s in (16, 19, 26)},
           "Width and font observations are incomplete or duplicated")
    for width in (375, 390, 430):
        sizes = sorted((row for row in rows if row["width"] == width), key=lambda row: row["setting"])
        printed = str(width) + "".join(f'{row["title_px"]}/{row["time_px"]}' for row in sizes)
        insist(printed in text, f"The printed sizes at width {width} differ from the observation")
        for field in ("title_px", "time_px"):
            insist(sizes[0][field] < sizes[1][field] < sizes[2][field], "Expected successive increase in " + field)
    for fact in [run["application_commit"][:12], "更改预约时间（改期）", "表5-6", "只读",
                 "11月30日09:00", "12月1日10:30", "北京时间"]:
        insist(fact in text, "Missing rescheduling observation: " + fact)
    readonly = run["read_only_copy"]
    effects = run["business_effects"]
    for label in [readonly["home_action"], readonly["row_action"],
                  f'{effects["unchanged_tables"]}张业务表', f'{effects["visit_count"]}笔预约',
                  f'{effects["receipt_count"]}份回执', "未提交改期"]:
        insist(label in text, "Observed access or data effect missing from section 5.6: " + label)
    insist(readonly["read_only"] and not readonly["change_or_cancel_visible"] and
           effects["business_writes"] == effects["reschedule_confirmations"] == 0,
           "Read-only and preview observations must agree with the operator's report")
    phone = observed["iphone_evidence"]
    all_text = "".join("".join(pages).split())
    insist(phone["preview_commit"] != run["application_commit"] and phone["preview_commit"][:7] in all_text,
           "The historical device result must be identifiable separately from the current version")


def verify_patient_navigation(reader, pages, navigation):
    def section_text(number):
        prefix = {"1.2": "第一章", "5.1": "第五章"}.get(number, number + "　")
        section = next(item for item in bookmarks(reader.outline) if item.title.startswith(prefix))
        return "".join(pages[reader.get_destination_page_number(section)].split())

    patient = section_text("5.1")
    settings = section_text("5.6")
    review = navigation["reschedule"]
    version = review["application_commit"][:12]
    insist(version in settings, "Updated version missing from the section on measured results")
    for label in ["更改预约时间", "查看改期详情", "同日", "换日"]:
        insist(label in patient, "Current appointment journey missing: " + label)
    standard = next(row for row in review["comparison_height_css_px"]
                    if (row["width"], row["font"]) == (390, 16))
    insist(f'由{standard["before"]}缩至{standard["after"]}逻辑像素' in settings, "Observed heights differ")
    cases = review["cases_390_16"]
    sources = {row["source"] for row in cases}
    insist(len(sources) == 2 and len(cases) == 4 and
           all({row["single_date_heading"] for row in cases if row["source"] == source} == {True, False}
               for source in sources), "Both date comparisons required for each retained appointment")
    insist(review["disclosure_and_return_checked"] and review["new_confirmations"] == 0
           and review["tables_unchanged"] == 33, "Preview and return observations are inconsistent")

    nearby = navigation["nearby"]
    first, second = (point["rows"] for point in nearby["first_two"])
    insist([r["id"] for r in first] == [r["id"] for r in reversed(second)] and
           all(rows[0]["metres"] < rows[1]["metres"] for rows in (first, second)),
           "The nearest two branches must reverse order between the two controlled positions")
    for rows in first, second:
        insist(f'约{rows[0]["metres"]}米' in settings and rows[0]["name"].split(" · ")[-1] in settings,
               "The first branch and its displayed distance are missing")
    for label in ["微信工具分别指定两个位置", nearby["without_coordinates"]["label"], "拒绝定位", "手选城市"]:
        insist(label in settings, "Nearby branch observations missing: " + label)

    public = nearby["https_directory"]
    signed = public["published_branches_with_wgs84"]
    total = signed + public["branches_without_coordinates"]
    entrance = section_text("1.2")
    insist(f"可匿名查到{total}家门店，其中{signed}家有坐标" in entrance and
           nearby["application_commit"][:12] in settings and public["http_status"] == 200
           and public["certificate_verified"] and not public["physical_device_location_observed"],
           "Public directory scope does not match the printed evidence")
    for clinic in nearby["manual_cities"]:
        insist(clinic["button_accessible_name_has_city_and_address"] and
               clinic["city"] + clinic["district"] in entrance, "Same-name branch is not distinguishable")


def verify_screens(reader, pages, expected):
    text = (HERE / "正文.md").read_text()
    refs = re.findall(r"^@screen ([\w-]+) \| (图 [^\n]+)$", text, re.M)
    insist({name + ".png" for name, _ in refs} == expected.keys() and len(refs) == 6,
           "Each of the six captured views needs a source and caption")
    matched = []
    compact = ["".join(page.split()) for page in pages]
    for name, caption in refs:
        filename = name + ".png"
        asset = HERE / "screens" / filename
        insist(hashlib.sha256(asset.read_bytes()).hexdigest() == expected[filename],
               f"Screen image changed since acceptance: {filename}")
        where = [i for i, page in enumerate(compact) if "".join(caption.split()) in page]
        insist(len(where) == 1, f"Caption missing or duplicated: {caption}")
        with Image.open(asset) as source:
            pixels = source.convert("RGB")
        images = [item.image.convert("RGB") for item in reader.pages[where[0]].images]
        insist(any(im.size == pixels.size and ImageChops.difference(im, pixels).getbbox() is None for im in images),
               f"Printed pixels differ from captured view: {filename}")
        matched.append(where[0] + 1)
    insist(sum(len(page.images) for page in reader.pages) == len(matched), "Unexpected screen in report")
    return matched


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
    audit_text = "\n".join([complete_text, *(str(v) for v in reader.metadata.values()),
                           *(str(item.title) for item in bookmarks(reader.outline))])
    forbidden = re.search(r"WorkBuddy|Codex|ChatGPT|模拟|开发者|测试|\bAI\b|SITE_(?:SOURCE|REPORT|COMMIT|TIME)", audit_text, re.I)
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
    observed = json.loads((HERE / "验收记录.json").read_text())
    verify_appointment_readability(reader, pages, observed)
    verify_patient_navigation(reader, pages, observed["patient_navigation"])
    site_run = json.loads((HERE / observed["site_report_chain"]).read_text())
    pictures = verify_screens(reader, pages, observed["screen_sha256"] | site_run["screenshots"])
    compact = "".join(complete_text.split())
    site_bookmarks = [item for item in bookmarks(reader.outline) if item.title.startswith(("5.8", "5.9"))]
    insist(len(site_bookmarks) == 2, "The report publication and follow-up sections need bookmarks")
    site_pages = "".join("".join(pages[reader.get_destination_page_number(item)].split()) for item in site_bookmarks)
    facts = [site_run["runtime_identity"]["application_commit"][:12], site_run["clinic"],
             site_run["original"]["number"], site_run["report"]["number"], site_run["followup"]["number"],
             site_run["followup"]["beijing"][:16].replace("T", " "), site_run["followup"]["end_beijing"][11:16],
             f"就诊#{site_run['original']['id']}", f"提醒#{site_run['report']['notice']}",
             f"复诊#{site_run['followup']['id']}", f"第{site_run['report']['version']}版"]
    for fact in facts:
        insist("".join(fact.split()) in site_pages, f"Cross-role observation missing from final pages: {fact}")
    read = site_run["read_observation"]
    insist([read["unread_after_" + key] for key in ("publication", "view", "explicit_read")] == [1, 1, 0],
           "Observed read transition differs from the patient result")
    insist(site_run["original"]["status"] == "CHECKED_IN" and site_run["followup"]["status"] == "SCHEDULED",
           "Observed visit status differs from the stated result")
    effects = site_run["data_effects"]
    insist(all(effects[k] == 1 for k in ("report_versions", "publication_notices", "followup_receipts"))
           and all(effects[k] == 0 for k in ("new_invoices", "new_payments", "new_treatments")),
           "Report observations differ from recorded data effects")
    server_run = json.loads((HERE / observed["server_report_chain"]).read_text())
    server_mark = next(item for item in bookmarks(reader.outline) if item.title.startswith("5.10"))
    server_page = "".join(pages[reader.get_destination_page_number(server_mark)].split())
    server_trip = server_run["patient_journey"]
    server_scope = server_run["server_scope"]
    server_roles = server_run["three_role_checks"]
    insist(server_run["source_commit"] == site_run["runtime_identity"]["application_commit"] and
           server_run["settings"] == "config.settings.production" and server_scope["private_internal_network"] and
           server_scope["new_database_in_tmpfs"] and not server_scope["public_teacher_entry_changed"] and
           not server_scope["public_https_path_exercised"], "The two installations or their stated scope differs")
    insist(all(flag is True for key, flag in server_roles.items() if key != "前台报告正文HTTP状态") and
           server_roles["前台报告正文HTTP状态"] == 403 and server_trip["status"] == "SCHEDULED",
           "Hosted role projections differ from the report")
    server_facts = ["香港服务器", server_trip["followup_visit"][-8:], server_trip["followup_start"][:16].replace("T", ""),
                    str(server_roles["前台报告正文HTTP状态"]), "公网入口仍为原版本"]
    insist(all(fact in server_page for fact in server_facts), "Hosted follow-up facts missing from section 5.10")
    insist(server_trip["source_visit"] != site_run["original"]["number"] and
           server_trip["followup_visit"][-8:] not in site_pages and site_run["followup"]["number"] not in server_page,
           "The two encounters have been mixed")
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
            "editable_vector_figures": len(diagrams), "screen_pages": sorted(set(pictures)), "verified_screen_images": len(pictures),
            "embedded_songti_fonts": sorted({f.split("+")[-1] for f in embedded if "Songti" in f})}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", nargs="?", type=Path, default=TARGET)
    report = verify(parser.parse_args().pdf)
    print(json.dumps(report, ensure_ascii=False, indent=2))
