"""Character-level, reviewable transcript edits; original audio never changes."""
from copy import deepcopy
from difflib import SequenceMatcher
import re
from uuid import uuid4
from . import workflow

SAFE_STUTTERS = re.compile(r"选{3,}(?=项)|问{3,}(?=题)|讨{3,}(?=论)|现{3,}(?=象)|意{3,}(?=向性)")


def context(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ValueError("校对背景须为对象。")
    result = {}
    for key, limit in (("topic", 3000), ("terms", 6000)):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > limit:
            raise ValueError("话题或术语说明过长。")
        result[key] = text.strip()
    result["auto_stutter"] = value.get("auto_stutter", True) is True
    return result


def diff(before, after):
    # autojunk=False is important for repeated Chinese characters. Work is
    # bounded per segment by the parser's 16k limit; no document-wide diff.
    if before == after:
        return [("equal", before, after, 0, len(before))]
    if len(before) * len(after) > 4_000_000:
        # First strip common prefix/suffix to avoid quadratic whole-paragraph
        # comparison for large repeated text. The middle remains one edit.
        prefix = 0
        while prefix < min(len(before), len(after)) and before[prefix] == after[prefix]: prefix += 1
        suffix = 0
        while suffix < min(len(before), len(after)) - prefix and before[-1-suffix] == after[-1-suffix]: suffix += 1
        end_b, end_a = len(before)-suffix, len(after)-suffix
        parts = [("equal", before[:prefix], after[:prefix], 0, prefix)] if prefix else []
        parts.append(("replace", before[prefix:end_b], after[prefix:end_a], prefix, end_b))
        if suffix: parts.append(("equal", before[end_b:], after[end_a:], end_b, len(before)))
        return parts
    return [(tag, before[a:b], after[c:d], a, b) for tag, a, b, c, d in SequenceMatcher(None, before, after, autojunk=False).get_opcodes()]


def compose(row, states=("accepted",)):
    value, cursor = "", 0
    for edit in row["edits"]:
        value += row["before"][cursor:edit["start"]]
        value += edit["after"] if edit["status"] in states else edit["before"]
        cursor = edit["end"]
    return value + row["before"][cursor:]


def is_stutter(before, after):
    return any(before[:m.start()] + m.group()[0] + before[m.end():] == after for m in SAFE_STUTTERS.finditer(before))


def build(item, result, cfg, at):
    sources = {row["id"]: row for row in item["segments"]}
    rows = []
    proposals = {row["source_id"]: row for row in result.get("corrections", [])}
    # Local rule is limited to repeated characters inside these compounds.
    # Never deduplicate arbitrary sentences, negations, numbers or laughter.
    for sid, source in sources.items():
        proposal = proposals.get(sid)
        before = source["text"]
        after = proposal["after"] if proposal else before
        if cfg["auto_stutter"] and not source.get("asr_issue"):
            after = SAFE_STUTTERS.sub(lambda match: match.group()[0], after)
        edits = []
        for tag, old, new, start, end in diff(before, after):
            if tag == "equal": continue
            candidate = before[:start] + new + before[end:]
            mechanical = is_stutter(before, candidate)
            uncertain = not mechanical and ((proposal or {}).get("certainty", "uncertain") != "high" or (proposal or {}).get("needs_audio") is True)
            edits.append({"id": "edit-" + uuid4().hex, "start": start, "end": end, "before": old, "after": new,
                "status": "accepted" if mechanical and cfg["auto_stutter"] else "pending", "uncertain": uncertain,
                "mechanical": mechanical, "auto_applied": mechanical and cfg["auto_stutter"],
                "reason": "明确词内口吃清理；可撤销。" if mechanical else (proposal or {}).get("reason", "文字推测，需要回听核对。"),
                "needs_audio": uncertain or (proposal or {}).get("needs_audio") is True})
        if edits:
            rows.append({"source_id": sid, "before": before, "edits": edits})
    return {"id": "proof-" + uuid4().hex, "created_at": at, "model": result.get("model", ""),
        "context": cfg, "rows": rows, "flags": deepcopy(result.get("flags", [])),
        "baseline_segments": deepcopy(item["segments"]), "review_log": [],
        "warning": "仅凭文字推测，未核验录音；蓝色建议不是确定原话。校订稿只包含已接受的修改。"}


def install(item, session):
    previous = item.get("proofreading")
    if previous:
        item.setdefault("proofreading_history", []).append(deepcopy(previous))
    item["proofreading"] = session
    item["proofreading_context"] = session["context"]
    changed = set()
    by_id = {row["id"]: row for row in item["segments"]}
    for row in session["rows"]:
        text = compose(row)
        if text != by_id[row["source_id"]]["text"]:
            target = by_id[row["source_id"]]
            target.setdefault("original_text", target["text"])
            target.update(text=text, review_status="needs_review")
            changed.add(row["source_id"])
    invalidate_notes(item, changed)


def invalidate_notes(item, ids):
    for note in item.get("notes", []):
        if set(note.get("source_ids", [])).intersection(ids):
            note["review_status"] = "needs_review"


def review(item, body, at):
    session = item.get("proofreading")
    if not session or body.get("session_id") != session["id"]:
        raise ValueError("校对批次已改变，请刷新后重试。")
    action = body.get("action")
    if action not in {"accept", "reject", "undo"}:
        raise ValueError("请选择接受、拒绝或撤销修改。")
    ids = body.get("edit_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(sid, str) for sid in ids) or len(ids) != len(set(ids)):
        raise ValueError("请选择有效且不重复的修改编号。")
    lookup = {edit["id"]: (row, edit) for row in session["rows"] for edit in row["edits"]}
    by_id = {row["id"]: row for row in item["segments"]}
    if any(sid not in lookup for sid in ids):
        raise ValueError("修改已不存在，请刷新。")
    rows = {lookup[sid][0]["source_id"]: lookup[sid][0] for sid in ids}
    stale = {sid for sid,row in rows.items() if sid not in by_id or compose(row)!=by_id[sid]["text"]}
    for sid, row in rows.items():
        if sid in stale and action != "reject":
            raise ValueError("这句原文已被人工或局部补转修改，旧建议未覆盖它；请重新校对这段。")
    for sid in ids:
        row, edit = lookup[sid]
        if action != "undo" and edit["status"] != "pending" or action == "undo" and edit["status"] != "accepted":
            raise ValueError("所选修改的状态已改变，请刷新。")
    for sid in ids:
        lookup[sid][1]["status"] = {"accept": "accepted", "reject": "rejected", "undo": "rejected"}[action]
        lookup[sid][1]["auto_applied"] = False if action == "undo" else lookup[sid][1].get("auto_applied", False)
    changed = set()
    for sid, row in rows.items():
        if sid in stale: continue  # Rejecting stale suggestions never writes text.
        value = compose(row)
        if value != by_id[sid]["text"]:
            by_id[sid].setdefault("original_text", by_id[sid]["text"])
            by_id[sid].update(text=value, review_status="needs_review")
            changed.add(sid)
    session["review_log"].append({"action": action, "edit_ids": ids, "at": at})
    invalidate_notes(item, changed)


def public_session(item):
    value = deepcopy(item.get("proofreading"))
    if not value: return None
    by_id = {row["id"]: row for row in item["segments"]}
    for row in value["rows"]:
        row["stale"] = row["source_id"] not in by_id or compose(row) != by_id[row["source_id"]]["text"]
    return value


def original_segments(item):
    session = item.get("proofreading")
    return deepcopy(session["baseline_segments"]) if session else [{**row, "text": row.get("original_text", row["text"])} for row in item["segments"]]


def annotated_runs(item, source_id, include_automatic=False):
    """Mark accepted edits against the snapshot, plus pending proposals. Rejected
    edits disappear. Manually changed rows show a diff but no actionable IDs."""
    segment = next(row for row in item["segments"] if row["id"] == source_id)
    session = item.get("proofreading")
    row = next((row for row in (session or {}).get("rows", []) if row["source_id"] == source_id), None)
    if not row: return [{"kind": "text", "text": segment["text"]}]
    if compose(row) != segment["text"]:
        runs = []
        for tag, old, new, *_ in diff(row["before"], segment["text"]):
            if tag == "equal": runs.append({"kind":"text", "text":old})
            else:
                if old: runs.append({"kind":"delete", "text":old, "status":"manual"})
                if new: runs.append({"kind":"insert", "text":new, "status":"manual"})
        return runs
    runs, cursor = [], 0
    for edit in row["edits"]:
        if edit["start"] > cursor: runs.append({"kind":"text", "text":row["before"][cursor:edit["start"]]})
        if edit["status"] == "rejected" or edit.get("auto_applied") and not include_automatic:
            runs.append({"kind":"text", "text":edit["after"] if edit["status"] == "accepted" else edit["before"]})
        else:
            for kind, text in (("delete",edit["before"]),("insert",edit["after"])):
                if text: runs.append({"kind":kind,"text":text,"edit_id":edit["id"],"status":edit["status"],"uncertain":edit["uncertain"]})
        cursor = edit["end"]
    runs.append({"kind":"text","text":row["before"][cursor:]})
    return runs
