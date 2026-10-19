"""Optional offline MLX worker. The web server itself has no ML dependencies."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import queue
import time
from uuid import uuid4

from core import pipeline, workflow, audio_prepare
from audio_processing import fingerprint
from asr_checkpoints import Checkpoints
from core.asr_guard import CHUNK_SECONDS, VERSION, ALIGNMENT_VERSION, guarded_window, issue_segment
from core.languages import language, check_model

WINDOW_TIMEOUT = 180  # seconds without a completed attempt/phase; no endless GPU loop
ACTIVE = {"queued", "running", "cancelling"}


def worker_env(config):
    env = dict(os.environ, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONDONTWRITEBYTECODE="1")
    if config.get("backend", "mlx") == "mlx":
        # Keep an existing MLX virtualenv isolated from newly installed CPU
        # dependencies (NumPy/native wheels may use a different Python ABI).
        vendor = (Path(__file__).resolve().parent / ".portable" / "vendor").resolve()
        env["PYTHONPATH"] = os.pathsep.join(part for part in env.get("PYTHONPATH", "").split(os.pathsep) if part and Path(part).resolve() != vendor)
    return env


def configuration(value):
    value = value or {}
    result = {}
    for key in ("python_path", "model_path"):
        text = value.get(key, "")
        if not isinstance(text, str) or len(text) > 2048 or any(c in text for c in "\n\r\0"):
            raise ValueError("本地模型路径格式无效。")
        result[key] = text.strip()
    result["language"] = language(value.get("language", "auto"))
    result["backend"] = value.get("backend", "mlx")
    if result["backend"] not in {"mlx", "faster"}:
        raise ValueError("请选择 MLX 或 faster-whisper 本地后端。")
    return result


def checked_config(value):
    config = configuration(value)
    python = Path(config["python_path"] or sys.executable).expanduser().absolute()
    if not re.fullmatch(r"python(?:3(?:\.\d+)?)?(?:\.exe)?", python.name) or not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError("请选择已安装 mlx-whisper 的 Python 可执行文件（python/python3）。")
    if not config["model_path"]:
        raise ValueError("请先在设置中选择已下载的 MLX Whisper 模型目录。")
    model = Path(config["model_path"]).expanduser().resolve()
    weights = ("model.bin",) if config["backend"] == "faster" else ("weights.npz", "weights.safetensors")
    if not model.is_dir() or not (model / "config.json").is_file() or not any((model / name).is_file() for name in weights):
        raise ValueError("本地模型目录须含 config.json，MLX 需 npz/safetensors，faster-whisper 需 model.bin。请先完成首次安装；识别时不自动下载。")
    if config["backend"] == "faster" and not (model / "tokenizer.json").is_file():
        raise ValueError("faster-whisper 缺少本地 tokenizer.json；请完成模型安装，避免识别时隐式下载。")
    config.update(python_path=str(python), model_path=str(model))
    check_model(config)
    return config


def probe(value):
    config = checked_config(value)
    env = worker_env(config)
    try:
        result = subprocess.run([config["python_path"], "-c", "import faster_whisper, av" if config["backend"] == "faster" else "import mlx_whisper"], env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("本地环境检查失败或超时；未启动转写，也未下载模型。") from None
    if result.returncode:
        raise ValueError("所选 Python 无法导入对应 Whisper 后端；请先运行首次安装或选择已有环境。")
    if config["backend"] == "mlx" and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
        raise ValueError("本地转写需要 FFmpeg 和 ffprobe。")
    return {"ok": True, "message": "Python、Whisper 后端和本地权重文件可用；尚未加载模型或验证实际识别效果。"}


class Jobs:
    def __init__(self, store):
        self.store, self.lock, self.jobs = store, threading.RLock(), {}
        self.process = None
        self.checkpoints = Checkpoints(store.root)

    @staticmethod
    def public(job):
        return {key: job[key] for key in ("id", "lecture_id", "status", "progress", "message", "phase", "completed_chunks", "processed_chunks", "total_chunks", "issue_count", "resumed_chunks", "resume_available", "audio_preparation", "preparation_progress") if key in job}

    def _persist(self, job):
        with self.lock:
            latest = [row for row in self.jobs.values() if row["lecture_id"] == job["lecture_id"]]
            if latest and latest[-1]["id"] != job["id"]:
                return
            public = self.public(job)
            self.store.mutate(job["lecture_id"], lambda item: item.update(local_asr_state=public))

    def get(self, identity):
        with self.lock:
            jobs = [row for row in self.jobs.values() if row["lecture_id"] == identity]
            if jobs:
                return self.public(jobs[-1])
        state = self.store.get(identity).get("local_asr_state")
        if state and state["status"] in ACTIVE:
            return {**state, "status": "interrupted", "message": "上次服务已中断；已完成分段保留，可从断点继续。"}
        return state

    def start(self, identity, config, replace=False, resume=True):
        config = checked_config(config)
        if config.get("backend", "mlx") == "mlx" and (not shutil.which("ffmpeg") or not shutil.which("ffprobe")):
            raise ValueError("本地转写需要 FFmpeg 和 ffprobe。")
        item = self.store.get(identity)
        if item["segments"] and replace is not True:
            raise ValueError("已有转写和笔记，请明确确认替换。")
        path = self.store.audio_path(item)
        snapshot = workflow.digest([item["segments"], item["notes"], item["audio"]])
        source = fingerprint(path)
        key = self.checkpoints.key(identity, source, config)
        if audio_prepare.required(path):
            key = workflow.digest([key, audio_prepare.VERSION])
        checkpoint = self.checkpoints.load(key) if resume else {"version": VERSION, "chunks": {}, "duration": None}
        cached = [index for index, part in checkpoint["chunks"].items() if not part.get("issues")]
        with self.lock:
            if any(job["status"] in ACTIVE for job in self.jobs.values()):
                raise ValueError("已有本地转写任务，请等待完成或先取消，避免重复占用内存。")
            job = {"id": uuid4().hex, "lecture_id": identity, "status": "queued", "progress": 0,
                   "message": "等待本地 Whisper 启动；异常段有限重试，已完成段保存断点。", "cancel": threading.Event(),
                   "phase": "queued", "completed_chunks": len(cached), "processed_chunks": len(cached), "total_chunks": 0, "issue_count": 0,
                   "resumed_chunks": len(cached), "resume_available": bool(cached)}
            self.jobs[job["id"]] = job
        self._persist(job)
        threading.Thread(target=self._run, args=(job, path, config, source, snapshot, replace, key, checkpoint), daemon=True).start()
        return self.public(job)

    def cancel(self, identity):
        with self.lock:
            matches = [job for job in self.jobs.values() if job["lecture_id"] == identity and job["status"] in {"queued", "running", "cancelling"}]
            if not matches:
                raise ValueError("没有正在运行的本地任务。")
            job = matches[-1]
            job["cancel"].set()
            job.update(status="cancelling", message="正在取消；原稿和笔记保持不变。")
            if self.process and self.process.poll() is None:
                self.process.terminate()
            self._persist(job)
            return self.public(job)

    def close(self):
        with self.lock:
            for job in self.jobs.values():
                job["cancel"].set()
            if self.process and self.process.poll() is None:
                self.process.terminate()

    def _run(self, job, path, config, source, snapshot, replace, checkpoint_key=None, checkpoint=None):
        process = None
        reader_stop = threading.Event()
        checkpoint = checkpoint or {"version": VERSION, "chunks": {}, "duration": None}
        chunks = checkpoint["chunks"]
        try:
            env = worker_env(config)
            prepared_path = path
            preparation = {"converted": False}
            if audio_prepare.required(path):
                with self.lock:
                    job.update(status="running", phase="preparing_audio", preparation_progress=0, message="先提取音轨并缓存为 16 kHz 单声道 WAV；原视频保留，尚未启动 Whisper。")
                self._persist(job)
                def preparation_progress(value):
                    with self.lock:
                        job["preparation_progress"] = value
                def preparation_process(value):
                    with self.lock:
                        self.process = value
                prepared_path, preparation = audio_prepare.prepare(path, self.store.root, cancel=job["cancel"], on_progress=preparation_progress, on_process=preparation_process)
                with self.lock:
                    job.update(audio_preparation=preparation, preparation_progress=100)
            with self.lock:
                if job["cancel"].is_set():
                    job.update(status="cancelled", message="已取消，原稿未改动。")
                    return
                job.update(status="running", phase="loading", message="音轨已准备好，正在启动 Whisper；后续重试可复用音频缓存。" if preparation["converted"] else "本地识别中；短分段、重复检测和断点保护已启用。")
                process = subprocess.Popen([config["python_path"], str(Path(__file__).resolve()), "--worker"],
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                           text=True, encoding="utf-8", env=env)
                self.process = process
            skip = [int(index) for index, part in chunks.items() if not part.get("issues")]
            process.stdin.write(json.dumps({"audio_path": str(prepared_path), "config": config, "skip": skip,
                                           "cached": chunks}, ensure_ascii=False) + "\n")
            process.stdin.close()
            events, complete = queue.Queue(maxsize=8), False
            def read_events():
                try:
                    for line in process.stdout:
                        while not reader_stop.is_set():
                            try:
                                events.put(line, timeout=.2)
                                break
                            except queue.Full:
                                continue
                        if reader_stop.is_set():
                            return
                except (OSError, ValueError):
                    pass
                finally:
                    while not reader_stop.is_set():
                        try:
                            events.put(None, timeout=.2)
                            break
                        except queue.Full:
                            continue
            threading.Thread(target=read_events, daemon=True).start()
            last_activity = time.monotonic()
            while True:
                if job["cancel"].is_set():
                    break
                try:
                    line = events.get(timeout=.2)
                except queue.Empty:
                    if time.monotonic() - last_activity > WINDOW_TIMEOUT:
                        raise ValueError("当前片段长时间无进展，已停止模型以避免卡死；已完成分段保留，可从断点继续。")
                    continue
                if line is None:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # Ignore library diagnostics, never expose paths/logs.
                if not isinstance(event, dict):
                    continue
                if event.get("kind") == "init":
                    duration = event["duration"]
                    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not 0 < duration <= 7 * 24 * 3600:
                        raise ValueError("模型工作进程返回无效音频时长。")
                    checkpoint["duration"] = duration
                    with self.lock:
                        job["total_chunks"] = math.ceil(duration / CHUNK_SECONDS)
                    last_activity = time.monotonic()
                elif event.get("kind") == "attempt":
                    last_activity = time.monotonic()
                    with self.lock:
                        job.update(phase="retrying" if event.get("retry") else "transcribing",
                                   message=("检测到异常，拆成更短片段重试；不会静默保存重复输出。" if event.get("retry") else "Whisper 分段识别中；已完成段自动保存断点。"))
                elif event.get("kind") == "chunk":
                    index, part = event["index"], event["result"]
                    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < job["total_chunks"]:
                        raise ValueError("模型返回无效分段编号。")
                    start, end = index * CHUNK_SECONDS, min((index + 1) * CHUNK_SECONDS, checkpoint["duration"])
                    if not isinstance(part, dict) or not isinstance(part.get("segments"), list) or not isinstance(part.get("issues"), list):
                        raise ValueError("模型分段结果格式无效。")
                    for row in part["segments"] + part["issues"]:
                        if not start <= row["start"] < row["end"] <= end + .001:
                            raise ValueError("模型分段时间码越界。")
                    if part["segments"]:
                        pipeline.parse_transcript(json.dumps(part["segments"], ensure_ascii=False), "json")
                    chunks[str(index)] = {**part, "start": start, "end": end}
                    chunks[str(index)]["alignment_version"] = ALIGNMENT_VERSION
                    if checkpoint_key:
                        self.checkpoints.save(checkpoint_key, checkpoint)
                    last_activity = time.monotonic()
                    with self.lock:
                        job.update(progress=min(99, int(sum(part["end"] - part["start"] for part in chunks.values()) / checkpoint["duration"] * 100)),
                                   completed_chunks=sum(not bool(part.get("issues")) for part in chunks.values()), processed_chunks=len(chunks),
                                   issue_count=sum(len(part.get("issues", [])) for part in chunks.values()), resume_available=True)
                        self._persist(job)
                elif event.get("kind") == "complete":
                    complete = True
            process.wait(timeout=10)
            if job["cancel"].is_set():
                with self.lock:
                    job.update(status="cancelled", message="已取消，原稿和笔记未改动。")
                return
            if process.returncode or not complete or not checkpoint.get("duration") or len(chunks) != math.ceil(checkpoint["duration"] / CHUNK_SECONDS):
                raise ValueError("本地转写未完成，请检查模型与 MLX 环境；原稿未改动。")
            issues = [issue for part in chunks.values() for issue in part.get("issues", [])]
            rows = sorted([row for part in chunks.values() for row in part["segments"]] + [issue_segment(issue) for issue in issues], key=lambda row: (row["start"], row["end"]))
            if not rows:
                raise ValueError("未得到可用文字；近乎数字静音的片段已跳过，不能据此保证整段没有人声。原稿未改动。")
            parsed = pipeline.parse_transcript(json.dumps(rows, ensure_ascii=False), "json")
            parsed["duration"] = checkpoint["duration"]
            if fingerprint(path) != source:
                raise ValueError("处理期间原录音已变化，未保存识别结果。")
            def save(current):
                if workflow.digest([current["segments"], current["notes"], current["audio"]]) != snapshot:
                    raise ValueError("处理期间原稿、笔记或录音已变化，未覆盖现有内容。")
                # Import here avoids a module cycle when app.py owns the server.
                from app import install_transcript
                install_transcript(current, parsed, json.dumps(rows, ensure_ascii=False), replace)
                current["transcript_source"] = {"provider": "local", "label": "本地 Whisper", "filename": ""}
                current["asr_report"] = {"guard_version": VERSION, "issues": issues, "processed_seconds": checkpoint["duration"],
                                         "alignment_version": ALIGNMENT_VERSION, "legacy_check_chunks": sum(part.get("alignment_version") != ALIGNMENT_VERSION for part in chunks.values()),
                                         "audio_preparation": preparation,
                                         "chunk_seconds": CHUNK_SECONDS, "resumed_chunks": job.get("resumed_chunks", 0),
                                         "complete_without_detected_issues": not bool(issues)}
                for segment in current["segments"]:
                    if segment["text"].startswith("【转写缺口，非录音原文】"):
                        segment.update(asr_issue=True, review_status="needs_review")
                current["warnings"].append("本地自动转写未经人工核对；混合语言、专有名词和静音附近可能识别错误，未进行说话人分离。")
                if issues:
                    current["warnings"].append(f"有 {len(issues)} 个转写缺口：已有限重试，仍异常的输出未当作原文保存；请回听标记范围。处理进度 100% 不代表完整正确转写。")
            with self.lock:
                if job["cancel"].is_set():
                    job.update(status="cancelled", message="已取消，原稿未改动。")
                    return
                self.store.mutate(job["lecture_id"], save)
                job.update(status="completed_with_warnings" if issues else "completed", phase="finished", progress=100,
                           issue_count=len(issues), processed_chunks=len(chunks), resume_available=bool(issues),
                           message=f"音频处理完毕：{len(parsed['segments'])} 段，{len(issues)} 处转写缺口。" if issues else f"本地转写完成：{len(parsed['segments'])} 段，未检测到明显循环，仍需核对。")
        except Exception as exc:
            with self.lock:
                if job["cancel"].is_set():
                    job.update(status="cancelled", message="已取消，原稿未改动。")
                else:
                    safe = str(exc) if isinstance(exc, (ValueError, pipeline.PipelineError)) else "本地任务未完成；请检查模型环境，原稿未改动。"
                    job.update(status="failed", message=safe[:250])
        finally:
            reader_stop.set()
            if process:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                if process.stdout:
                    process.stdout.close()
            with self.lock:
                if self.process is process:
                    self.process = None
            if job.get("lecture_id"):
                try:
                    self._persist(job)
                except Exception:
                    pass


def worker():
    data = json.loads(sys.stdin.readline())
    config, path = data["config"], Path(data["audio_path"])
    if config.get("backend", "mlx") == "faster":
        from core.local_engine import duration as read_duration
        duration = read_duration(path)
    else:
        duration = float(subprocess.check_output([shutil.which("ffprobe"), "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=20))
    if not math.isfinite(duration) or not 0 < duration <= 7 * 24 * 3600:
        raise ValueError("invalid audio duration")
    def emit(event):
        print(json.dumps(event, ensure_ascii=False), flush=True)
    emit({"kind": "init", "duration": duration})
    skip, cached = set(data.get("skip", [])), data.get("cached", {})
    previous_text = ""
    def decode(offset, length, retry):
        emit({"kind": "attempt", "offset": offset, "length": length, "retry": retry})
        if config.get("backend", "mlx") == "faster":
            from core.local_engine import transcribe
            return transcribe(config, path, offset, length, retry=retry, on_window=lambda start, duration: emit({"kind": "attempt", "offset": offset + start, "length": duration, "retry": retry}))
        with tempfile.TemporaryDirectory(prefix="lecture-asr-") as tmp:
            wav = Path(tmp) / "chunk.wav"
            # QTA can contain a second spatial track with more channels but an
            # unsupported codec. Do not let FFmpeg auto-select it over track 0.
            subprocess.run([shutil.which("ffmpeg"), "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-ss", str(offset), "-i", str(path), "-map", "0:a:0", "-vn", "-t", str(length), "-ar", "16000", "-ac", "1", str(wav)], check=True, timeout=45)
            import array
            import wave
            with wave.open(str(wav), "rb") as handle:
                pcm = array.array("h", handle.readframes(handle.getnframes()))
            if sys.byteorder != "little":
                pcm.byteswap()
            if pcm and max(abs(sample) for sample in pcm) <= 2:
                return {"digital_silence": True}
            # Optional imports only on first non-silent inference, no downloads.
            from core.mixed_asr import transcribe_mlx
            return transcribe_mlx(str(wav), config,
                                           on_window=lambda start, duration: emit({"kind": "attempt", "offset": offset + start, "length": duration, "retry": retry}),
                                           task="transcribe", condition_on_previous_text=False, verbose=None,
                                           temperature=(0.2, 0.4) if retry else (0.0, 0.2),
                                           compression_ratio_threshold=2.4, logprob_threshold=-1.0, no_speech_threshold=.6,
                                           word_timestamps=True, hallucination_silence_threshold=2.0)
    for index, offset in enumerate(range(0, math.ceil(duration), CHUNK_SECONDS)):
        if index in skip:
            previous_text = "".join(row["text"] for row in cached[str(index)]["segments"])
            continue
        result = guarded_window(decode, offset, min(CHUNK_SECONDS, duration - offset), previous_text)
        previous_text = "".join(row["text"] for row in result["segments"])
        emit({"kind": "chunk", "index": index, "result": result})
    emit({"kind": "complete"})


if __name__ == "__main__" and sys.argv[1:] == ["--worker"]:
    worker()
