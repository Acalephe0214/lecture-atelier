"""Local ReportLab PDF, with embedded system fonts when supported."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
import os
import threading
from .delivery import sections

_lock = threading.RLock()


def export_pdf(item, course_name="", english=False, rich_sections=None):
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
    except ImportError:
        raise ValueError("PDF 导出需要 ReportLab。请先运行 setup-mac.command 或 setup-windows.bat 安装本项目依赖。") from None
    # Do not redistribute system fonts. ReportLab embeds glyph subsets inside
    # the document. A viewer-provided CJK font is the final fallback only.
    with _lock:
        font = "LectureCJK"
        if font not in pdfmetrics.getRegisteredFontNames():
            candidates = [Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf"),
                Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/msyh.ttc",
                Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/simsun.ttc",
                Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")]
            for path in candidates:
                if path.is_file():
                    try:
                        pdfmetrics.registerFont(TTFont(font, str(path), subfontIndex=0))
                        break
                    except Exception:
                        continue
            else:
                font = "STSong-Light"
                if font not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(UnicodeCIDFont(font))
        ink, green, sage = colors.HexColor("#243b34"), colors.HexColor("#315c4b"), colors.HexColor("#728372")
        styles = {}
        for name, size, leading, before, after, color in [("title", 25, 36, 0, 12, ink), ("h1", 17, 25, 22, 10, green), ("h2", 13, 21, 14, 7, green), ("h3", 11.5, 19, 10, 5, ink), ("body", 10.5, 18, 0, 8, ink), ("source", 8, 13, 0, 9, sage), ("notice", 9, 15, 0, 14, sage), ("quote", 10, 17, 0, 8, green)]:
            styles[name] = ParagraphStyle(name, fontName=font, fontSize=size, leading=leading, spaceBefore=before,
                spaceAfter=after, textColor=color, alignment=TA_LEFT, wordWrap="CJK", splitLongWords=True,
                keepWithNext=name in {"title", "h1", "h2", "h3"}, leftIndent=12 if name == "quote" else 0)
        output = BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=54, leftMargin=54, topMargin=60, bottomMargin=57,
            title=item.get("title", "Lecture Atelier"), author="Lecture Atelier", pageCompression=1)
        safe = lambda value: escape(str(value or "")).replace("\n", "<br/>")
        story = [Paragraph("LECTURE ATELIER  /  FIELD NOTES", styles["source"]),
            Paragraph(safe(item.get("title", "")), styles["title"]),
            Paragraph(safe("  ·  ".join(part for part in (course_name,item.get("date","")) if part)), styles["source"]),
            HRFlowable(width="100%", thickness=.7, color=colors.HexColor("#ccd5c6")), Spacer(1, 15)]
        for kind, value in rich_sections if rich_sections is not None else sections(item, english):
            story.append(Paragraph(value if rich_sections is not None else safe(value), styles[kind]))
        def page(canvas, document):
            canvas.saveState()
            canvas.setFillColor(colors.HexColor("#fffef9")); canvas.rect(0, 0, *A4, fill=1, stroke=0)
            canvas.setStrokeColor(colors.HexColor("#ccd5c6")); canvas.line(54, 42, A4[0] - 54, 42)
            canvas.setFillColor(sage); canvas.setFont(font, 8)
            canvas.drawString(54, 28, "LECTURE ATELIER  ·  PRIVATE NOTES")
            canvas.drawRightString(A4[0] - 54, 28, str(document.page))
            canvas.restoreState()
        doc.build(story, onFirstPage=page, onLaterPages=page)
        return output.getvalue()
