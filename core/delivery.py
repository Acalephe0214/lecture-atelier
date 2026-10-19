"""Shared, source-cited document structure. No transcript or key in exports."""
from .pipeline import _stamp


def sections(item, english=False):
    tr = lambda zh, en: en if english else zh
    by_id = {row["id"]: row for row in item.get("segments", [])}
    result = [("notice", tr("AI 整理内容仍需核对。出处可定位原文，不代表结论已经证实。", "AI-generated notes need review. Citations locate evidence; they do not verify conclusions."))]
    def add(row, heading=3):
        result.extend([(f"h{heading}", row.get("title", "")), ("body", row.get("content", ""))])
        if row.get("evidence_quote"):
            result.append(("quote", tr("原文依据：", "Source quote: ") + row["evidence_quote"]))
        refs = " · ".join(sid + " " + _stamp(by_id.get(sid, {}).get("start")) for sid in row.get("source_ids", []))
        if refs:
            result.append(("source", tr("出处：", "Sources: ") + refs))
    overview = item.get("overview")
    result.append(("h1", tr("总结总览", "Executive overview")))
    if overview:
        if overview.get("stale"):
            result.append(("notice", tr("原文或笔记已改变；此总览需要重新核对。", "Source or notes changed; this overview may be outdated.")))
        add(overview["summary"], 2)
        for key, zh, en in [("decisions", "最终决策", "Final decisions"), ("actions", "行动事项", "Action items"), ("key_points", "重点信息", "Key information"), ("open_questions", "未决问题与风险", "Open questions & risks")]:
            if overview.get(key):
                result.append(("h2", tr(zh, en)))
                for row in overview[key]:
                    add(row)
        if item.get("workflow", {}).get("scene") == "meeting" and not overview.get("decisions"):
            result.append(("body", tr("未提取到有明确原文依据的最终决策。", "No final decision with explicit source evidence was extracted.")))
    else:
        result.append(("body", tr("尚未生成独立总览。", "No independent overview has been generated.")))
    result.append(("h1", tr("详细笔记", "Detailed notes")))
    if item.get("generation", {}).get("mode") == "local":
        result.append(("notice", tr("以下为原句复制卡片，不是 AI 总结。", "The following are source copies, not AI summaries.")))
    for row in item.get("notes", []):
        add(row, 2)
        status = row.get("review_status", "unreviewed")
        result.append(("source", {"verified": tr("已核查", "Reviewed"), "needs_review": tr("待复核", "Needs review")}.get(status, tr("未核查", "Unreviewed"))))
    return result
