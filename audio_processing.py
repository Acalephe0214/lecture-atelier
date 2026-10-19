"""Optional, local denoising cache; never modifies the indexed original."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import threading
from uuid import uuid4

from local_sources import LocalSourceError, audio_metadata

PROFILE = "voice-light-v1"
FILTER = "highpass=f=70,afftdn=nr=8:nf=-45:tn=1:gs=4"
PROFILES = {
    "denoised": {"id": PROFILE, "filter": FILTER, "label": "降噪听课版 · 轻度"},
    "keyboard": {"id": "keyboard-declick-v1", "filter": "highpass=f=70,adeclick=w=30:o=75:a=2:t=2:b=2:m=s,afftdn=nr=6:nf=-45:tn=1:gs=4", "label": "键盘点击抑制 · 实验版"},
}


def fingerprint(path):
    path = Path(path).resolve(strict=True)
    info = path.stat()
    raw = f"{path}\0{info.st_size}\0{info.st_mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()


def processed_path(store, item, version):
    if version not in PROFILES:
        raise LocalSourceError("不支持这个录音版本。")
    entry = item.get("audio_derivatives", {}).get(version)
    if not entry:
        raise LocalSourceError("这节课尚未生成降噪试听版，请先使用原录音。")
    source = store.audio_path(item)
    if fingerprint(source) != entry.get("source_fingerprint"):
        raise LocalSourceError("原录音已变化，旧降噪缓存已失效，请重新生成。")
    name = entry.get("storage_name", "")
    root = store.root / "processed"
    if root.resolve() != root:
        raise LocalSourceError("降噪缓存目录不可用，请检查本地缓存位置。")
    path = (root / name).resolve()
    if not name or Path(name).name != name or path.parent != root or not path.is_file():
        raise LocalSourceError("降噪缓存不存在或不可用，原录音仍保留。")
    return path


def public_versions(store, item):
    if not item.get("audio"):
        return []
    base = f"/api/lectures/{item['id']}/audio"
    versions = [{"id": "original", "label": "原录音", "url": base, "available": True}]
    for version, profile in PROFILES.items():
        entry = item.get("audio_derivatives", {}).get(version)
        if not entry:
            continue
        try:
            processed_path(store, item, version)
            available, reason = True, ""
        except (LocalSourceError, OSError):
            available, reason = False, "原音已变化或降噪缓存不可用"
        versions.append({"id": version, "label": profile["label"], "url": base + "?version=" + version,
                         "available": available, "reason": reason, "profile": entry.get("profile", ""),
                         "revision": entry.get("generated_at", "")})
    return versions


def media_duration(path):
    if Path(path).suffix.lower() in {".wav", ".m4a", ".mp4", ".mov", ".qt", ".qta", ".qat"}:
        return audio_metadata(path)["duration"]
    program = shutil.which("ffprobe")
    if not program:
        try:
            from core.local_engine import duration
            return duration(path)
        except ImportError:
            raise LocalSourceError("此录音格式的时长检查需要 FFprobe 或 PyAV。") from None
    value = float(subprocess.check_output([program, "-v", "error", "-protocol_whitelist", "file,pipe", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], timeout=20))
    if not math.isfinite(value) or value <= 0:
        raise LocalSourceError("无法读取有效的录音时长。")
    return value


def generate(store, identity, ffmpeg=None, on_progress=None, cancel_event=None, on_process=None, profile="denoised"):
    if profile not in PROFILES:
        raise LocalSourceError("未知的降噪处理方式。")
    preset = PROFILES[profile]
    from core.local_engine import media_program
    program = ffmpeg or media_program()
    if not program:
        raise LocalSourceError("本地降噪需要 FFmpeg；不影响原录音播放。")
    item = store.get(identity)
    source = store.audio_path(item)
    source_hash = fingerprint(source)
    existing = item.get("audio_derivatives", {}).get(profile)
    if existing and existing.get("source_fingerprint") == source_hash and existing.get("profile") == preset["id"]:
        try:
            return {"status": "cached", "path": str(processed_path(store, item, profile))}
        except LocalSourceError:
            pass
    directory = store.root / "processed"
    directory.mkdir(exist_ok=True, mode=0o700)
    if directory.resolve() != directory:
        raise LocalSourceError("降噪缓存目录不能指向其他位置。")
    destination = directory / (profile + "-" + uuid4().hex + ".m4a")
    original_duration = media_duration(source)
    process = None
    try:
        if cancel_event and cancel_event.is_set():
            raise LocalSourceError("已取消生成，原录音保持不变。")
        process = subprocess.Popen([program, "-hide_banner", "-loglevel", "error", "-nostdin", "-n", "-protocol_whitelist", "file,pipe", "-i", str(source),
                    "-map", "0:a:0", "-vn", "-map_metadata", "-1", "-filter_threads", "2", "-af", preset["filter"],
                    "-c:a", "aac", "-ar", "48000", "-b:a", "96k", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(destination)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if on_process:
            on_process(process)
        for line in process.stdout:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                raise LocalSourceError("已取消生成，原录音保持不变。")
            if on_progress and line.startswith("out_time_us="):
                try:
                    progress = min(99, max(0, int(int(line.split("=", 1)[1]) / 1_000_000 / original_duration * 100)))
                    on_progress(progress)
                except ValueError:
                    pass
        if process.wait(timeout=10):
            raise LocalSourceError("本地降噪未完成，原录音和已有听课版未改动。")
        if cancel_event and cancel_event.is_set():
            raise LocalSourceError("已取消生成，原录音保持不变。")
    except Exception:
        if destination.exists():
            destination.unlink()  # Only this newly generated UUID cache, never source.
        raise
    finally:
        if process:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            if process.stdout:
                process.stdout.close()
    if fingerprint(source) != source_hash:
        raise LocalSourceError("处理期间原音发生变化，未把缓存挂接到课次。")
    duration = audio_metadata(destination)["duration"]
    if abs(duration - original_duration) > .1:
        raise LocalSourceError("降噪缓存时长与原音不匹配，未挂接，避免破坏时间码。")
    destination.chmod(0o600)
    entry = {"storage_name": destination.name, "source_fingerprint": source_hash,
             "profile": preset["id"], "filter": preset["filter"], "duration": duration, "size": destination.stat().st_size,
             "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    def save(current):
        if fingerprint(store.audio_path(current)) != source_hash:
            raise LocalSourceError("课次原音已更换，未挂接降噪缓存。")
        current.setdefault("audio_derivatives", {})[profile] = entry
    store.mutate(identity, save)
    return {"status": "generated", "path": str(destination), "duration": duration,
            "original_duration": original_duration, "size": entry["size"], "profile": preset["id"]}


class DenoiseJobs:
    """One background listening-cache job; no inference, cloud or source writes."""
    def __init__(self, store):
        self.store, self.lock, self.jobs = store, threading.Lock(), {}
        self.process = None
        self.cancel_event = threading.Event()

    def get(self, identity):
        with self.lock:
            return dict(self.jobs[identity]) if identity in self.jobs else None

    def start(self, identity, profile="denoised"):
        if profile not in PROFILES:
            raise LocalSourceError("未知的降噪处理方式。")
        self.store.audio_path(self.store.get(identity))
        if not shutil.which("ffmpeg"):
            raise LocalSourceError("生成听课版需要本地 FFmpeg。")
        with self.lock:
            if any(job["status"] == "running" for job in self.jobs.values()):
                raise LocalSourceError("已有听课版正在生成，请稍后再试。")
            self.cancel_event = threading.Event()
            self.jobs[identity] = {"status": "running", "progress": 0, "message": "本机生成降噪听课版，原录音不改动。"}
        threading.Thread(target=self._run, args=(identity, profile), daemon=True).start()
        return self.get(identity)

    def _run(self, identity, profile="denoised"):
        own_process = None
        def progress(value):
            with self.lock:
                self.jobs[identity]["progress"] = value
        def capture(process):
            nonlocal own_process
            own_process = process
            with self.lock:
                self.process = process
                if self.cancel_event.is_set():
                    process.terminate()
        try:
            generate(self.store, identity, on_progress=progress, cancel_event=self.cancel_event, on_process=capture, profile=profile)
            with self.lock:
                self.jobs[identity].update(status="completed", progress=100, message="降噪听课版已就绪，可切换试听；原录音保留。")
        except Exception:
            with self.lock:
                self.jobs[identity].update(status="failed", message="听课版未生成，请检查 FFmpeg 和原文件；原录音仍保留。")
        finally:
            with self.lock:
                if self.process is own_process:
                    self.process = None

    def close(self):
        with self.lock:
            self.cancel_event.set()
            if self.process and self.process.poll() is None:
                self.process.terminate()


if __name__ == "__main__":
    import argparse
    from store import Store
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lecture_id")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).parent / ".runtime")
    args = parser.parse_args()
    print("本机生成轻度降噪试听缓存；原录音不改动。", flush=True)
    print(json.dumps(generate(Store(args.data_dir), args.lecture_id), ensure_ascii=False, indent=2))
