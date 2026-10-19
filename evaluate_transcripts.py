"""Offline CER/whitespace-WER scoring of explicitly human-verified references.

This measures text agreement, not semantic fidelity, speaker attribution or
summary quality. It does not call speech models, APIs or network services.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import unicodedata


METHODS = {"independent_listening", "edited_model_output"}


def normalized(text):
    """NFC + casefold; drop Unicode punctuation/symbols, retain word boundaries."""
    text = unicodedata.normalize("NFC", text).casefold()
    return "".join(c for c in text if unicodedata.category(c)[0] not in "PS")


def edit_distance(reference, hypothesis):
    """Unit-cost Levenshtein distance, with linear working memory."""
    if len(reference) < len(hypothesis):
        reference, hypothesis = hypothesis, reference
    previous = list(range(len(hypothesis) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, actual in enumerate(hypothesis, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (expected != actual)))
        previous = current
    return previous[-1]


def score(dataset):
    if not isinstance(dataset, dict):
        raise ValueError("The dataset root must be an object.")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Expected a non-empty cases list.")
    identifiers = set()
    verified = []
    excluded = []
    for case in cases:
        if not isinstance(case, dict):
            raise ValueError("Each case must be an object.")
        identifier = case.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in identifiers:
            raise ValueError("Case IDs must be non-empty unique strings.")
        identifiers.add(identifier)
        if case.get("reference_status") != "human_verified":
            excluded.append({"id": identifier, "reason": "reference_not_human_verified"})
            continue
        reference = case.get("reference")
        if (not isinstance(reference, str) or not reference.strip()
                or case.get("reference_method") not in METHODS):
            raise ValueError("Verified references require text and a declared annotation method.")
        clean = normalized(reference)
        if not "".join(clean.split()):
            raise ValueError("A reference needs non-punctuation speech text.")
        hypotheses = case.get("hypotheses")
        if (not isinstance(hypotheses, dict) or not hypotheses
                or any(not isinstance(k, str) or not k or not isinstance(v, str)
                       for k, v in hypotheses.items())):
            raise ValueError("Verified cases need named string hypotheses (empty text is allowed).")
        verified.append((case, clean))

    report = {"schema_version": 1, "status": "scored" if verified else "pending_reference",
              "total_cases": len(cases), "scored_cases": len(verified),
              "excluded": excluded, "normalization": "NFC, casefold, no Unicode punctuation/symbols",
              "cer_unit": "Unicode code point, whitespace removed",
              "wer_unit": "whitespace-delimited token; not linguistic word segmentation",
              "systems": {}, "cases": [],
              "limits": "Text agreement only; not summary quality or representative accuracy."}
    for case, clean in verified:
        chars, words = "".join(clean.split()), clean.split()
        row = {"id": case["id"], "language": case.get("language", "unspecified"),
               "reference_method": case["reference_method"], "systems": {}}
        for name, hypothesis in case["hypotheses"].items():
            actual = normalized(hypothesis)
            ce = edit_distance(chars, "".join(actual.split()))
            we = edit_distance(words, actual.split())
            counts = {"character_errors": ce, "reference_characters": len(chars),
                      "word_errors": we, "reference_words": len(words)}
            row["systems"][name] = {**counts, "cer": ce / len(chars), "wer": we / len(words)}
            total = report["systems"].setdefault(name, {"cases": 0, **dict.fromkeys(counts, 0)})
            total["cases"] += 1
            for key, value in counts.items():
                total[key] += value
        report["cases"].append(row)
    for total in report["systems"].values():
        total["cer"] = total["character_errors"] / total["reference_characters"]
        total["wer"] = total["word_errors"] / total["reference_words"]
    report["paired_system_coverage"] = bool(verified) and all(
        set(case["hypotheses"]) == set(verified[0][0]["hypotheses"]) for case, _ in verified)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New local report file; never overwritten")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Use a new report path; nothing was overwritten.")
    try:
        report = score(json.loads(args.dataset.read_text(encoding="utf-8")))
    except (ValueError, OSError) as error:
        parser.error(str(error))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(f"{report['status']}: {report['scored_cases']} / {report['total_cases']} cases scored.")


if __name__ == "__main__":
    main()
