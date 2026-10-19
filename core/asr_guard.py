"""Conservative ASR heuristics, not a claim of transcription correctness."""
from __future__ import annotations

import math
import re
from .languages import LanguageUncertain

VERSION = "whisper-guard-v2"
CHUNK_SECONDS = 60
ALIGNMENT_VERSION = "word-alignment-partial-v1"


def normalized(text):
    return "".join(character for character in text.casefold() if character.isalnum())


def word_timing_reasons(row):
    """Catch collapsed word alignment even when segment confidence looks good.

    Isolated zero-length punctuation/short tokens are not an anomaly. A cluster
    of lexical words at a single time is review evidence, not spoken content.
    """
    words = row.get("words")
    if not isinstance(words, list):
        return []
    durations = []
    for word in words:
        if not isinstance(word, dict) or not isinstance(word.get("word"), str) or not normalized(word["word"]):
            continue
        a, b = word.get("start"), word.get("end")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (a, b)) or b < a:
            return ["模型词级时间码无效"]
        durations.append(b - a)
    if len(durations) >= 4 and sum(d <= .005 for d in durations) >= max(4, len(durations) * .5):
        return ["词级时间码成片塌缩，疑似静音幻觉，需回听"]
    return []


def inspect_result(result, length, previous_text=""):
    """Return local timestamps and rejection reasons; never deduplicate speech."""
    if not isinstance(result, dict) or not isinstance(result.get("segments"), list):
        return [], ["模型没有返回有效段落"]
    rows, reasons, last_start = [], [], -1
    for row in result["segments"]:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            return [], ["模型段落格式无效"]
        text = row["text"].strip()
        if not text:
            continue
        reasons.extend(word_timing_reasons(row))
        start, end = row.get("start"), row.get("end")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in (start, end)):
            return [], ["模型时间码无效"]
        # Whisper can timestamp a final token slightly into its padded tail.
        # Only clip <= 0.5 s of tail padding, never move an out-of-range start
        # or repair reversed/zero-duration timestamps by inventing timings.
        if start < 0 or start >= length or end <= start or start < last_start or end > length + .5:
            return [], ["模型时间码倒退或超出音频片段"]
        last_start = start
        rows.append({"start": round(start, 3), "end": round(min(end, length), 3), "text": text})
        if len(normalized(text)) >= 80 and len(normalized(text)) / max(end - start, .01) > 45:
            reasons.append("短时间内生成过量文字")
        for field, threshold, test, label in (
            ("compression_ratio", 3.0, lambda a, b: a > b, "文本压缩比异常，疑似重复"),
            ("avg_logprob", -1.5, lambda a, b: a < b, "模型文字置信偏低"),
        ):
            value = row.get(field)
            if isinstance(value, (int, float)) and math.isfinite(value) and test(value, threshold) and len(normalized(text)) >= 20:
                reasons.append(label)
    if not rows:
        return [], ["非近乎数字静音的片段未得到文字，不能假定无人说话"]
    text = normalized("".join(row["text"] for row in rows))
    if len(text) > 12000:
        reasons.append("单个音频片段返回文字过多")
    # Bound regex input and phrase lengths. Repetition can be legitimate, so
    # flagged text is reviewed/retried, not silently collapsed or endorsed.
    sample = text[:12000]
    if re.search(r"(.)\1{11,}", sample) or re.search(r"(.{2,60}?)\1{5,}", sample):
        reasons.append("检测到连续短语或字符循环")
    recent = []
    for row in rows:
        current = normalized(row["text"])
        recent.append(current)
        if len(recent) >= 3 and len(current) >= 6 and recent[-3:] == [current] * 3:
            reasons.append("多个相邻段落重复同一句")
    previous = normalized(previous_text)
    if len(text) >= 40 and text == previous:
        reasons.append("与上一音频片段的转写完全相同，需核对")
    return rows, list(dict.fromkeys(reasons))


