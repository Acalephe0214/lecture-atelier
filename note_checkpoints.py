"""Private, exact-request checkpoints. A hit never makes a provider request."""
import hashlib
import json

from core import pipeline


class NoteCheckpoints:
    VERSION = 1

    def __init__(self, store, lecture_id, report=None):
        self.store, self.lecture_id = store, lecture_id
        self.report = report or (lambda event: None)
        self.reused = self.saved = 0
        with store.connection() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS note_checkpoints (key TEXT PRIMARY KEY, lecture_id TEXT NOT NULL, stage TEXT NOT NULL, response TEXT NOT NULL, valid INTEGER NOT NULL)")

    def key(self, stage, endpoint, payload):
        # Endpoint, model, exact sources, glossary, language and instructions
        # affect this digest. Authorization headers/keys are never stored.
        material = [self.VERSION, self.lecture_id, stage, endpoint, payload]
        return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def ready(self, stage, endpoint, payload):
        with self.store.connection() as conn:
            row = conn.execute("SELECT valid FROM note_checkpoints WHERE key=?", (self.key(stage, endpoint, payload),)).fetchone()
        return bool(row and row[0])

    def run(self, stage, endpoint, payload, fetch, validate):
        key = self.key(stage, endpoint, payload)
        with self.store.connection() as conn:
            row = conn.execute("SELECT response,valid FROM note_checkpoints WHERE key=?", (key,)).fetchone()
        if row:
            try:
                result = validate(json.loads(row[0]))
            except (ValueError, KeyError, TypeError, IndexError):
                # Revalidation protects against corruption and changing rules.
                with self.store.connection() as conn:
                    conn.execute("UPDATE note_checkpoints SET valid=0 WHERE key=?", (key,))
            else:
                with self.store.connection() as conn:
                    conn.execute("UPDATE note_checkpoints SET valid=1 WHERE key=?", (key,))
                self.reused += 1
                self.report({"reused_units": self.reused, "checkpointed_units": self.saved})
                return result
        response = fetch()
        # Save the paid answer before validation. Keep answer text, not hidden
        # reasoning, request headers, credentials or entire provider envelopes.
        choices = response.get("choices", []) if isinstance(response, dict) else []
        if not isinstance(choices, list):
            choices = []
        safe = {"choices": [{"finish_reason": choice.get("finish_reason"), "message": {
            "content": choice.get("message", {}).get("content"),
            "refusal": bool(choice.get("message", {}).get("refusal"))}}
            for choice in choices[:1] if isinstance(choice, dict) and isinstance(choice.get("message"), dict)]}
        text = json.dumps(safe, ensure_ascii=False)
        if len(text.encode()) > pipeline.MAX_RESPONSE_BYTES:
            raise pipeline.PipelineError("模型返回内容超过本地断点大小限制，处理已暂停。")
        try:
            with self.store.connection() as conn:
                conn.execute("INSERT OR REPLACE INTO note_checkpoints VALUES (?,?,?,?,0)", (key, self.lecture_id, stage, text))
        except Exception:
            raise pipeline.PipelineError("本地断点保存失败，请检查磁盘空间与权限后继续。") from None
        result = validate(safe)
        with self.store.connection() as conn:
            conn.execute("UPDATE note_checkpoints SET valid=1 WHERE key=?", (key,))
        self.saved += 1
        self.report({"reused_units": self.reused, "checkpointed_units": self.saved})
        return result

    def preview(self, item, settings, scope):
        from core import overview
        endpoint, model, _ = pipeline._configuration(settings["llm"], True, "LLM", "/chat/completions")
        details = [] if scope != "all" else [pipeline.notes_payload(batch, settings.get("glossary", []), item.get("workflow"), model) for batch in pipeline._batches(item["segments"])]
        groups = overview.plan(item["notes"], item["segments"])["groups"] if scope == "overview" and item.get("notes") else []
        summaries = [{**overview.payload(group, item.get("workflow"), model, len(groups) > 1), **overview.request_policy(endpoint, model)} for group in groups]
        return {"details_ready": sum(self.ready("notes", endpoint, body) for body in details), "details_total": len(details),
                "overview_ready": sum(self.ready("overview", endpoint, body) for body in summaries), "overview_known": len(summaries)}
