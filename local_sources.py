"""Read-only links to explicitly indexed local recordings and Markdown drafts.

Paths can only be registered by the local CLI, never by an HTTP request.
The database keeps a reviewable cache; original files are never modified.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import struct
import wave

from core import pipeline


class LocalSourceError(ValueError):
    pass


STAMP = re.compile(r"^\s*\*\*((?:\d{1,3}:)?\d{1,2}:\d{2})\*\*\s*$", re.MULTILINE)
TRANSCRIPT_HEADING = re.compile(r"^##\s+录音转写\s*$", re.MULTILINE)
SECTION = re.compile(r"^#{1,3}\s+", re.MULTILINE)
KINDS = {"audio": "课堂录音", "transcript": "文字初校稿", "reference": "整理附记"}
MAX_DRAFT_BYTES = 8 * 1024 * 1024


def snapshot(path, kind):
    try:
        source = Path(path).expanduser().resolve(strict=True)
        info = source.stat()
    except (OSError, RuntimeError):
        raise LocalSourceError("索引原文件不存在或无法读取，请检查本机文件位置。") from None
    if not stat.S_ISREG(info.st_mode):
        raise LocalSourceError("索引目标须是普通文件。")
    return {"path": str(source), "name": source.name, "kind": kind,
            "size": info.st_size, "mtime_ns": info.st_mtime_ns}


def source_state(source):
    """Cheap status check. Do not read a 300MB recording just to list a lecture."""
    try:
        path = Path(source["path"])
        if not path.is_absolute() or str(path.resolve(strict=True)) != source["path"]:
            return "missing"
        current = path.stat()
        if not stat.S_ISREG(current.st_mode):
            return "missing"
        if current.st_size != source["size"] or current.st_mtime_ns != source["mtime_ns"]:
            return "changed"
        return "available"
    except (OSError, KeyError, TypeError, ValueError):
        return "missing"


def public_sources(item):
    sources = item.get("local_sources", {})
    output = []
    for key, source in sources.items():
        if key == "audio" and (item.get("audio") or {}).get("storage_kind") != "local_index":
            continue
        output.append({"key": key, "name": source.get("name", "本地文件"),
                       "kind": source.get("kind", key), "state": source_state(source)})
    return output


def linked_audio_path(item):
    source = item.get("local_sources", {}).get("audio")
    if not source:
        raise LocalSourceError("录音索引不存在，请重新登记本地文件。")
    status = source_state(source)
    if status == "missing":
        raise LocalSourceError("原录音已移走或无法读取；请恢复原路径，或重新登记索引。")
    if status == "changed":
        raise LocalSourceError("原录音已发生变化，请先在课次中检查并同步来源。")
    return Path(source["path"])


def read_draft(source):
    if source["size"] > MAX_DRAFT_BYTES:
        raise LocalSourceError("文字稿超过 8 MiB，请先按课次拆分。")
    path = Path(source["path"])
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        raise LocalSourceError("文字稿须为 UTF-8 Markdown 或文本。") from None
    if source_state(source) != "available":
        raise LocalSourceError("读取期间原稿发生变化，请稍后再同步。")
    return text


def seconds(label):
    parts = list(map(int, label.split(":")))
    if len(parts) not in (2, 3) or parts[-1] >= 60 or (len(parts) == 3 and parts[-2] >= 60):
        raise LocalSourceError("原稿时间码无效。")
    return parts[-1] + 60 * parts[-2] + (3600 * parts[0] if len(parts) == 3 else 0)


def parse_draft(text):
    """Only bold standalone timecodes are speech. Never turn summaries into speech."""
    explicit = TRANSCRIPT_HEADING.search(text)
    start = explicit.end() if explicit else 0
    first = STAMP.search(text, start)
    if not first:
        raise LocalSourceError("未找到独立加粗的录音时间码，未自动猜测段落。")
    end_heading = SECTION.search(text, first.end())
    stop = end_heading.start() if end_heading else len(text)
    body = text[first.start():stop]
    stamps = list(STAMP.finditer(body))
    rows = []
    for index, match in enumerate(stamps):
        end = stamps[index + 1].start() if index + 1 < len(stamps) else len(body)
        content = body[match.end():end].strip()
        if not content:
            raise LocalSourceError("时间码后没有正文，请检查原稿。")
        rows.append({"id": f"s{index + 1:04d}", "start": seconds(match.group(1)),
                     "end": None, "text": content})
    parsed = pipeline.parse_transcript(json.dumps({"segments": rows}, ensure_ascii=False), "json")
    return {**parsed, "preamble": text[:first.start()].strip(),
            "appendix": text[stop:].strip() if end_heading else ""}


def _boxes(handle, start, stop):
    position = start
    while position + 8 <= stop:
        handle.seek(position)
        header = handle.read(8)
        if len(header) < 8:
            break
        size, name = struct.unpack(">I4s", header)
        header_size = 8
        if size == 1:
            extended = handle.read(8)
            if len(extended) != 8:
                raise LocalSourceError("录音文件头不完整。")
            size = struct.unpack(">Q", extended)[0]
            header_size = 16
        elif size == 0:
            size = stop - position
        if size < header_size or position + size > stop:
            raise LocalSourceError("录音文件结构无效。")
        yield name, position + header_size, position + size
        position += size


def audio_metadata(path):
    """Read WAV or QuickTime/MP4 movie headers, skipping audio bytes; no ffmpeg required."""
    path = Path(path)
    if path.suffix.lower() == ".wav":
        with wave.open(str(path), "rb") as handle:
            return {"duration": handle.getnframes() / handle.getframerate(), "date": ""}
    if path.suffix.lower() not in {".m4a", ".mp4", ".mov", ".qt", ".qta", ".qat"}:
        raise LocalSourceError("本地索引暂支持 M4A、MP4、MOV、QTA 和 WAV 录音。")
    with path.open("rb") as handle:
        for name, left, right in _boxes(handle, 0, path.stat().st_size):
            if name != b"moov":
                continue
            for child, payload, _ in _boxes(handle, left, right):
                if child != b"mvhd":
                    continue
                handle.seek(payload)
                raw = handle.read(36)
                if len(raw) < 20:
                    raise LocalSourceError("录音时长信息不完整。")
                if raw[0] == 0:
                    created, _, scale, duration = struct.unpack(">IIII", raw[4:20])
                elif raw[0] == 1 and len(raw) >= 32:
                    created, _, scale, duration = struct.unpack(">QQIQ", raw[4:32])
                else:
                    raise LocalSourceError("不支持该录音文件头版本。")
                if not scale or not duration:
                    raise LocalSourceError("录音缺少有效时长。")
                date = ""
                if created:
                    moment = datetime(1904, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=created)
                    date = moment.astimezone(timezone(timedelta(hours=8))).date().isoformat()
                return {"duration": round(duration / scale, 3), "date": date}
    raise LocalSourceError("录音缺少可读取的 movie header。")


def prepare(entry):
    audio = snapshot(entry["audio_path"], "audio")
    transcript = snapshot(entry["transcript_path"], "transcript")
    metadata = audio_metadata(audio["path"])
    text = read_draft(transcript)
    parsed = parse_draft(text)
    if any(segment["start"] >= metadata["duration"] for segment in parsed["segments"]):
        raise LocalSourceError("文字稿时间码超出录音时长，未建立配对。")
    sources = {"audio": audio, "transcript": transcript}
    references = []
    for index, path in enumerate(entry.get("reference_paths", []), 1):
        source = snapshot(path, "reference")
        sources[f"reference-{index}"] = source
        references.append({"name": source["name"], "text": read_draft(source)})
    transcript["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if any(source_state(source) != "available" for source in sources.values()):
        raise LocalSourceError("索引期间来源文件发生变化，请稍后重试。")
    warnings = [
        "导入的是既有术语初校稿，未逐句人工听核；所有段落保持未核查，引用前请复听。",
        "原稿只标注段落开始时间，未推算结束时间；可定位回听，但不能直接导出完整 SRT。",
    ]
    return {"sources": sources, "segments": parsed["segments"], "duration": metadata["duration"],
            "date": entry.get("date") or metadata["date"], "warnings": warnings,
            "original_transcript": text,
            "source_context": {"preamble": parsed["preamble"], "appendix": parsed["appendix"],
                               "references": references},
            "audio": {"name": audio["name"], "mime": "audio/wav" if Path(audio["path"]).suffix.lower() == ".wav" else "audio/mp4",
                      "size": audio["size"], "storage_kind": "local_index", "revision": str(audio["mtime_ns"])}}


def sync_sources(store, identity, confirm_replace=False):
    old = store.get(identity)
    sources = old.get("local_sources", {})
    if not sources or "audio" not in sources or "transcript" not in sources:
        raise LocalSourceError("这节课没有完整的本地文件索引；请通过本机索引工具重新登记。")
    entry = {"audio_path": sources["audio"]["path"], "transcript_path": sources["transcript"]["path"],
             "date": old["date"],
             "reference_paths": [source["path"] for key, source in sources.items() if key.startswith("reference-")]}
    fresh = prepare(entry)
    text_changed = fresh["original_transcript"] != old.get("original_transcript")
    audio_changed = fresh["sources"]["audio"] != sources["audio"]
    if text_changed and old.get("notes") and not confirm_replace:
        raise LocalSourceError("原稿已变化。同步前请确认将现有笔记归档，防止旧引用错误关联新段落。")

    def update(item):
        if item.get("local_sources") != sources or item.get("segments") != old.get("segments") or item.get("notes") != old.get("notes"):
            raise LocalSourceError("课次在同步期间被修改，请重新检查后再试。")
        if text_changed:
            archived = item.setdefault("deleted_notes", [])
            stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for note in item.get("notes", []):
                saved = dict(note)
                saved["deleted_at"] = stamp
                saved["source_snapshot"] = {row["id"]: {"text": row["text"], "original_text": row.get("original_text", row["text"])}
                                            for row in item["segments"] if row["id"] in note["source_ids"]}
                archived[:] = [existing for existing in archived if existing["id"] != saved["id"]]
                archived.append(saved)
            item["notes"] = []
            for key in ("proofreading", "proofreading_history", "proofreading_job"):
                if key in item:
                    item.setdefault("source_sync_proofreading_history",[]).append({"kind":key,"value":item.pop(key),"at":stamp})
            item["segments"] = fresh["segments"]
            item["generation"] = {"mode": "", "model": "", "created_at": ""}
        if audio_changed:
            for row in item["segments"] + item.get("notes", []):
                if row.get("review_status") == "verified":
                    row["review_status"] = "needs_review"
        item["local_sources"] = fresh["sources"]
        item["source_context"] = fresh["source_context"]
        item["original_transcript"] = fresh["original_transcript"]
        item["duration"] = fresh["duration"]
        item["audio"] = {**fresh["audio"], "url": f"/api/lectures/{identity}/audio"}
        item["warnings"] = fresh["warnings"]
        if text_changed:
            item["warnings"].append("已从更新后的原稿重新建立段落；旧笔记已归档，不会静默重新关联。")
        if audio_changed:
            item["warnings"].append("原录音已更新，请复核转写时间码是否仍然对应。")
    return store.mutate(identity, update)
