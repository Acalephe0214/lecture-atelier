"""Three distinct transcript editions; no AI or network call during export."""
from copy import deepcopy
from io import BytesIO
import json
import zipfile
from html import escape
from . import redline, pipeline, paragraphs
from .word_export import paragraph, text, NS


def data(item, version, english=False, layout="reading", timestamps=False):
    if version not in {"original","marked","clean"}: raise ValueError("请选择校对前、带修订标记或已接受修改后的校订稿。")
    tr=lambda zh,en:en if english else zh
    descriptions={"original":tr("本轮校对前原稿", "Transcript before this proofreading pass"),
        "marked":tr("带修订标记稿", "Transcript with revision marks"),
        "clean":tr("校订稿 仅含已接受修改", "Revised transcript with accepted edits only")}
    explanation=tr("红色删除线为原文，蓝色为修改；问号表示推测。包含已接受及待确认建议，不含已拒绝建议。口吃清理也保留标记。", "Red strikeout is deleted text; blue is a change. Question marks flag guesses. Includes accepted edits and pending proposals, but not rejected proposals. Automatic stutter cleanup is marked too.") if version=="marked" else tr("仅为文字校对记录，不代表已经核验录音。校订稿不包含未接受的 AI 修改。", "A text proofreading record, not verification of the recording. Unaccepted AI edits are excluded from the revised transcript.")
    if version=="original": explanation=tr("此快照保存于本轮 AI 校对开始前；不是录音文件。更早的人工修改和历史校对仍保存在完整 JSON 的历史中。", "Snapshot from before this AI proofreading pass, not the audio file. Earlier manual edits and proofreading remain in full JSON history.")
    segments=redline.original_segments(item) if version=="original" else deepcopy(item["segments"])
    rows=[]
    for segment in segments:
        runs=redline.annotated_runs(item,segment["id"],include_automatic=True) if version=="marked" else [{"kind":"text","text":segment["text"]}]
        issues=[flag for flag in item.get("proofreading",{}).get("flags",[]) if flag["source_id"]==segment["id"]] if version=="marked" else []
        rows.append({**segment,"runs":runs,"issues":issues})
    return {"title":item["title"],"edition":descriptions[version],"notice":explanation,"version":version,"rows":rows,"blocks":paragraphs.blocks(rows,layout),"layout":layout,"timestamps":bool(timestamps),"date":item.get("date",""),"english":english}


def source_label(document, row):
    parts = [row["id"]] if document["layout"] == "timeline" else []
    if document["layout"] == "timeline" or document["timestamps"]:
        if row.get("start") is not None:
            parts.append(pipeline._stamp(row["start"]))
    if row.get("speaker"):
        parts.append(row["speaker"])
    return "  ".join(parts)


def run_html(runs, pdf=False, english=False):
    parts=[]
    for run in runs:
        value=escape(run["text"]).replace('\n','<br/>' if pdf else '<br>')
        if run["kind"]=="delete": value=('<strike><font color="#b03c3c">'+value+'</font></strike>') if pdf else '<del>'+value+'</del>'
        if run["kind"]=="insert": value=('<font color="#245ba8"><u>'+value+'</u></font>') if pdf else '<ins>'+value+'</ins>'
        if run.get("uncertain") and (run["kind"]=="insert" or not any(r.get("edit_id")==run.get("edit_id") and r["kind"]=="insert" for r in runs)):
            label="(? listen back)" if english else "（？待回听）"
            value += '<font color="#886018"> '+label+'</font>' if pdf else '<span class="uncertain">'+label+'</span>'
        parts.append(value)
    return ''.join(parts)


