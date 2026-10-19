"""Bounded, local passage repair. Candidates never overwrite text automatically."""
from __future__ import annotations

import json
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import math
import re
from uuid import uuid4
from datetime import datetime, timezone

from audio_processing import fingerprint, media_duration
from core import workflow, audio_prepare
from core.asr_guard import inspect_result, word_timing_reasons
from local_transcription import checked_config, worker_env

STRATEGIES = [
    ("原音＋词级时间码", 0, None, (0.0, .2)),
    ("前后各加 2 秒上下文", 2, None, (.2, .4)),
    ("去瞬态点击＋上下文", 2, "highpass=f=70,adeclick=w=30:o=75:t=2:b=2:m=s,afftdn=nr=6:nf=-45:tn=1", (0.0, .2)),
    ("15 秒短窗＋上下文", 2, None, (.4, .6)),
]


def segment_digest(segment):
    return workflow.digest(segment)


def joined_text(rows):
    text = ""
    for row in rows:
        word = row["text"].strip()
        if re.search(r"[A-Za-zÀ-ỹ0-9][.!?,;:)]?$", text) and word and re.match(r"[A-Za-zÀ-ỹ0-9]", word):
            text += " "
        text += word
    return text


def resolve_issue(item, segment, method):
    """Filled is distinct from human verified; keep the original issue audit."""
    segment["asr_issue"] = False
    segment["repair_method"] = method
    for issue in item.get("asr_report", {}).get("issues", []):
        if issue.get("start") == segment.get("start") and issue.get("end") == segment.get("end"):
            issue.update(resolved=True, resolved_by=method, source_id=segment["id"])
    for note in item.get("notes", []):
        if segment["id"] in note["source_ids"] and note["review_status"] == "verified":
            note["review_status"] = "needs_review"


