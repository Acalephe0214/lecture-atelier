"""Bounded mixed-language routing. No cloud fallback or text-based guessing."""
import math
import re
from .languages import candidates, decoder_language, LanguageUncertain

VERSION = "mixed-short-windows-v1"
SAMPLE_RATE = 16000
WINDOW = 12
CONTEXT = 1


def choose_language(probabilities, allowed):
    try:
        scores = {code: float(score) for code, score in dict(probabilities).items() if math.isfinite(float(score)) and 0 <= float(score) <= 1}
    except (ValueError, TypeError, AttributeError):
        raise LanguageUncertain() from None
    present = {code: scores[code] for code in allowed if code in scores}
    if not present:
        raise LanguageUncertain()
    best = max(present, key=present.get)
    # Conservative heuristics, NOT calibrated correctness probabilities. Avoid
    # confidently forcing an out-of-scope language into one selected by a user.
    if present[best] < .15 or sum(present.values()) < .25 or max(scores.values()) > present[best] * 2:
        raise LanguageUncertain()
    return best


def _join(words):
    text = ""
    for word in words:
        piece = word["word"]
        if text and piece and not piece[0].isspace() and re.search(r"[A-Za-zÀ-ỹ0-9]$", text) and re.match(r"[A-Za-zÀ-ỹ0-9]", piece):
            text += " "
        text += piece
    return text.strip()


def decode_mixed(audio, allowed, detect, recognize, *, keep_words=False, on_window=None):
    """12s cores with 1s context; crop by real word midpoints, never duplicate it."""
    rows = []
    windows = range(0, len(audio), WINDOW * SAMPLE_RATE)
    for start in windows:
        end = min(len(audio), start + WINDOW * SAMPLE_RATE)
        core = audio[start:end]
        if not len(core) or float(abs(core).max()) < .00006:
            continue
        if on_window:
            on_window(start / SAMPLE_RATE, (end - start) / SAMPLE_RATE)
        selected = choose_language(detect(core), allowed)
        left, right = max(0, start - CONTEXT * SAMPLE_RATE), min(len(audio), end + CONTEXT * SAMPLE_RATE)
        result = recognize(audio[left:right], selected)
        if not isinstance(result, dict) or not isinstance(result.get("segments"), list):
            raise LanguageUncertain()
        found = False
        for part in result["segments"]:
            words = []
            for word in part.get("words", []):
                a, b = word.get("start"), word.get("end")
                if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (a, b)) or b <= a:
                    raise LanguageUncertain()
                a, b = left / SAMPLE_RATE + a, left / SAMPLE_RATE + b
                if start / SAMPLE_RATE <= (a + b) / 2 < end / SAMPLE_RATE:
                    if not isinstance(word.get("word"), str):
                        raise LanguageUncertain()
                    clipped = {"start": max(a, start / SAMPLE_RATE), "end": min(b, end / SAMPLE_RATE), "word": word["word"]}
                    if clipped["end"] > clipped["start"]:
                        words.append(clipped)
            if words:
                found = True
                row = {key: part[key] for key in ("avg_logprob", "compression_ratio", "no_speech_prob") if key in part}
                row.update(start=words[0]["start"], end=words[-1]["end"], text=_join(words))
                if keep_words:
                    row["words"] = words
                rows.append(row)
        if not found:
            raise LanguageUncertain()
    return {"segments": rows} if rows else {"digital_silence": True, "segments": []}


def transcribe_mlx(audio, config, *, on_window=None, **options):
    """Uses the installed MLX model holder; never loads remote weights."""
    import mlx_whisper
    allowed = candidates(config["language"])
    options.update(task="transcribe", language=decoder_language(config["language"]))
    if not allowed:
        return mlx_whisper.transcribe(audio, path_or_hf_repo=config["model_path"], **options)
    import importlib
    import mlx.core as mx
    import numpy as np
    import wave
    from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim, N_FRAMES, N_SAMPLES
    module = importlib.import_module("mlx_whisper.transcribe")
    model = module.ModelHolder.get_model(config["model_path"], mx.float16)
    with wave.open(str(audio), "rb") as handle:
        if (handle.getnchannels(), handle.getframerate(), handle.getsampwidth()) != (1, 16000, 2):
            raise ValueError("混合语言识别需要 16 kHz 单声道 PCM。")
        pcm = np.frombuffer(handle.readframes(handle.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
    def detect(samples):
        mel = log_mel_spectrogram(samples, n_mels=model.dims.n_mels, padding=N_SAMPLES)
        return model.detect_language(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))[1]
    def recognize(samples, selected):
        return mlx_whisper.transcribe(samples, path_or_hf_repo=config["model_path"], **{**options, "language": selected, "word_timestamps": True})
    return decode_mixed(pcm, allowed, detect, recognize, keep_words=options.get("word_timestamps", False), on_window=on_window)