def docx(document):
    notice="Word uses native tracked changes; displayed colors follow the reader's revision settings. Strikeout marks deleted text, underlining marks insertions, and question marks flag guesses." if document.get("english") else "Word 使用原生修订，显示颜色随阅读器的修订设置而定。删除线为原文，下划线为修改，问号表示推测；包含已接受及待确认建议，不含已拒绝建议。"
    parts=[paragraph(document["title"],"Title"),paragraph(document["edition"],"Subtitle"),paragraph(notice if document["version"]=="marked" else document["notice"])]
    count=0
    for row in document["blocks"]:
        label = source_label(document, row)
        if label: parts.append(paragraph(label,"Source"))
        runs=[]
        for run in row["runs"]:
            value=text(run["text"])
            def make_run(value,deleted=False,color="000000"):
                tag='w:delText' if deleted else 'w:t'
                return f'<w:r><w:rPr><w:color w:val="{color}"/></w:rPr><{tag} xml:space="preserve">'+value.replace('\n',f'</{tag}><w:br/><{tag} xml:space="preserve">')+f'</{tag}></w:r>'
            if run["kind"]=="text": runs.append(make_run(value))
            else:
                count+=1;deleted=run["kind"]=="delete";tag="w:del" if deleted else "w:ins"
                runs.append(f'<{tag} w:id="{count}" w:author="AI proofreading">'+make_run(value,deleted,"B03C3C" if deleted else "245BA8")+f'</{tag}>')
                if run.get("uncertain") and run["kind"]=="insert": runs.append(make_run("(? listen back)" if document["english"] else "（？待回听）",color="886018"))
        parts.append('<w:p><w:pPr><w:pStyle w:val="Normal"/></w:pPr>'+''.join(runs)+'</w:p>')
        for issue in row.get("issues",[]): parts.append(paragraph("？ "+issue["reason"]+(' '+issue["query_terms"] if issue.get("query_terms") else ''),"Source"))
    document_xml='<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="'+NS+'"><w:body>'+''.join(parts)+'<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080"/></w:sectPr></w:body></w:document>'
    styles='<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="'+NS+'"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Songti SC"/><w:sz w:val="23"/><w:color w:val="000000"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="140" w:line="300" w:lineRule="auto"/><w:widowControl/></w:pPr></w:pPrDefault></w:docDefaults>'
    for name,size in (("Normal",23),("Title",38),("Subtitle",25),("Source",19)):
        styles+=f'<w:style w:type="paragraph" w:styleId="{name}"><w:name w:val="{name}"/><w:pPr>'+('<w:keepNext/>' if name!="Normal" else '')+f'</w:pPr><w:rPr><w:sz w:val="{size}"/><w:color w:val="000000"/></w:rPr></w:style>'
    styles+='</w:styles>'
    settings='<?xml version="1.0" encoding="UTF-8"?><w:settings xmlns:w="'+NS+'"><w:revisionView w:markup="true" w:insDel="true"/>'+('<w:trackRevisions/>' if document["version"]=="marked" else '')+'</w:settings>'
    types='<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>'+''.join(f'<Override PartName="/word/{name}.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>' for name,kind in (("document","document.main"),("styles","styles"),("settings","settings")))+'</Types>'
    relroot='http://schemas.openxmlformats.org/package/2006/relationships'
    rels=f'<Relationships xmlns="{relroot}"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
    docrels=f'<Relationships xmlns="{relroot}">'+''.join(f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/{name}" Target="{name}.xml"/>' for idx,name in enumerate(("styles","settings"),1))+'</Relationships>'
    output=BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for filename,value in {"[Content_Types].xml":types,"_rels/.rels":rels,"word/document.xml":document_xml,"word/styles.xml":styles,"word/settings.xml":settings,"word/_rels/document.xml.rels":docrels}.items(): archive.writestr(filename,value.encode())
    return output.getvalue()


def export(item,version="clean",format="docx",english=False,layout="reading",timestamps=False):
    document=data(item,version,english,layout,timestamps)
    if format=="docx": return docx(document),"application/vnd.openxmlformats-officedocument.wordprocessingml.document","docx"
    if format=="pdf":
        from .pdf_export import export_pdf
        sections=[("h2",escape(document["edition"])),("notice",escape(document["notice"]))]
        for row in document["blocks"]:
            label = source_label(document, row)
            if label: sections.append(("source",escape(label)))
            sections.append(("body",run_html(row["runs"],pdf=True,english=english)))
            for issue in row.get("issues",[]): sections.append(("notice",escape("？ "+issue["reason"])))
        return export_pdf(item,"",english,rich_sections=sections),"application/pdf","pdf"
    if format=="json": return json.dumps(document,ensure_ascii=False,indent=2).encode(),"application/json; charset=utf-8","json"
    if format=="srt":
        if version=="marked": raise ValueError("SRT 不支持修订标记；请选择原稿或校订稿，或改用 Word / PDF / HTML。")
        return pipeline.export_srt(document["rows"]).encode(),"application/x-subrip; charset=utf-8","srt"
    if format=="html":
        html='<!doctype html><html><meta charset="utf-8"><title>'+escape(document["title"])+'</title><style>body{max-width:760px;margin:50px auto;padding:0 25px;background:#fffef9;color:#243b34;font:17px/1.95 system-ui}h1{font-size:30px}small{color:#758575}del{color:#b03c3c;background:#fff1ec}ins{color:#245ba8;background:#edf4ff;text-decoration:underline}.uncertain{color:#886018}section{margin:24px 0}</style><h1>'+escape(document["title"])+'</h1><h2>'+escape(document["edition"])+'</h2><p>'+escape(document["notice"])+'</p>'
        for row in document["blocks"]:
            label = source_label(document, row)
            html+='<section>'+('<small>'+escape(label)+'</small>' if label else '')+'<p>'+run_html(row["runs"],english=english)+'</p>'+''.join('<p class="uncertain">？ '+escape(issue['reason'])+'</p>' for issue in row.get('issues',[]))+'</section>'
        return (html+'</html>').encode(),"text/html; charset=utf-8","html"
    if format not in {"txt","md"}: raise ValueError("不支持这种校对稿导出格式。")
    lines=[document["title"],document["edition"],document["notice"],""]
    for row in document["blocks"]:
        value=''
        for run in row["runs"]:
            part=run["text"]
            if run["kind"]=="delete": part='~~'+part+'~~' if format=="md" else '[-'+part+'-]'
            if run["kind"]=="insert": part='**'+part+'**' if format=="md" else '[+'+part+'+]'
            if run.get("uncertain") and run["kind"]=="insert": part+='(? listen back)' if english else '（？待回听）'
            value+=part
        label = source_label(document, row)
        if label: lines.append(label)
        lines.extend([value,""])
        for issue in row.get("issues",[]): lines.extend(['？ '+issue["reason"],""])
    return '\n'.join(lines).encode(),("text/markdown" if format=="md" else "text/plain")+"; charset=utf-8",format
