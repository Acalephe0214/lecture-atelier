"""Local SQLite storage and private on-disk connector configuration."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import sqlite3
import threading
from datetime import datetime, timezone
from uuid import uuid4

from local_sources import linked_audio_path, public_sources
from audio_processing import public_versions
from local_transcription import configuration as local_configuration
from core import overview

SAMPLE_COURSE = ("示例课程", "#70806d", "course-sample")

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, data_dir):
        self.root = Path(data_dir).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.audio_dir = self.root / "audio"
        self.audio_dir.mkdir(exist_ok=True, mode=0o700)
        self.database = self.root / "lectures.sqlite3"
        self.settings_path = self.root / "settings.json"
        self._settings_lock = threading.Lock()
        with self.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS courses (id TEXT PRIMARY KEY, name TEXT NOT NULL, color TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS lectures (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            # Fresh workspaces have one generic category, never the author's
            # course list. Reopening any populated workspace preserves it as-is.
            if not conn.execute("SELECT 1 FROM courses LIMIT 1").fetchone() and not conn.execute("SELECT 1 FROM lectures LIMIT 1").fetchone():
                name, color, identity = SAMPLE_COURSE
                conn.execute("INSERT OR IGNORE INTO courses VALUES (?, ?, ?)", (identity, name, color))
        try:
            self.database.chmod(0o600)
        except OSError:
            pass

    def connection(self):
        conn = sqlite3.connect(self.database, timeout=20)
        conn.row_factory = sqlite3.Row
        # SQLite connection's context manager commits or rolls back but does not
        # close; the wrapper makes each operation own exactly one connection.
        class ConnectionContext:
            def __enter__(self):
                return conn
            def __exit__(self, kind, value, tb):
                try:
                    if kind is None:
                        conn.commit()
                    else:
                        conn.rollback()
                finally:
                    conn.close()
        return ConnectionContext()

    def courses(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM courses ORDER BY rowid")]

    def ensure_sample_course(self):
        name, color, identity = SAMPLE_COURSE
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO courses VALUES (?, ?, ?)", (identity, name, color))
        return identity

    def add_course(self, name):
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise StoreError("请输入 1—100 字的课程名称。")
        course = {"id": "course-" + uuid4().hex, "name": name.strip(), "color": "#70806d"}
        with self.connection() as conn:
            conn.execute("INSERT INTO courses VALUES (:id, :name, :color)", course)
        return course

    @staticmethod
    def _summary(item):
        return {"id": item["id"], "course_id": item["course_id"], "title": item["title"],
                "date": item["date"], "duration": item["duration"],
                "segment_count": len(item["segments"]), "note_count": len(item["notes"]),
                "updated_at": item["updated_at"], "is_demo": item["is_demo"],
                "generation_mode": item["generation"]["mode"],
                "audio_name": item["audio"]["name"] if item["audio"] else ""}

    def lectures(self):
        with self.connection() as conn:
            values = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM lectures")]
        return sorted((self._summary(item) for item in values), key=lambda item: item["updated_at"], reverse=True)

    def get(self, lecture_id):
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
        if not row:
            raise KeyError(lecture_id)
        return json.loads(row[0])

    def create(self, course_id, title, date, *, identity=None, is_demo=False):
        if not isinstance(title, str) or not title.strip() or len(title.strip()) > 200:
            raise StoreError("请输入 1—200 字的课次标题。")
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except (TypeError, ValueError):
            raise StoreError("日期须使用 YYYY-MM-DD 格式。") from None
        lecture_id = identity or "lecture-" + uuid4().hex
        item = {"id": lecture_id, "course_id": course_id, "title": title.strip(), "date": date,
                "duration": 0, "updated_at": now(), "is_demo": is_demo, "segments": [], "notes": [],
                "warnings": [], "generation": {"mode": "", "model": "", "created_at": ""},
                "audio": None, "transcript_format": "", "original_transcript": ""}
        item["workflow"] = {"scene": "class", "instructions": "", "prompt_override": "", "output_language": "zh"}
        with self.connection() as conn:
            if not conn.execute("SELECT id FROM courses WHERE id = ?", (course_id,)).fetchone():
                raise StoreError("课程不存在，请先创建课程。")
            conn.execute("INSERT OR IGNORE INTO lectures VALUES (?, ?)", (lecture_id, json.dumps(item, ensure_ascii=False)))
        return self.get(lecture_id)

    def mutate(self, lecture_id, callback):
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT payload FROM lectures WHERE id = ?", (lecture_id,)).fetchone()
            if not row:
                raise KeyError(lecture_id)
            item = json.loads(row[0])
            callback(item)
            item["updated_at"] = now()
            conn.execute("UPDATE lectures SET payload = ? WHERE id = ?", (json.dumps(item, ensure_ascii=False), lecture_id))
        return item

    def audio_path(self, item):
        if not item.get("audio"):
            raise StoreError("请先上传录音文件。")
        if item["audio"].get("storage_kind") == "local_index":
            return linked_audio_path(item)
        # Storage names are generated here, never derived from supplied names.
        name = item["audio"].get("storage_name", "")
        if not name or Path(name).name != name:
            raise StoreError("录音文件不可用。")
        path = (self.audio_dir / name).resolve()
        if path.parent != self.audio_dir or not path.is_file():
            raise StoreError("录音文件不可用。")
        return path

    def public_lecture(self, item):
        result = copy.deepcopy(item)
        result["audio_versions"] = public_versions(self, item)
        result.pop("audio_derivatives", None)
        result.pop("external_transcription_private", None)
        result.pop("local_repair_private", None)
        if result.get("proofreading"):
            from core.redline import public_session
            result["proofreading"] = public_session(item)
        if result.get("local_sources"):
            result["source_files"] = public_sources(item)
        result.pop("local_sources", None)
        if result.get("overview"):
            result["overview"]["stale"] = result["overview"].get("source_hash") != overview.content_hash(item)
        if result.get("audio"):
            result["audio"].pop("storage_name", None)
        return result

    def private_settings(self):
        with self._settings_lock:
            if self.settings_path.exists():
                try:
                    raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    raise StoreError("本地配置文件无法读取，请检查 data-dir 中的 settings.json。") from None
            else:
                raw = {}
        result = {"glossary": raw.get("glossary", [])}
        result["billing"] = raw.get("billing", {})
        result["notion"] = raw.get("notion", {"parent_page_id": "", "token": ""})
        result["local_asr"] = local_configuration(raw.get("local_asr", {}))
        for name in ("llm", "asr"):
            existing = raw.get(name, {})
            result[name] = {key: os.environ.get("LECTURE_" + name.upper() + "_" + key.upper(), existing.get(key, ""))
                            for key in ("base_url", "model", "api_key")}
        return result

    def public_settings(self):
        raw = self.private_settings()
        result = {"glossary": raw["glossary"]}
        result["billing"] = raw["billing"]
        result["notion"] = {"parent_page_id": raw["notion"].get("parent_page_id", ""), "configured": bool(raw["notion"].get("token"))}
        result["local_asr"] = dict(raw["local_asr"])
        result["local_asr"]["configured"] = bool(raw["local_asr"]["model_path"])
        for name in ("llm", "asr"):
            result[name] = {key: raw[name][key] for key in ("base_url", "model")}
            result[name]["configured"] = bool(raw[name]["base_url"] and raw[name]["model"])
        return result

    def update_settings(self, patch):
        if not isinstance(patch, dict):
            raise StoreError("配置内容必须为对象。")
        with self._settings_lock:
            raw = json.loads(self.settings_path.read_text(encoding="utf-8")) if self.settings_path.exists() else {}
            try:
                if "billing" in patch:
                    from core.usage_estimate import validate_billing
                    raw["billing"] = validate_billing(patch["billing"])
                if "notion" in patch:
                    from core.notion_export import configuration
                    update = dict(patch["notion"])
                    previous = raw.get("notion", {})
                    update["token"] = "" if update.get("clear_key") is True else (update.get("token") or previous.get("token", ""))
                    raw["notion"] = configuration({**previous, **update})
            except (ValueError, TypeError):
                raise StoreError("请检查费率或 Notion 配置格式；目标须为有效页面链接 / ID，费率为非负数字。") from None
            for name in ("llm", "asr"):
                if name not in patch:
                    continue
                value = patch[name]
                if not isinstance(value, dict):
                    raise StoreError("接口配置必须为对象。")
                target = raw.setdefault(name, {})
                for key in ("base_url", "model", "api_key"):
                    if key not in value:
                        continue
                    content = value[key]
                    if not isinstance(content, str) or len(content) > 4096:
                        raise StoreError("接口配置格式不正确。")
                    content = content.strip()
                    if key != "api_key" or content:
                        target[key] = content
                if value.get("clear_key") is True:
                    target["api_key"] = ""
            if "glossary" in patch:
                entries = patch["glossary"]
                if not isinstance(entries, list) or len(entries) > 300:
                    raise StoreError("术语表最多支持 300 项。")
                clean = []
                for entry in entries:
                    if not isinstance(entry, dict) or not isinstance(entry.get("term"), str) or not isinstance(entry.get("meaning", ""), str):
                        raise StoreError("术语表须包含 term 和 meaning 文本字段。")
                    if not entry["term"].strip() or len(entry["term"]) > 200 or len(entry.get("meaning", "")) > 2000:
                        raise StoreError("术语条目为空或过长。")
                    clean.append({"term": entry["term"].strip(), "meaning": entry.get("meaning", "").strip()})
                if len(json.dumps(clean, ensure_ascii=False)) > 20000:
                    raise StoreError("术语表序列化后的总长度不能超过 20000 字符，请精简释义或减少条目。")
                raw["glossary"] = clean
            if "local_asr" in patch:
                try:
                    if not isinstance(patch["local_asr"], dict):
                        raise ValueError("本地模型配置须为对象。")
                    raw["local_asr"] = local_configuration({**raw.get("local_asr", {}), **patch["local_asr"]})
                except ValueError as exc:
                    raise StoreError(str(exc)) from None
            temporary = self.root / (".settings-" + uuid4().hex + ".tmp")
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(raw, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.settings_path)
                self.settings_path.chmod(0o600)
            finally:
                if temporary.exists():
                    temporary.unlink()
        return self.public_settings()
