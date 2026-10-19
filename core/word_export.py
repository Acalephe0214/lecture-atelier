"""Readable, editable DOCX export using only stdlib ZIP and OOXML."""
from io import BytesIO
import zipfile
from xml.sax.saxutils import escape
from .pipeline import _stamp

NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def text(value):
    value = str(value or "")
    return escape("".join(c if c in "\t\n\r" or 0x20 <= ord(c) <= 0xD7FF or 0xE000 <= ord(c) <= 0xFFFD or 0x10000 <= ord(c) <= 0x10FFFF else "\ufffd" for c in value))


def paragraph(value, style="Normal"):
    runs = '<w:r><w:t xml:space="preserve">' + text(value).replace("\n", '</w:t><w:br/><w:t xml:space="preserve">') + '</w:t></w:r>'
    return '<w:p><w:pPr><w:pStyle w:val="' + style + '"/></w:pPr>' + runs + '</w:p>'


def export_docx(lecture, course_name="", english=False):
    tr=lambda zh,en:en if english else zh
    stamp=lambda value:"No timestamp" if english and value is None else _stamp(value)
    meeting = lecture.get("generation", {}).get("scene", lecture.get("workflow", {}).get("scene")) == "meeting"
    parts = [paragraph(tr("会议总结与详细笔记","Meeting overview and detailed notes") if meeting else tr("课堂总结与详细笔记","Lecture overview and detailed notes"), "Title"), paragraph(lecture.get("title", ""), "Subtitle"), paragraph(f"{course_name}    {lecture.get('date', '')}", "Source")]
    parts.append(paragraph(tr("请先核对以下总结与原文，再将其作为正式记录。来源编号和时间用于定位，不代表观点或决定已经核实。","Check this summary against its sources before treating it as an official record. Source IDs and times locate evidence; they do not verify views or decisions.")))
    summary = lecture.get("overview")
    if summary:
        parts.append(paragraph(tr("总结总览","Overview"), "Heading1"))
        if summary.get("stale"):
            parts.append(paragraph(tr("原文或笔记已修改 此总览需要重新核对","Source or notes changed. This overview needs review."), "Heading2"))
        intro = summary["summary"]
        parts.append(paragraph(intro["content"]))
        def citations(row):
            by_id = {segment["id"]: segment for segment in lecture.get("segments", [])}
            return tr("来源：","Sources: ") + "; ".join(sid + " " + stamp(by_id.get(sid, {}).get("start")) for sid in row.get("source_ids", []))
        parts.append(paragraph(citations(intro), "Source"))
        for name, label, empty in [("decisions", "最终决策", "未提取到有明确原文依据的最终决策。"), ("actions", "行动事项", "未提取到明确的行动事项。"), ("key_points", "最重要的信息", "暂无单列重点。"), ("open_questions", "未决问题与风险", "未提取到单列未决问题；不代表全部问题已经解决。")]:
            if not meeting and name in {"decisions", "actions"} and not summary.get(name):
                continue
            labels={"decisions":("Final decisions","No final decisions with explicit source evidence were extracted."),"actions":("Action items","No explicit action items were extracted."),"key_points":("Key information","No separate key points."),"open_questions":("Open questions and risks","No separate open questions were extracted; this does not mean every issue is resolved.")}
            parts.append(paragraph(tr(label,labels[name][0]), "Heading2"))
            rows = summary.get(name, [])
            if not rows:
                parts.append(paragraph(tr(empty,labels[name][1])))
            for row in rows:
                parts.append(paragraph(row["title"], "Heading3"))
                parts.append(paragraph(row["content"]))
                if row.get("evidence_quote"):
                    parts.append(paragraph(tr("原文依据：","Source evidence: ") + row["evidence_quote"]))
                parts.append(paragraph(citations(row), "Source"))
    else:
        parts.extend([paragraph(tr("总结总览","Overview"), "Heading1"), paragraph(tr("尚未生成独立的全局总结。以下保留当前笔记，不将逐句摘录冒充总结。","No independent overview has been generated. Current notes follow; source excerpts are not a summary."))])
    parts.append(paragraph(tr("详细笔记","Detailed notes"), "Heading1"))
    mode = lecture.get("generation", {}).get("mode")
    if mode == "local":
        parts.append(paragraph(tr("以下是原文复制卡片 不是人工校订后的独立版本或 AI 总结","The following are source-copy cards, not an independently revised transcript or AI summary."), "Heading2"))
    by_id = {row["id"]: row for row in lecture.get("segments", [])}
    for index, row in enumerate(lecture.get("notes", []), 1):
        parts.append(paragraph(f"{index}  {row['title']}", "Heading2"))
        parts.append(paragraph(row["content"]))
        status = {"unreviewed":tr("未核查","Unreviewed"),"verified":tr("已核查","Verified"),"needs_review":tr("待复核","Needs review")}.get(row.get("review_status"),tr("未核查","Unreviewed"))
        source = "; ".join(sid + " " + stamp(by_id.get(sid, {}).get("start")) for sid in row.get("source_ids", []))
        parts.append(paragraph(status + tr("  来源：","  Sources: ") + source, "Source"))
    if not lecture.get("notes"):
        parts.append(paragraph(tr("暂无详细笔记。完整转写请另行导出 TXT、JSON 或字幕。","No detailed notes. Export TXT, JSON or subtitles for the full transcript.")))
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="' + NS + '"><w:body>' + "".join(parts) + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/></w:sectPr></w:body></w:document>'
    styles = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="' + NS + '"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Songti SC"/><w:sz w:val="23"/><w:color w:val="000000"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="100" w:line="280" w:lineRule="auto"/><w:widowControl/></w:pPr></w:pPrDefault></w:docDefaults>'
    for identity, size, before, after, bold in [("Normal", 23, 0, 100, False), ("Title", 40, 0, 180, False), ("Subtitle", 25, 0, 140, False), ("Heading1", 32, 240, 120, True), ("Heading2", 27, 180, 100, True), ("Heading3", 24, 140, 80, True), ("Source", 20, 0, 100, False)]:
        outline = '<w:outlineLvl w:val="' + identity[-1:].replace("1", "0").replace("2", "1").replace("3", "2") + '"/>' if identity.startswith("Heading") else ""
        styles += f'<w:style w:type="paragraph" w:styleId="{identity}"><w:name w:val="{identity}"/>' + ('<w:basedOn w:val="Normal"/>' if identity != "Normal" else '') + f'<w:pPr><w:spacing w:before="{before}" w:after="{after}"/>' + ('<w:keepNext/>' if identity.startswith("Heading") or identity in {"Title", "Subtitle"} else '') + outline + f'</w:pPr><w:rPr><w:color w:val="000000"/><w:sz w:val="{size}"/>' + ('<w:b/>' if bold else '') + '</w:rPr></w:style>'
    styles += '</w:styles>'
    types = '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>'
    rels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    docrels = '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, value in {"[Content_Types].xml": types, "_rels/.rels": rels, "word/document.xml": document, "word/styles.xml": styles, "word/_rels/document.xml.rels": docrels}.items():
            archive.writestr(name, value.encode("utf-8"))
    return output.getvalue()
