"""Optional cross-platform Whisper engine. Inference is strictly local."""
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

_model = None
_model_path = None


def media_program():
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        return None


def duration(path):
    import av
    with av.open(str(path), options={"protocol_whitelist": "file,pipe"}) as container:
        if not container.streams.audio:
            raise ValueError("录音没有可识别的音轨。")
        stream = container.streams.audio[0]
        value = float(stream.duration * stream.time_base) if stream.duration is not None else float(container.duration or 0) / av.time_base
    if not math.isfinite(value) or not 0 < value <= 7 * 24 * 3600:
        raise ValueError("录音时长无效。")
    return value


def audio_window(path, offset, length):
    import av
    import numpy as np
    chunks = []
    # Decode FIRST audio track only (iPhone QTA can have an unsupported second
    # spatial track). Seek back to a keyframe, crop by actual timestamps.
    with av.open(str(path), options={"protocol_whitelist": "file,pipe"}) as container:
        stream = container.streams.audio[0]
        container.seek(max(0, int(offset / stream.time_base)), stream=stream, backward=True)
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        cursor = offset
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                start = float(resampled.pts * resampled.time_base) if resampled.pts is not None else cursor
                data = resampled.to_ndarray().reshape(-1)
                end = start + len(data) / 16000
                cursor = end
                if start >= offset + length:
                    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
                left = max(0, math.ceil((offset - start) * 16000))
                right = min(len(data), math.floor((offset + length - start) * 16000))
                if right > left:
                    chunks.append(data[left:right])
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def transcribe(config, path, offset, length, retry=False, words=False, filters=None, temperatures=None, on_window=None):
    global _model, _model_path
    if config.get("backend", "mlx") == "mlx":
        raise ValueError("MLX 转写使用现有工作进程。")
    from faster_whisper import WhisperModel
    if not (Path(config["model_path"]) / "tokenizer.json").is_file():
        raise ValueError("缺少本地 tokenizer.json，未加载模型或发起下载。")
    if _model is None or _model_path != config["model_path"]:
        # An explicit local folder and local_files_only prevent hidden model
        # downloads at inference time; setup is the only download step.
        _model = WhisperModel(config["model_path"], device="cpu", compute_type="int8", local_files_only=True)
        _model_path = config["model_path"]
    if filters and media_program():
        with tempfile.TemporaryDirectory(prefix="lecture-filter-") as tmp:
            wav = str(Path(tmp) / "chunk.wav")
            subprocess.run([media_program(), "-v", "error", "-nostdin", "-protocol_whitelist", "file,pipe", "-ss", str(offset), "-i", str(path), "-map", "0:a:0", "-vn", "-t", str(length), "-af", filters, "-ar", "16000", "-ac", "1", wav], check=True, timeout=45)
            audio = audio_window(wav, 0, length)
    else:
        audio = audio_window(path, offset, length)
    if not len(audio) or float(abs(audio).max()) < .00006:
        return {"digital_silence": True, "segments": []}
    from .languages import candidates, decoder_language
    from .mixed_asr import decode_mixed
    allowed = candidates(config["language"])

    def recognize(samples, selected):
        segments, _ = _model.transcribe(
            samples, language=selected, initial_prompt=config.get("hint_text") or None,
            task="transcribe", beam_size=5, condition_on_previous_text=False,
            word_timestamps=True, hallucination_silence_threshold=2.0,
            temperature=temperatures or ((.2, .4) if retry else (0, .2)), vad_filter=False,
            compression_ratio_threshold=2.4, log_prob_threshold=-1, no_speech_threshold=.6)
        rows = []
        for row in segments:
            part = {name: getattr(row, name) for name in ("start", "end", "text", "avg_logprob", "compression_ratio", "no_speech_prob")}
            if row.words:
                part["words"] = [{"start": word.start, "end": word.end, "word": word.word} for word in row.words or []]
            rows.append(part)
        return {"segments": rows}
    if allowed:
        return decode_mixed(audio, allowed, lambda samples: _model.detect_language(audio=samples, vad_filter=False)[2], recognize, keep_words=words, on_window=on_window)
    return recognize(audio, decoder_language(config["language"]))
