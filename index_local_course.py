#!/usr/bin/env python3
"""Explicit local-file registration. No copying, transcription, or external calls.

Dry run by default. Paths must be provided in a local manifest; the web server
never accepts new filesystem paths from a browser. Existing lessons are skipped,
never silently overwritten. Uses the app's ordinary SQLite file.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import sqlite3
from uuid import uuid4

from local_sources import LocalSourceError, prepare
from store import Store, now


def prepare_manifest(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("version") != 1:
        raise LocalSourceError("清单须为 version: 1 的 JSON 对象。")
    entries = data.get("lectures")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise LocalSourceError("清单应包含 1—100 个明确的课次。")
    ids, results = set(), []
    for entry in entries:
        identity = entry.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", identity) or identity in ids:
            raise LocalSourceError("课次编号无效或重复。")
        ids.add(identity)
        if not isinstance(entry.get("title"), str) or not 1 <= len(entry["title"].strip()) <= 200:
            raise LocalSourceError("课次标题为空或过长。")
        fresh = prepare(entry)
        datetime.strptime(fresh["date"], "%Y-%m-%d")
        results.append((entry, fresh))
    return data, results


def register(manifest, prepared, data_dir):
    store = Store(data_dir)
    course_id = manifest["course_id"]
    if course_id not in {course["id"] for course in store.courses()}:
        raise LocalSourceError("目标课程不存在；请先在 App 中创建课程并使用实际 ID。")
    backup_dir = store.root / "backups"
    backup_dir.mkdir(exist_ok=True, mode=0o700)
    backup = backup_dir / ("before-local-index-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid4().hex[:8] + ".sqlite3")
    with sqlite3.connect(store.database) as source, sqlite3.connect(backup) as destination:
        source.backup(destination)
    backup.chmod(0o600)
    output = []
    with store.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for entry, fresh in prepared:
            identity = entry["id"]
            existing = conn.execute("SELECT payload FROM lectures WHERE id = ?", (identity,)).fetchone()
            if existing:
                old = json.loads(existing[0])
                registered = old.get("local_sources", {})
                if any(registered.get(kind, {}).get("path") != fresh["sources"][kind]["path"] for kind in ("audio", "transcript")):
                    raise LocalSourceError("已有课次编号指向其他材料，已中止；不会覆盖原课次。")
                output.append({"id": identity, "title": old["title"], "status": "already_indexed_preserved"})
                continue
            item = {"id": identity, "course_id": course_id, "title": entry["title"].strip(),
                    "date": fresh["date"], "duration": fresh["duration"], "updated_at": now(),
                    "is_demo": False, "segments": fresh["segments"], "notes": [],
                    "warnings": fresh["warnings"], "generation": {"mode": "", "model": "", "created_at": ""},
                    "audio": {**fresh["audio"], "url": f"/api/lectures/{identity}/audio"},
                    "transcript_format": "markdown-timestamped", "original_transcript": fresh["original_transcript"],
                    "local_sources": fresh["sources"], "source_context": fresh["source_context"]}
            conn.execute("INSERT INTO lectures VALUES (?, ?)", (identity, json.dumps(item, ensure_ascii=False)))
            output.append({"id": identity, "title": item["title"], "date": item["date"],
                           "segments": len(item["segments"]), "duration": item["duration"],
                           "audio_bytes": item["audio"]["size"], "status": "indexed_without_copy"})
    return {"backup": str(backup), "lectures": output, "audio_bytes_copied": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--data-dir", default=Path(__file__).parent / ".runtime", type=Path)
    parser.add_argument("--apply", action="store_true", help="明确写入索引；默认仅检查来源")
    args = parser.parse_args()
    try:
        manifest, prepared = prepare_manifest(args.manifest)
        if args.apply:
            result = register(manifest, prepared, args.data_dir)
        else:
            result = {"dry_run": True, "course_id": manifest["course_id"], "lectures": [
                {"id": entry["id"], "title": entry["title"], "date": fresh["date"],
                 "segments": len(fresh["segments"]), "duration": fresh["duration"],
                 "audio_bytes": fresh["audio"]["size"], "reference_files": len(fresh["sources"]) - 2}
                for entry, fresh in prepared], "audio_bytes_to_copy": 0}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (LocalSourceError, KeyError, ValueError, OSError) as exc:
        parser.exit(1, "索引未完成：" + str(exc) + "\n")


if __name__ == "__main__":
    main()