def apply_candidates(item, job, ids, source):
    if job.get("status") not in {"running", "completed", "cancelled", "interrupted", "failed"} or source != job.get("source"):
        raise ValueError("补转任务未完成或录音已变化，未覆盖原文。")
    if not isinstance(ids, list) or not ids or any(not isinstance(sid, str) for sid in ids) or len(ids) != len(set(ids)):
        raise ValueError("请选择要采用的候选段落。")
    selected = []
    for sid in ids:
        row = next((value for value in job["results"] if value["segment_id"] == sid), None)
        segment = next((value for value in item["segments"] if value["id"] == sid), None)
        if not row or not row.get("candidate") or row.get("status", "candidate") != "candidate" or row.get("errors") or not segment or segment_digest(segment) != row["snapshot"]:
            raise ValueError("所选段落已修改、已采用或没有可用候选；未覆盖任何文字。")
        selected.append((segment, row))
    for segment, row in selected:
        item.setdefault("asr_repair_history", []).append({"before": dict(segment), "candidate": row,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
        segment.setdefault("original_text", segment["text"])
        segment.update(text=row["candidate"], review_status="unreviewed", user_edited=False)
        resolve_issue(item, segment, "local_candidate")
    warning = "局部补转候选仅通过启发式检查，仍未人工核对；关联笔记需要复核。"
    if warning not in item["warnings"]:
        item["warnings"].append(warning)


class RepairJobs:
    def __init__(self, store):
        self.store, self.lock, self.jobs = store, threading.RLock(), {}
        self.process = None
        self.closed = False

    @staticmethod
    def public(job):
        value = copy.deepcopy({key: value for key, value in job.items() if key not in {"source", "cancel_requested"} and not key.startswith("_")})
        end = job.get("_finished", time.monotonic())
        if "_started" in job:
            value["elapsed_seconds"] = round(max(0, end - job["_started"]), 1)
        if job.get("current") and "_strategy_started" in job:
            value["strategy_elapsed_seconds"] = round(max(0, end - job["_strategy_started"]), 1)
        results = job.get("results", [])
        value.update(completed=len(results), candidate_count=sum(bool(row.get("candidate")) and row.get("status") != "applied" for row in results),
                     unresolved_count=sum(not bool(row.get("candidate")) for row in results), applied_count=sum(row.get("status") == "applied" for row in results))
        value["progress"] = min(100, int(len(results) * 100 / max(1, job.get("total", len(results)))))
        return value

    def get(self, identity):
        with self.lock:
            if identity in self.jobs:
                return self.public(self.jobs[identity])
            saved = self.store.get(identity).get("local_repair_state")
            if saved and saved["status"] == "running":
                return {**saved, "status": "interrupted", "phase": "interrupted", "current": None, "message": "上次局部补转中断，已生成候选保留，未自动覆盖原稿；可采用候选或重新尝试。"}
            return saved

    def _persist(self, identity):
        self.store.mutate(identity, lambda item: item.update(local_repair_state=self.public(self.jobs[identity]), local_repair_private={"source":self.jobs[identity]["source"]}))

    def cancel(self, identity):
        with self.lock:
            job = self.jobs.get(identity)
            if not job or job["status"] != "running":
                raise ValueError("没有正在运行的局部补转任务。")
            job.update(cancel_requested=True, message="正在停止局部补转，原文保持不变。")
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self._persist(identity)
            return self.public(job)

    def start(self, identity, ids, config):
        hint=config.get("hint_text","")
        if not isinstance(hint,str) or len(hint)>1200 or '\0' in hint:
            raise ValueError("局部转写术语提示不能超过 1200 字符。")
        config = checked_config(config)
        config["hint_text"]=hint
        item = self.store.get(identity)
        if not isinstance(ids, list) or not 1 <= len(ids) <= 64 or any(not isinstance(sid, str) for sid in ids) or len(set(ids)) != len(ids):
            raise ValueError("一次请选择 1—64 个片段，累计不超过 30 分钟。")
        rows = []
        for sid in ids:
            segment = next((row for row in item["segments"] if row["id"] == sid), None)
            if not segment:
                raise ValueError("所选段落不存在。")
            start, end = segment.get("start"), segment.get("end")
            if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in (start, end)) or not 0 <= start < end or end - start > 120:
                raise ValueError("局部补转需要真实起止时间，每段最长 120 秒。无结束时间的稿件请先人工回听校对。")
            rows.append({"segment_id": sid, "start": start, "end": end, "snapshot": segment_digest(segment)})
        if sum(row["end"] - row["start"] for row in rows) > 1800:
            raise ValueError("本次片段累计超过 30 分钟，请分批补转。")
        path = self.store.audio_path(item)
        source = fingerprint(path)
        with self.lock:
            if self.closed or any(job["status"] == "running" for job in self.jobs.values()):
                raise ValueError("已有局部补转任务，请稍后。")
            self.jobs[identity] = {"id": uuid4().hex, "status": "running", "results": [], "total": len(rows),
                "phase": "preparing", "current": None, "_started": time.monotonic(), "last_attempt_errors": [],
                "message": "局部补转中：最多 4 种策略；候选需确认采用，不覆盖人工编辑。", "source": source, "hint_used":bool(hint)}
            self._persist(identity)
        threading.Thread(target=self._run, args=(identity, path, rows, config), daemon=True).start()
        return self.get(identity)

    def _run(self, identity, path, rows, config):
        try:
            prepared = audio_prepare.cached(path, self.store.root) or path
            for index, row in enumerate(rows, 1):
                result = None
                errors = []
                attempts_log = []
                for strategy in range(len(STRATEGIES)):
                    with self.lock:
                        if self.closed or self.jobs[identity].get("cancel_requested"):
                            raise ValueError("服务已停止，原稿未改动。")
                        self.jobs[identity]["message"] = f"{row['segment_id']}：尝试 {strategy + 1}/4 · {STRATEGIES[strategy][0]}"
                        self.jobs[identity].update(phase="recognizing", current={"index": index, "segment_id": row["segment_id"], "start": row["start"], "end": row["end"],
                            "strategy_index": strategy + 1, "strategy_total": len(STRATEGIES), "strategy": STRATEGIES[strategy][0]}, _strategy_started=time.monotonic(), last_attempt_errors=errors)
                        self._persist(identity)
                        process = subprocess.Popen([config["python_path"], str(Path(__file__).resolve()), "--worker"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                            env=worker_env(config))
                        self.process = process
                    try:
                        out, _ = process.communicate(json.dumps({"path": str(prepared), "config": config, "row": row, "strategy": strategy}), timeout=180)
                        if process.returncode:
                            raise ValueError("本地识别失败")
                        result = json.loads(out.strip().splitlines()[-1])
                        if not isinstance(result, dict) or not isinstance(result.get("errors"), list):
                            raise ValueError("本地结果无效")
                        with self.lock:
                            self.jobs[identity]["phase"] = "validating"
                        # Validate in the server too, not just in the worker.
                        checked, issues = inspect_result({"segments": result.get("segments")}, row["end"] - row["start"])
                        if not result["errors"] and not issues:
                            result["segments"] = checked
                            break
                        errors = result["errors"] or issues
                        result = None
                    except (ValueError, IndexError, OSError, subprocess.TimeoutExpired):
                        errors, result = ["当前策略失败或超时"], None
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.communicate(timeout=5)
                        with self.lock:
                            attempts_log.append({"strategy": STRATEGIES[strategy][0], "attempt": strategy + 1,
                                "elapsed_seconds": round(max(0, time.monotonic() - self.jobs[identity]["_strategy_started"]), 1),
                                "passed": result is not None, "errors": [] if result else errors})
                            if self.process is process:
                                self.process = None
                with self.lock:
                    self.jobs[identity]["results"].append({**row, "candidate": joined_text(result["segments"]) if result else "",
                        "segments": result["segments"] if result else [], "strategy": STRATEGIES[strategy][0], "attempts": strategy + 1,
                        "attempt_log": attempts_log,
                        "errors": [] if result else errors, "status": "candidate" if result else "unresolved"})
                    self.jobs[identity].update(phase="between_passages", current=None, last_attempt_errors=[])
                    self._persist(identity)
            with self.lock:
                if self.closed or self.jobs[identity].get("cancel_requested"):
                    raise ValueError("任务已取消")
                self.jobs[identity].update(status="completed", phase="finished", current=None, _finished=time.monotonic(), message="局部补转结束。可回听候选后采用；仍失败的段落保留缺口，可人工补字。")
                self._persist(identity)
        except Exception:
            with self.lock:
                cancelled = self.closed or self.jobs[identity].get("cancel_requested")
                self.jobs[identity].update(status="cancelled" if cancelled else "failed", phase="stopped", current=None, _finished=time.monotonic(),
                    message="局部补转已取消，已生成候选保留；未自动覆盖原稿。" if cancelled else "局部补转未完成，已生成候选保留；未自动覆盖原稿，可重试或人工补字。")
                self._persist(identity)

    def apply(self, identity, job_id, ids):
        with self.lock:
            job = self.jobs.get(identity)
            if not job:
                saved = self.store.get(identity)
                if saved.get("local_repair_state") and saved.get("local_repair_private"):
                    job = {**saved["local_repair_state"], **saved["local_repair_private"]}
                    if job.get("status") == "running":
                        job.update(status="interrupted", phase="interrupted", current=None)
            if not job or job["id"] != job_id:
                raise ValueError("此候选已过期，请重新补转；原稿仍保留。")
            source = fingerprint(self.store.audio_path(self.store.get(identity)))
            updated = copy.deepcopy(job)
            def save(item):
                apply_candidates(item, job, ids, source)
                for result in updated["results"]:
                    if result["segment_id"] in ids:
                        result["status"] = "applied"
                item["local_repair_state"] = self.public(updated)
            item = self.store.mutate(identity, save)
            self.jobs[identity] = updated
            return item

    def close(self):
        with self.lock:
            self.closed = True
            if self.process and self.process.poll() is None:
                self.process.terminate()


def worker(data):
    from core.asr_guard import inspect_result
    path, config, row, strategy = data["path"], data["config"], data["row"], data["strategy"]
    _, padding, filters, temperatures = STRATEGIES[strategy]
    duration = media_duration(path)
    start, end = row["start"], min(duration, row["end"])
    rows, errors = [], []
    step = 15 if strategy == 3 else end - start
    offset = start
    while offset < end - .001:
        boundary = min(end, offset + step)
        left, right = max(0, offset - padding), min(duration, boundary + padding)
        if config.get("backend", "mlx") == "faster":
            from core.local_engine import transcribe
            raw = transcribe(config, path, left, right-left, retry=strategy > 0, words=True, filters=filters, temperatures=temperatures)
        else:
            raw = None
        with tempfile.TemporaryDirectory(prefix="lecture-repair-") as directory:
            wav = str(Path(directory) / "chunk.wav")
            command = ["ffmpeg", "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-ss", str(left), "-i", path, "-map", "0:a:0", "-vn", "-t", str(right-left), "-ar", "16000", "-ac", "1"]
            if filters:
                command += ["-af", filters]
            if raw is None:
                from core.mixed_asr import transcribe_mlx
                subprocess.run(command + [wav], check=True, timeout=45)
                raw = transcribe_mlx(wav, config,
                initial_prompt=config.get("hint_text") or None,
                task="transcribe",
                condition_on_previous_text=False, temperature=temperatures, word_timestamps=True,
                hallucination_silence_threshold=2.0, compression_ratio_threshold=2.4, logprob_threshold=-1.0, no_speech_threshold=.6, verbose=None)
            # Crop context with real word midpoints; context must not leak into a
            # repaired passage or duplicate neighbouring words in the transcript.
            for part in raw.get("segments", []):
                errors.extend(word_timing_reasons(part))
                for word in part.get("words", []):
                    a, b = left + word["start"], left + word["end"]
                    if offset <= (a+b)/2 < boundary and b > a:
                        rows.append({"start": max(a, offset)-start, "end": min(b, boundary)-start,
                                     "text": word["word"], "avg_logprob": part.get("avg_logprob"), "compression_ratio": part.get("compression_ratio")})
        offset = boundary
    checked, validation_errors = inspect_result({"segments": rows}, end-start)
    errors = list(dict.fromkeys(errors + validation_errors))
    # A suspiciously partial candidate stays a gap rather than claiming success.
    if checked and (checked[0]["start"] > min(8, (end-start)*.4) or checked[-1]["end"] < (end-start)*.6):
        errors.append("候选覆盖范围偏短，请人工回听；可能是停顿，也可能漏识别")
    print(json.dumps({"segments": checked, "errors": errors}, ensure_ascii=False))


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker(json.loads(sys.stdin.read()))