def partial_result(result, length, previous_text=""):
    """Last-resort salvage: validate every retained row; localize bad intervals.

    Never clip a hallucinated long sentence into a valid timestamp, interpolate
    a missing word, or salvage global repetition. Invalid/unlocatable times
    still reject the whole attempt. The original strict validator is unchanged.
    """
    if not isinstance(result, dict) or not isinstance(result.get("segments"), list):
        return None
    good, issues, last_start = [], [], -1
    for row in result["segments"]:
        if not isinstance(row, dict) or not isinstance(row.get("text"), str):
            return None
        if not row["text"].strip():
            continue
        a, b = row.get("start"), row.get("end")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in (a, b)) or a < 0 or a < last_start or b < a or a > length + .5:
            return None
        last_start = a
        checked, errors = inspect_result({"segments": [row]}, length)
        if errors:
            start, end = min(a, max(0, length - .5)), min(max(b, a + .02), length)
            if end <= start:
                return None
            issues.append({"start": start, "end": end, "reasons": errors})
        else:
            good.extend(checked)
    if not issues or not good:
        return None
    # A bad interval owns every overlap; never retain a neighbouring sentence
    # across it, and never silently drop the conflicting sentence either.
    changed = True
    while changed:
        changed = False
        for row in good:
            for issue in issues:
                if row["start"] < issue["end"] and row["end"] > issue["start"]:
                    a, b = min(issue["start"], row["start"]), max(issue["end"], row["end"])
                    changed = changed or (a, b) != (issue["start"], issue["end"])
                    issue.update(start=a, end=b)
    kept = [row for row in good if not any(row["start"] < i["end"] and row["end"] > i["start"] for i in issues)]
    if not kept or inspect_result({"segments": kept}, length, previous_text)[1]:
        return None
    merged = []
    for issue in sorted(issues, key=lambda row: row["start"]):
        if merged and issue["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], issue["end"])
            merged[-1]["reasons"] = list(dict.fromkeys(merged[-1]["reasons"] + issue["reasons"]))
        else:
            merged.append(issue)
    return kept, merged


def guarded_window(decode, offset, length, previous_text=""):
    """One normal attempt, then two half-window attempts, no unbounded retry.

    decode(start, length, retry) returns Whisper dict or {'digital_silence':True}.
    None of the rejected output becomes alleged spoken text.
    """
    attempts = 0

    def attempt(start, duration, retry, previous):
        nonlocal attempts
        attempts += 1
        try:
            result = decode(start, duration, retry)
        except LanguageUncertain as exc:
            return [], [str(exc)], False, None
        except Exception:
            return [], ["本地模型识别出错"], False, None
        if isinstance(result, dict) and result.get("digital_silence") is True:
            return [], [], True, result
        rows, reasons = inspect_result(result, duration, previous)
        return [{**row, "start": round(start + row["start"], 3), "end": round(start + row["end"], 3)} for row in rows], reasons, False, result

    rows, reasons, silence, _ = attempt(offset, length, False, previous_text)
    if not reasons:
        return {"segments": rows, "issues": [], "attempts": attempts, "silence": silence}
    intervals = [(offset, length)] if length <= 15 else [(offset, length / 2), (offset + length / 2, length / 2)]
    output, issues, only_silence = [], [], True
    previous = previous_text
    for start, duration in intervals:
        retried, errors, silent, raw = attempt(start, duration, True, previous)
        only_silence = only_silence and silent
        if errors:
            partial = partial_result(raw, duration, previous)
            if partial:
                valid, gaps = partial
                output.extend({**row, "start": round(start + row["start"], 3), "end": round(start + row["end"], 3)} for row in valid)
                issues.extend({**gap, "start": round(start + gap["start"], 3), "end": round(start + gap["end"], 3)} for gap in gaps)
                previous = "".join(row["text"] for row in valid)
            else:
                issues.append({"start": round(start, 3), "end": round(start + duration, 3), "reasons": errors})
        else:
            output.extend(retried)
            if retried:
                previous = "".join(row["text"] for row in retried)
    return {"segments": output, "issues": issues, "attempts": attempts, "silence": only_silence and not issues}


def issue_segment(issue):
    return {"start": issue["start"], "end": issue["end"],
            "text": "【转写缺口，非录音原文】此处本地识别异常：" + "；".join(issue["reasons"]) + "。请回听或另行补转；没有保留疑似循环输出。"}
