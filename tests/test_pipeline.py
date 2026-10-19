import json
import unittest

from core.pipeline import (PipelineError, export_markdown, export_srt,
                           extract_local_notes, parse_transcript, validate_notes)


class TranscriptTests(unittest.TestCase):
    def test_plain_text_never_invents_times(self):
        parsed = parse_transcript("老师介绍了一种观点。\n但老师并没有赞同它。")
        self.assertIsNone(parsed["duration"])
        self.assertEqual(len(parsed["segments"]), 2)
        self.assertTrue(all(row["start"] is None and row["end"] is None for row in parsed["segments"]))
        self.assertTrue(parsed["warnings"])

    def test_srt(self):
        source = "1\r\n00:00:01,200 --> 00:00:03,050\r\n第一行\r\n第二行\r\n\r\n2\r\n00:00:04,000 --> 00:00:06,500\r\n反对意见。\r\n"
        parsed = parse_transcript(source)
        self.assertEqual(parsed["format"], "srt")
        self.assertEqual(parsed["duration"], 6.5)
        self.assertEqual(parsed["segments"][0]["text"], "第一行\n第二行")
        self.assertEqual(parsed["segments"][0]["start"], 1.2)
        self.assertEqual(parse_transcript(export_srt(parsed["segments"]))["segments"], parsed["segments"])

    def test_vtt(self):
        parsed = parse_transcript("WEBVTT\n\nNOTE not a transcript\nignore this\n\nintro\n00:01.250 --> 00:05.000 align:start\n[原文] 一个例子。\n")
        self.assertEqual(parsed["format"], "vtt")
        self.assertEqual(parsed["segments"][0]["start"], 1.25)
        self.assertEqual(parsed["segments"][0]["text"], "[原文] 一个例子。")

    def test_vtt_header_metadata(self):
        parsed = parse_transcript("WEBVTT\nKind: captions\nLanguage: zh\nX-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:0\n\n00:00.000 --> 00:01.000\n文字")
        self.assertEqual(parsed["segments"][0]["text"], "文字")

    def test_timestamped_txt_start_only(self):
        parsed = parse_transcript("[00:00] 概念\n[01:30] 反例")
        self.assertEqual(parsed["format"], "txt")
        self.assertEqual(parsed["duration"], 90)
        self.assertIsNone(parsed["segments"][0]["end"])
        with self.assertRaises(PipelineError):
            export_srt(parsed["segments"])

    def test_timestamped_txt_ranges(self):
        parsed = parse_transcript("[00:00] - [00:20] 第一段\n[00:21] - [00:35] 第二段")
        self.assertEqual(parsed["segments"][0]["end"], 20)
        self.assertIn("00:00:20,000", export_srt(parsed["segments"]))

    def test_plain_brackets_are_not_assumed_json(self):
        parsed = parse_transcript("[老师] 这是一个例子。")
        self.assertEqual(parsed["segments"][0]["text"], "[老师] 这是一个例子。")

    def test_json_array_and_object(self):
        rows = [{"id": "source_a", "start": 1, "end": 3, "text": "内容", "review_status": "verified"}]
        first = parse_transcript(json.dumps(rows))
        second = parse_transcript(json.dumps({"segments": rows}))
        self.assertEqual(first["segments"], second["segments"])
        self.assertEqual(first["segments"][0]["id"], "source_a")
        self.assertEqual(first["segments"][0]["original_text"], "内容")
        self.assertEqual(first["segments"][0]["review_status"], "unreviewed")

    def test_duplicates_and_bad_times_rejected(self):
        cases = [
            [{"id": "same", "text": "a"}, {"id": "same", "text": "b"}],
            [{"start": -1, "end": 2, "text": "a"}],
            [{"start": 2, "end": 1, "text": "a"}],
            [{"start": True, "end": 2, "text": "a"}],
            [{"start": float("nan"), "text": "a"}],
            [{"start": 2, "text": "a"}, {"start": 1, "text": "b"}],
            [{"end": 3, "text": "a"}],
            [{"start": "3", "end": 4, "text": "a"}],
            [{"text": ""}],
            [{"id": "<script>", "text": "bad"}],
        ]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(PipelineError):
                parse_transcript(json.dumps(rows))

    def test_overlapping_subtitles_are_allowed(self):
        parsed = parse_transcript(json.dumps([{"start": 0, "end": 3, "text": "a"}, {"start": 2, "end": 4, "text": "b"}]))
        self.assertEqual(parsed["duration"], 4)

    def test_bad_formats(self):
        for text, format in [("", "auto"), ("abc", "bad"), ("{broken", "auto"),
                             ("1\n00:00:70,000 --> 00:00:80,000\na", "srt"),
                             ("WEBVTT\n\ngarbage", "vtt")]:
            with self.subTest(text=text), self.assertRaises(PipelineError):
                parse_transcript(text, format)

    def test_long_plain_line_preserved_in_chunks(self):
        text = "汉字" * 13000
        parsed = parse_transcript(text)
        self.assertEqual("".join(row["text"] for row in parsed["segments"]), text)

    def test_hard_limits_are_explicit(self):
        with self.assertRaises(PipelineError):
            parse_transcript("文" * 2_000_001)
        with self.assertRaises(PipelineError):
            parse_transcript(json.dumps([{"text": "文" * 16001}]))
        with self.assertRaises(PipelineError):
            parse_transcript(json.dumps([{"text": "文"}] * 12001))


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.segments = parse_transcript("有人介绍观点甲。\n老师批评了观点甲。")['segments']
        self.note = {"category": "argument", "title": "论证", "content": "待核对的摘要", "source_ids": ["s0001"]}

    def test_local_is_exact_excerpts_not_summary(self):
        result = extract_local_notes(self.segments, [{"term": "甲", "meaning": "不要插入解释"}])
        self.assertEqual(result["mode"], "local")
        self.assertEqual([row["content"] for row in result["notes"]], [row["text"] for row in self.segments])
        self.assertTrue(all(row["category"] == "review" and row["review_status"] == "unreviewed" for row in result["notes"]))
        self.assertIn("没有调用模型", result["warnings"][0])

    def test_valid_note_structurally_normalized(self):
        row = validate_notes([dict(self.note, source_ids=["s0001", "s0001"])], self.segments)[0]
        self.assertEqual(row["source_ids"], ["s0001"])
        self.assertEqual(row["review_status"], "unreviewed")
        self.assertFalse(row["user_edited"])

    def test_invalid_citations_and_shapes(self):
        for update in ({"source_ids": []}, {"source_ids": ["fake"]}, {"source_ids": "s0001"},
                       {"source_ids": [{}]}, {"category": "madeup"}, {"category": []},
                       {"title": ""}, {"content": ""}, {"review_status": []}, {"id": "a b"}):
            with self.subTest(update=update), self.assertRaises(PipelineError):
                validate_notes([dict(self.note, **update)], self.segments)

    def test_markdown_contains_sources_and_corrections(self):
        self.segments[0]["text"] = "校订后的文字"
        notes = validate_notes([self.note], self.segments)
        text = export_markdown({"title": "现象学", "date": "2026-10-15", "segments": self.segments,
                                "notes": notes, "generation": {"mode": "local"}, "warnings": []}, "知觉现象学")
        self.assertIn("本地原文摘录", text)
        self.assertIn('[s0001](#s0001)', text)
        self.assertIn('<a id="s0001"></a>', text)
        self.assertIn("原始转写（校订前）", text)
        self.assertIn("有人介绍观点甲。", text)

    def test_unknown_times_srt_rejected(self):
        with self.assertRaises(PipelineError):
            export_srt(self.segments)


if __name__ == "__main__":
    unittest.main()
