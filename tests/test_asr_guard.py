"""Regression checks for repetition, finite retry, time bounds and checkpoint privacy."""
import json
from pathlib import Path
import tempfile
import unittest

from asr_checkpoints import Checkpoints
from core.asr_guard import inspect_result, guarded_window, issue_segment, VERSION, partial_result, word_timing_reasons


def good(text="这段只用于合成测试，讨论一个具体问题。", length=30):
    return {"segments": [{"start": 0, "end": length, "text": text, "avg_logprob": -.2, "compression_ratio": 1.2}]}


class GuardTests(unittest.TestCase):
    def test_collapsed_lexical_word_times_are_not_trusted_by_segment_confidence(self):
        row = {"start":21.1,"end":29.98,"text":"Synthetic hallucinated subscription sentence", "avg_logprob":-.1,
               "words":[{"word":str(i),"start":29.9,"end":29.9} for i in range(16)]}
        self.assertIn("塌缩",inspect_result({"segments":[row]},30)[1][0])
        self.assertFalse(word_timing_reasons({"words":[{"word":".","start":1,"end":1}]*8}))
        self.assertFalse(word_timing_reasons({"words":[{"word":"word","start":0,"end":1},{"word":"small","start":1,"end":1}]}))

    def test_terminal_hallucination_does_not_destroy_good_prefix(self):
        raw={"segments":[{"start":0,"end":10,"text":"Normally spoken synthetic phrase."},
                         {"start":10,"end":20,"text":"A second normal phrase."},
                         {"start":21,"end":51,"text":"Synthetic tail hallucination."}]}
        rows,gaps=partial_result(raw,30)
        self.assertEqual(len(rows),2)
        self.assertEqual(gaps[0]["start"],21)
        self.assertEqual(gaps[0]["end"],30)
        def decode(start, duration, retry):
            if not retry:
                return raw
            return {"segments":[{"start":0,"end":5,"text":"Normal short-window prefix."},
                                {"start":6,"end":36,"text":"Bad short-window tail."}]}
        result=guarded_window(decode,120,30)
        self.assertTrue(result['issues'])
        self.assertTrue(result['segments'])
        self.assertEqual(result['attempts'],3)

    def test_zero_duration_or_unknown_times_are_not_invented(self):
        raw={"segments":[{"start":0,"end":10,"text":"Good prefix."},{"start":30,"end":30,"text":"Unknown tail."}]}
        rows,issues=partial_result(raw,30)
        self.assertEqual(rows[0]['end'],10)
        self.assertEqual((issues[0]['start'],issues[0]['end']),(29.5,30))
        raw['segments'][1]['start']=float('nan')
        self.assertIsNone(partial_result(raw,30))

    def test_partial_overlap_expands_gap_without_losing_unmarked_text(self):
        raw={'segments':[{'start':0,'end':1,'text':'Safe.'},{'start':2,'end':5,'text':'Overlapping neighbour.'},
                         {'start':4,'end':7,'text':'Connects to bad row.'},{'start':6,'end':40,'text':'Bad time.'}]}
        rows,issues=partial_result(raw,30)
        self.assertEqual([r['text'] for r in rows],['Safe.'])
        self.assertEqual((issues[0]['start'],issues[0]['end']),(2,30))

    def test_short_rhetorical_repeat_not_collapsed(self):
        text = "不是这样的，不是这样的。请注意这个论证的前提。"
        rows, reasons = inspect_result(good(text), 30)
        self.assertEqual(reasons, [])
        self.assertEqual(rows[0]["text"], text)

    def test_chinese_and_english_repetition_and_timestamps(self):
        for text in ("谢谢大家，" * 12, "Thank you for watching. " * 12, "啊" * 20):
            self.assertTrue(inspect_result(good(text), 30)[1])
        bad = good()
        bad["segments"][0]["end"] = 100
        self.assertTrue(inspect_result(bad, 30)[1])
        bad["segments"][0]["end"] = float("nan")
        self.assertTrue(inspect_result(bad, 30)[1])

    def test_adjacent_same_sentences_and_previous_window(self):
        raw = {"segments": [{"start": i * 5, "end": i * 5 + 5, "text": "这里总是在重复同一句内容"} for i in range(3)]}
        self.assertTrue(inspect_result(raw, 30)[1])
        text = "完全相同的一个合成片段，用来检查跨段复读问题而不是宣称所有重复都一定是错误。" * 2
        self.assertTrue(inspect_result(good(text), 30, text)[1])

    def test_finite_retry_splits_then_succeeds(self):
        calls = []
        def decode(offset, length, retry):
            calls.append((offset, length, retry))
            return good("谢谢大家" * 20, length) if not retry else good("这里是正常的合成识别片段。", length)
        result = guarded_window(decode, 60, 60)
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1:], [(60, 30, True), (90, 30, True)])
        self.assertFalse(result["issues"])
        self.assertEqual(result["segments"][1]["start"], 90)

    def test_bad_retry_becomes_explicit_gap_not_repetitive_speech(self):
        calls = []
        def decode(offset, length, retry):
            calls.append(1)
            return good("重复输出" * 30, length)
        result = guarded_window(decode, 0, 60)
        self.assertEqual(len(calls), 3)
        self.assertEqual(result["segments"], [])
        self.assertEqual(len(result["issues"]), 2)
        self.assertIn("非录音原文", issue_segment(result["issues"][0])["text"])

    def test_one_bad_half_does_not_discard_other_half(self):
        def decode(offset, length, retry):
            return good("重复" * 60, length) if not retry or offset == 0 else good("后半段正常内容。", length)
        result = guarded_window(decode, 0, 60)
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["segments"][0]["start"], 30)

    def test_silence_and_non_silent_empty_are_different(self):
        self.assertTrue(guarded_window(lambda *args: {"digital_silence": True}, 0, 60)["silence"])
        result = guarded_window(lambda *args: {"segments": []}, 0, 60)
        self.assertTrue(result["issues"])

    def test_decoder_exception_is_bounded(self):
        def decode(*args):
            raise RuntimeError("internal path or GPU diagnostic")
        result = guarded_window(decode, 0, 10)
        self.assertEqual(result["attempts"], 2)
        self.assertNotIn("internal path", json.dumps(result))


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="lecture-checkpoint-test-")
        self.root = Path(self.tmp.name)
        self.model = self.root / "model"; self.model.mkdir()
        (self.model / "config.json").write_text("{}")
        (self.model / "weights.npz").write_bytes(b"synthetic-not-real-weights")
        self.config = {"model_path": str(self.model), "language": "zh"}
        self.cache = Checkpoints(self.root)
    def tearDown(self):
        self.tmp.cleanup()

    def test_atomic_roundtrip_and_model_language_source_invalidation(self):
        key = self.cache.key("lecture", "source-one", self.config)
        data = {"version": VERSION, "duration": 120, "chunks": {"0": {"segments": [], "issues": [], "start": 0, "end": 60}}}
        self.cache.save(key, data)
        self.assertEqual(self.cache.load(key), data)
        self.assertEqual(self.cache.path(key).stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(key, self.cache.key("lecture", "source-two", self.config))
        self.assertNotEqual(key, self.cache.key("lecture", "source-one", {**self.config, "language": "fr"}))
        (self.model / "weights.npz").write_bytes(b"replaced-model")
        self.assertNotEqual(key, self.cache.key("lecture", "source-one", self.config))
        self.assertNotIn(str(self.model), self.cache.path(key).read_text())

    def test_bad_or_symlink_checkpoint_rejected(self):
        with self.assertRaises(ValueError):
            self.cache.path("../escape")
        key = "f" * 64
        self.cache.root.mkdir()
        self.cache.path(key).write_text("not-json")
        with self.assertRaises(ValueError):
            self.cache.load(key)
        external = self.root / "external.json"; external.write_text("{}")
        self.cache.path(key).unlink()
        (self.cache.root / (key + ".json")).symlink_to(external)
        with self.assertRaises(ValueError):
            self.cache.load(key)


if __name__ == "__main__":
    unittest.main()
