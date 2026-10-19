"""Background note generation; progress contains counts, never keys or drafts."""
from copy import deepcopy
import json
import os
import re
import threading
import time
from uuid import uuid4
from core import pipeline, workflow, overview
from store import now

ACTIVE = {"queued", "running"}
USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens")


class NoteJobs:
    def __init__(self, store):
        self.store, self.lock, self.jobs = store, threading.RLock(), {}
        self.closed = threading.Event()

    def public(self, job):
        result = {key: deepcopy(value) for key, value in job.items() if not key.startswith("_")}
        result["elapsed_seconds"] = round(time.monotonic() - job["_started"], 1) if job["status"] in ACTIVE else job.get("elapsed_seconds", 0)
        return result

    def get(self, identity):
        with self.lock:
            job = self.jobs.get(identity)
            if job:
                return self.public(job)
        persisted = self.store.get(identity).get("generation_job")
        if persisted and persisted.get("status") in ACTIVE:
            return {**persisted, "status": "interrupted", "message": "服务重启中断了生成。已有笔记保留，不会自动重新调用付费接口。"}
        return persisted

    def diagnostics(self, identity):
        """Explicit local download only; never include drafts in polling data."""
        job = self.get(identity)
        if not job or not job.get("diagnostics_available") or not re.fullmatch(r"notes-[0-9a-f]{32}", job.get("id", "")):
            raise KeyError(identity)
        folder = self.store.root / "note-diagnostics"
        path = folder / (job["id"] + ".json")
        if folder.is_symlink() or path.is_symlink() or not path.is_file() or path.stat().st_size > 512000:
            raise KeyError(identity)
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_diagnostic(self, job, exc, settings):
        # Persist only an allowlisted answer excerpt and numeric metadata. In
        # particular: no headers, endpoint, prompt, reasoning text or traceback.
        raw = getattr(exc, "diagnostic", {})
        keys = ("error_code", "finish_reason", "answer_chars", "answer_excerpt", "answer_excerpt_truncated", "json_line", "json_column", "output_budget", "thinking_disabled", "synthesis_level", "group")
        record = {key: raw[key] for key in keys if key in raw}
        record.update(job_id=job["id"], scope=job["scope"], model=settings["llm"]["model"], created_at=now(), message=job["message"], usage=job["usage"], requests_started=job["requests_started"], requests_finished=job["requests_finished"], output_chars=job["output_chars"], reasoning_chars=job["reasoning_chars"], warning="Private local diagnostic. The answer excerpt may contain your transcript. Do not publish it.")
        secrets = [settings.get(kind, {}).get(field) for kind in ("llm", "asr", "notion") for field in ("api_key", "base_url", "token")]
        def redact(value):
            if isinstance(value, str):
                for secret in secrets:
                    if secret:
                        value = value.replace(secret, "[REDACTED]")
                return value
            if isinstance(value, dict):
                return {key: redact(child) for key, child in value.items()}
            return value
        folder = self.store.root / "note-diagnostics"
        try:
            if folder.is_symlink():
                return
            folder.mkdir(mode=0o700, exist_ok=True)
            path = folder / (job["id"] + ".json")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(redact(record), stream, ensure_ascii=False)
            with self.lock:
                job["diagnostics_available"] = True
                if isinstance(raw.get("finish_reason"), str):
                    job["finish_reason"] = raw["finish_reason"]
        except OSError:
            # Failure to save a diagnostic must not mask the actual failure.
            pass

    def start(self, item, settings, scope="all"):
        if not isinstance(scope,str) or scope not in {"all", "overview"}:
            raise pipeline.PipelineError("未知的整理范围。")
        if not item.get("segments") or scope == "overview" and not item.get("notes"):
            raise pipeline.PipelineError("请先准备原文和需要综合的笔记。")
        if scope == "overview":
            overview.check_plan(overview.plan(item["notes"], item["segments"]))
        else:
            pipeline._batches(item["segments"])  # Reject impossible jobs before paid extraction.
        pipeline._configuration(settings["llm"], True, "LLM", "/chat/completions")
        with self.lock:
            if self.closed.is_set() or any(job["status"] in ACTIVE for job in self.jobs.values()):
                raise pipeline.PipelineError("已有 AI 整理任务正在进行，请勿重复提交。")
            if self.get(item["id"]) and self.get(item["id"])["status"] in ACTIVE:
                raise pipeline.PipelineError("本节材料已有生成任务。")
            job = {"id": "notes-" + uuid4().hex, "lecture_id": item["id"], "scope": scope, "status": "queued", "phase": "preparing", "completed_units": 0, "total_units": 1,
                   "started_at": now(), "output_chars": 0, "reasoning_chars": 0, "requests_started": 0, "requests_finished": 0, "usage_reports": 0, "usage": None, "message": "", "_started": time.monotonic(), "_calls": [], "_current": None}
            self.jobs[item["id"]] = job
            self.store.mutate(item["id"], lambda row: row.update(generation_job=self.public(job)))
        thread = threading.Thread(target=self._run, args=(job, deepcopy(item), deepcopy(settings)), daemon=True)
        job["_thread"] = thread
        thread.start()
        return self.get(item["id"])

    def report(self, job, event):
        with self.lock:
            if self.closed.is_set():
                raise pipeline.PipelineError("本地服务已关闭，停止后续模型调用；供应商端当前请求可能仍计费。")
            if event.get("request_started"):
                job["requests_started"] += 1
                job["_current"] = {"usage": None, "output_chars": 0, "reasoning_chars": 0}
                job["_calls"].append(job["_current"])
            current = job["_current"]
            if current is not None:
                for key in ("output_chars", "reasoning_chars"):
                    if isinstance(event.get(key), int) and event[key] >= 0:
                        current[key] = event[key]
                raw = event.get("usage")
                if isinstance(raw, dict):
                    usage = {key: raw[key] for key in USAGE_KEYS if type(raw.get(key)) is int and raw[key] >= 0}
                    if usage:
                        current["usage"] = usage
            if event.get("request_finished"):
                job["requests_finished"] += 1
            for key in ("phase", "completed_units", "total_units", "synthesis_level", "output_budget", "thinking_disabled", "finish_reason"):
                if key in event:
                    job[key] = event[key]
            job["output_chars"] = sum(call["output_chars"] for call in job["_calls"])
            job["reasoning_chars"] = sum(call["reasoning_chars"] for call in job["_calls"])
            reports = [call["usage"] for call in job["_calls"] if call["usage"] is not None]
            job["usage_reports"] = len(reports)
            job["usage"] = {key: sum(report[key] for report in reports if key in report) for key in USAGE_KEYS if any(key in report for report in reports)} if reports else None

    def _run(self, job, item, settings):
        final_status = "failed"
        try:
            with self.lock:
                job["status"] = "running"
            report = lambda event: self.report(job, event)
            if job["scope"] == "all":
                generated = pipeline.generate_llm_notes(item["segments"], settings["llm"], settings["glossary"], allow_external=True, workflow_config=item.get("workflow"), on_progress=report)
            else:
                generated = {"notes": item["notes"], "warnings": [], "model": settings["llm"]["model"]}
            summary = overview.synthesize(generated["notes"], item["segments"], settings["llm"], item.get("workflow"), allow_external=True, on_progress=report)
            generated["warnings"] = [warning for warning in generated.get("warnings", []) if warning != "跨批次的论证联系可能缺失或重复，请人工检查上下文；没有自动声称全课综合完成。"]
            summary["model"] = settings["llm"]["model"]
            report({"phase": "saving", "completed_units": 0, "total_units": 1})
            def save(current):
                if overview.snapshot(current) != overview.snapshot(item):
                    raise pipeline.PipelineError("生成期间原文、笔记或用途已修改，未覆盖你的修改；本次接口用量可能已产生。")
                current.setdefault("note_history", []).append({key: deepcopy(current.get(key)) for key in ("notes", "overview", "generation")})
                current["note_history"][-1]["archived_at"] = now()
                current["notes"] = generated["notes"]
                summary["source_hash"] = overview.content_hash(current)
                summary["created_at"] = now()
                current["overview"] = summary
                current["warnings"].extend(warning for warning in generated.get("warnings", []) if warning not in current["warnings"])
                if job["scope"] == "all":
                    current["generation"] = {"mode": "llm", "model": generated["model"], "created_at": now(), **workflow.metadata(item.get("workflow"))}
                current["generation"]["usage"] = deepcopy(job["usage"])
                current["generation"]["usage_reports"] = job["usage_reports"]
                current["generation"]["requests_finished"] = job["requests_finished"]
            self.store.mutate(item["id"], save)
            with self.lock:
                job.update(phase="completed", completed_units=1, total_units=1,
                    message="总览已保存，原有详细笔记保持不变；内容仍需人工核查。" if job["scope"] == "overview" else "总览与详细笔记已保存，内容仍需人工核查。")
                final_status = "completed"
        except Exception as exc:
            with self.lock:
                job["message"] = str(exc) if isinstance(exc, pipeline.PipelineError) else "AI 整理未完成；已有笔记保持不变，没有自动重试。"
            self._save_diagnostic(job, exc, settings)
        finally:
            # Publish a terminal state only after diagnostics exist and the job
            # snapshot is persisted. Pollers may stop as soon as they see it.
            with self.lock:
                job["status"] = final_status
                job["elapsed_seconds"] = round(time.monotonic() - job["_started"], 1)
                public = self.public(job)
                try:
                    def persist(row):
                        if row.get("generation_job", {}).get("id") == job["id"]:
                            row["generation_job"] = public
                    self.store.mutate(item["id"], persist)
                except Exception:
                    pass

    def close(self):
        self.closed.set()
        with self.lock:
            threads = [job.get("_thread") for job in self.jobs.values()]
        for thread in threads:
            if thread and thread is not threading.current_thread():
                thread.join(timeout=1)
