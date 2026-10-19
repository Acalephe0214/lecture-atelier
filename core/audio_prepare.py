"""Private, reusable video-to-Whisper PCM cache. Never modifies originals."""
import hashlib
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import wave

VERSION = "pcm16k-mono-v1"
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v", ".qt", ".qta", ".qat"}


def required(path):
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def _path(source, root):
    from audio_processing import fingerprint
    folder = Path(root) / "asr-audio"
    if folder.is_symlink():
        raise ValueError("转写音频缓存目录不能是软链接。")
    key = hashlib.sha256((VERSION + fingerprint(source)).encode()).hexdigest()
    path = folder / (key + ".wav")
    if path.is_symlink():
        raise ValueError("转写音频缓存文件不能是软链接。")
    return path


def cached(source, root):
    if not required(source):
        return None
    path = _path(source, root)
    try:
        with wave.open(str(path), "rb") as handle:
            if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, 16000) or handle.getnframes() <= 0:
                return None
            expected = handle.getnframes() * 2
            if path.stat().st_size < expected + 44:
                return None
    except (OSError, EOFError, wave.Error):
        return None
    return path


def prepare(source, root, *, cancel=None, on_progress=None, on_process=None, ffmpeg=None):
    """Extract first audio track once, retaining timeline origin and silences."""
    from audio_processing import fingerprint, media_duration
    from .local_engine import media_program
    source = Path(source)
    if not required(source):
        return source, {"converted": False}
    if cancel and cancel.is_set():
        raise ValueError("音频准备已取消，原文件保留。")
    existing = cached(source, root)
    if existing:
        return existing, {"converted": True, "cached": True, "format": "WAV", "sample_rate": 16000, "channels": 1}
    program = ffmpeg or media_program()
    if not program:
        raise ValueError("视频转写需先提取音轨；未找到 FFmpeg，请完成首次安装，原文件保留。")
    before = fingerprint(source)
    duration = media_duration(source)
    if not math.isfinite(duration) or not 0 < duration <= 7 * 24 * 3600:
        raise ValueError("视频时长无效，未启动转写。")
    destination = _path(source, root)
    destination.parent.mkdir(mode=0o700, exist_ok=True)
    if shutil.disk_usage(destination.parent).free < duration * 32000 + 64 * 1024 * 1024:
        raise ValueError("磁盘空间不足，无法生成转写音轨缓存；原视频未改动。")
    descriptor, name = tempfile.mkstemp(prefix=".preparing-", suffix=".wav", dir=destination.parent)
    os.close(descriptor)
    temporary, process, timer = Path(name), None, None
    report = on_progress or (lambda value: None)
    try:
        report(0)
        # -copyts/-start_at_zero and first_pts=0 retain leading silence relative
        # to the media timeline. No denoising, silence removal or speed changes.
        process = subprocess.Popen([program, "-hide_banner", "-loglevel", "error", "-nostdin", "-y", "-protocol_whitelist", "file,pipe", "-copyts", "-start_at_zero", "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn", "-map_metadata", "-1", "-af", "aresample=async=1:first_pts=0", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-progress", "pipe:1", "-nostats", str(temporary)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if on_process:
            on_process(process)
        def stop_if_stalled():
            try:
                if process.poll() is None:
                    process.terminate()
            except OSError:
                pass
        timer = threading.Timer(1200, stop_if_stalled)
        timer.daemon = True
        timer.start()
        for line in process.stdout:
            if cancel and cancel.is_set():
                raise ValueError("音频准备已取消，原文件保留。")
            if line.startswith("out_time_us="):
                try:
                    progress = max(0, min(99, int(float(line.split("=", 1)[1]) / 1e6 / duration * 100)))
                except (ValueError, OverflowError):
                    continue
                report(progress)
        if process.wait(timeout=10):
            raise ValueError("音轨提取失败、视频没有可读取音轨或处理超时；未启动 Whisper，原视频保留。")
        if cancel and cancel.is_set():
            raise ValueError("音频准备已取消，原文件保留。")
        with wave.open(str(temporary), "rb") as handle:
            if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, 16000) or handle.getnframes() <= 0:
                raise ValueError("转写音轨缓存无效，未启动 Whisper。")
        if fingerprint(source) != before:
            raise ValueError("提取期间原视频发生变化，未使用旧音轨启动识别。")
        temporary.chmod(0o600)
        os.replace(temporary, destination)
        report(100)
        return destination, {"converted": True, "cached": False, "format": "WAV", "sample_rate": 16000, "channels": 1}
    finally:
        if timer:
            timer.cancel()
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
        if temporary.exists():
            temporary.unlink()  # Only this function's private, newly created temp.
