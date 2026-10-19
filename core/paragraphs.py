"""Deterministic reading layout, matching static/paragraphs.js. Sources stay intact."""
from copy import deepcopy
import math
import re


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def group(segments):
    groups, current, size = [], [], 0
    for row in segments:
        previous = current[-1] if current else None
        duration = row["start"] - current[0]["start"] if previous and _finite(row.get("start")) and _finite(current[0].get("start")) else 0
        pause = row["start"] - previous["end"] if previous and _finite(row.get("start")) and _finite(previous.get("end")) else 0
        if previous and (row.get("asr_issue") or previous.get("asr_issue") or row.get("speaker") != previous.get("speaker") or pause > 4 or size >= 550 or duration >= 120 or (size >= 240 and re.search(r'''[。！？.!?][”’"']?$''', previous["text"].strip()))):
            groups.append(current)
            current, size = [], 0
        current.append(row)
        # Match JavaScript UTF-16 string length, including emoji.
        size += len(row["text"].encode("utf-16-le", errors="surrogatepass")) // 2
        if row.get("asr_issue"):
            groups.append(current)
            current, size = [], 0
    if current:
        groups.append(current)
    return groups


def separator(before, after):
    return " " if before and not before[-1].isspace() and re.search(r'''[A-Za-zÀ-ỹ0-9][.!?,;:)\]”’"'»…\s]*$''', before) and re.match(r'''[\[(“‘"'«]*[A-Za-zÀ-ỹ0-9]''', after) else ""


def blocks(rows, layout="reading"):
    """Merge only presentation runs, keeping source IDs and exact time bounds."""
    if layout not in {"reading", "timeline"}:
        raise ValueError("请选择阅读段落或逐句时间线。")
    result = []
    for sources in group(rows) if layout == "reading" else [[row] for row in rows]:
        first, last = sources[0], sources[-1]
        block = {"id": first["id"], "source_ids": [row["id"] for row in sources],
                 "start": first.get("start"), "end": last.get("end"), "speaker": first.get("speaker", ""),
                 "asr_issue": bool(first.get("asr_issue")), "text": "", "runs": [], "issues": []}
        before = ""
        for row in sources:
            space = separator(before, row["text"]) if before else ""
            if space:
                block["runs"].append({"kind": "text", "text": space})
            block["text"] += space + row["text"]
            block["runs"].extend(deepcopy(row.get("runs", [{"kind": "text", "text": row["text"]}])))
            block["issues"].extend(deepcopy(row.get("issues", [])))
            before = row["text"]
        result.append(block)
    return result


def reading_text(segments):
    return "\n\n".join(row["text"] for row in blocks(segments))
