"""Recoverable workspace removal. Original media bytes stay on disk."""
from copy import deepcopy
import hashlib
import json
from uuid import uuid4

from store import StoreError, now


class RemovalConflict(StoreError):
    pass


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class RecycleBin:
    def __init__(self, store):
        self.store = store
        with store.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS recycle (id TEXT PRIMARY KEY, kind TEXT NOT NULL, name TEXT NOT NULL, removed_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def _snapshot(self, conn, kind, identity):
        if kind == "course":
            row = conn.execute("SELECT * FROM courses WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise KeyError(identity)
            items = [json.loads(row[0]) for row in conn.execute("SELECT payload FROM lectures ORDER BY id")]
            return {"course": dict(row), "lectures": [item for item in items if item["course_id"] == identity]}
        if kind not in {"lecture", "audio"}:
            raise StoreError("请选择课程、课次或录音。")
        row = conn.execute("SELECT payload FROM lectures WHERE id=?", (identity,)).fetchone()
        if row is None:
            raise KeyError(identity)
        item = json.loads(row[0])
        if kind == "audio" and not item.get("audio"):
            raise StoreError("请先选择已添加的录音。")
        return {"lectures": [item]}

    @staticmethod
    def _preview(kind, identity, snapshot):
        items = snapshot["lectures"]
        return {"kind": kind, "identity": identity, "revision": revision(snapshot),
                "name": snapshot["course"]["name"] if kind == "course" else items[0]["audio"]["name"] if kind == "audio" else items[0]["title"],
                "lecture_ids": [item["id"] for item in items], "lecture_count": len(items),
                "audio_count": sum(bool(item.get("audio")) for item in items)}

    def preview(self, kind, identity):
        with self.store.connection() as conn:
            conn.execute("BEGIN")
            return self._preview(kind, identity, self._snapshot(conn, kind, identity))

    def remove(self, kind, identity, expected):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            snapshot = self._snapshot(conn, kind, identity)
            if not isinstance(expected, str) or revision(snapshot) != expected:
                raise RemovalConflict("材料已更新，请重新打开移除确认。")
            preview = self._preview(kind, identity, snapshot)
            recycle_id = "recycle-" + uuid4().hex
            conn.execute("INSERT INTO recycle VALUES (?, ?, ?, ?, ?)",
                         (recycle_id, kind, preview["name"], now(), json.dumps(snapshot, ensure_ascii=False)))
            if kind == "audio":
                item = deepcopy(snapshot["lectures"][0])
                item["audio"] = None
                for key in ("audio_derivatives", "local_asr_state", "local_repair_state", "local_repair_private", "external_transcription", "external_transcription_private"):
                    item.pop(key, None)
                if item.get("local_sources"):
                    item["local_sources"].pop("audio", None)
                item["updated_at"] = now()
                conn.execute("UPDATE lectures SET payload=? WHERE id=?", (json.dumps(item, ensure_ascii=False), identity))
            else:
                for item in snapshot["lectures"]:
                    conn.execute("DELETE FROM lectures WHERE id=?", (item["id"],))
                if kind == "course":
                    conn.execute("DELETE FROM courses WHERE id=?", (identity,))
        return {"recycle_id": recycle_id, **preview}

    def entries(self):
        with self.store.connection() as conn:
            rows = conn.execute("SELECT id, kind, name, removed_at, payload FROM recycle ORDER BY rowid DESC").fetchall()
        return [{key: row[key] for key in ("id", "kind", "name", "removed_at")} | {
            "lecture_count": len(json.loads(row["payload"])["lectures"])} for row in rows]

    def restore(self, identity):
        with self.store.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM recycle WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise KeyError(identity)
            data = json.loads(row["payload"])
            items = data["lectures"]
            if row["kind"] == "audio":
                previous = items[0]
                current = conn.execute("SELECT payload FROM lectures WHERE id=?", (previous["id"],)).fetchone()
                if current is None:
                    raise RemovalConflict("请先恢复这份录音所属的课次。")
                item = json.loads(current[0])
                if item.get("audio"):
                    raise RemovalConflict("当前课次已有录音，请先移除当前录音再恢复。")
                item["audio"] = previous["audio"]
                if previous.get("audio_derivatives"):
                    item["audio_derivatives"] = previous["audio_derivatives"]
                if previous.get("local_sources", {}).get("audio"):
                    item.setdefault("local_sources", {})["audio"] = previous["local_sources"]["audio"]
                item["updated_at"] = now()
                conn.execute("UPDATE lectures SET payload=? WHERE id=?", (json.dumps(item, ensure_ascii=False), item["id"]))
            else:
                if "course" in data:
                    course = data["course"]
                    if conn.execute("SELECT 1 FROM courses WHERE id=?", (course["id"],)).fetchone():
                        raise RemovalConflict("课程编号已有新记录，请保留两份资料并联系维护者。")
                    conn.execute("INSERT INTO courses VALUES (:id, :name, :color)", course)
                for item in items:
                    if not conn.execute("SELECT 1 FROM courses WHERE id=?", (item["course_id"],)).fetchone():
                        raise RemovalConflict("请先恢复课次所属的课程。")
                    if conn.execute("SELECT 1 FROM lectures WHERE id=?", (item["id"],)).fetchone():
                        raise RemovalConflict("课次编号已有新记录，请保留两份资料并联系维护者。")
                    conn.execute("INSERT INTO lectures VALUES (?, ?)", (item["id"], json.dumps(item, ensure_ascii=False)))
            conn.execute("DELETE FROM recycle WHERE id=?", (identity,))
        return {"restored": identity, "kind": row["kind"], "lecture_ids": [item["id"] for item in items]}
