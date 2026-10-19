import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from core import pipeline
from index_local_course import prepare_manifest, register
from local_sources import LocalSourceError, audio_metadata, parse_draft, prepare, snapshot, source_state, sync_sources
from store import Store


class LocalIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "录音.wav"
        self.draft = self.root / "初校稿.md"
        self.write_audio()
        self.original = "# 术语初校稿\n\n未人工听核。\n\n**00:00**\n\n第一段。\n\n**00:05**\n\n第二段。\n"
        self.draft.write_text(self.original, encoding="utf-8")
        self.manifest = {"version": 1, "course_id": "course-sample", "lectures": [{
            "id": "local-lesson-1", "title": "第一讲", "date": "2026-09-08",
            "audio_path": str(self.audio), "transcript_path": str(self.draft)}]}
        self.plan = self.root / "plan.json"
        self.plan.write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")
        self.data_dir = self.root / "data"

    def tearDown(self):
        self.temp.cleanup()

    def write_audio(self, duration=10):
        with wave.open(str(self.audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\0\0" * (8000 * duration))

    def import_one(self):
        manifest, prepared = prepare_manifest(self.plan)
        report = register(manifest, prepared, self.data_dir)
        return Store(self.data_dir), report

    def test_markdown_timecodes_preserved_without_fabricating_ends(self):
        parsed = parse_draft(self.original)
        self.assertEqual([row["start"] for row in parsed["segments"]], [0, 5])
        self.assertTrue(all(row["end"] is None for row in parsed["segments"]))
        self.assertTrue(all(row["review_status"] == "unreviewed" for row in parsed["segments"]))
        self.assertIn("未人工听核", parsed["preamble"])
        with self.assertRaises(pipeline.PipelineError):
            pipeline.export_srt(parsed["segments"])

    def test_fifth_lecture_summaries_and_appendix_are_not_speech(self):
        text = "# 第五讲\n\n## 内容导航\n\n**00:00—00:15　导读**\n\n整理提要。\n\n## 录音转写\n\n**00:00:00**\n\n录音正文。\n\n**00:01:00**\n\n第二段。\n\n## 重点复听\n\n不确定词。\n\n## 术语对照\n\n非逐字原话。"
        parsed = parse_draft(text)
        self.assertEqual(len(parsed["segments"]), 2)
        self.assertNotIn("整理提要", str(parsed["segments"]))
        self.assertNotIn("不确定词", str(parsed["segments"]))
        self.assertIn("整理提要", parsed["preamble"])
        self.assertIn("重点复听", parsed["appendix"])

    def test_invalid_order_and_empty_segments_rejected(self):
        with self.assertRaises(pipeline.PipelineError):
            parse_draft("**01:00**\n\n后。\n\n**00:10**\n\n前。")
        with self.assertRaises(LocalSourceError):
            parse_draft("**00:00**\n\n**00:01**\n\n正文。")
        with self.assertRaises(LocalSourceError):
            parse_draft("普通文字没有时间码。")

    def test_audio_header_is_read_without_external_tools(self):
        self.assertEqual(audio_metadata(self.audio)["duration"], 10)
        created = int((datetime(2026, 9, 8, 10, tzinfo=timezone.utc) - datetime(1904, 1, 1, tzinfo=timezone.utc)).total_seconds())
        def box(name, body):
            return struct.pack(">I4s", len(body) + 8, name) + body
        for version in (0, 1):
            raw = (struct.pack(">IIII", created, created, 1000, 12345) if version == 0 else
                   struct.pack(">QQIQ", created, created, 1000, 12345))
            movie = bytes([version, 0, 0, 0]) + raw + b"\0" * 20
            path = self.root / f"movie-{version}.m4a"
            path.write_bytes(box(b"mdat", b"x" * 100) + box(b"moov", box(b"mvhd", movie)))
            self.assertEqual(audio_metadata(path), {"duration": 12.345, "date": "2026-09-08"})
            for extension in (".qta", ".QTA", ".qat", ".qt"):
                quicktime = self.root / ("synthetic" + extension)
                quicktime.write_bytes(path.read_bytes())
                self.assertEqual(audio_metadata(quicktime), {"duration": 12.345, "date": "2026-09-08"})

    def test_timestamp_beyond_recording_is_not_paired(self):
        self.draft.write_text("**01:00**\n\n超过时长。", encoding="utf-8")
        with self.assertRaises(LocalSourceError):
            prepare(self.manifest["lectures"][0])

    def test_registration_copies_zero_audio_bytes_and_keeps_sources(self):
        before = self.audio.read_bytes(), self.draft.read_bytes()
        store, report = self.import_one()
        item = store.get("local-lesson-1")
        self.assertEqual(report["audio_bytes_copied"], 0)
        self.assertEqual(list(store.audio_dir.iterdir()), [])
        self.assertEqual(store.audio_path(item), self.audio.resolve())
        self.assertEqual((self.audio.read_bytes(), self.draft.read_bytes()), before)
        self.assertEqual(item["original_transcript"], self.original)
        self.assertTrue(Path(report["backup"]).is_file())

    def test_paths_are_private_but_names_and_status_are_public(self):
        store, _ = self.import_one()
        public = store.public_lecture(store.get("local-lesson-1"))
        self.assertNotIn("local_sources", public)
        self.assertNotIn(str(self.root), json.dumps(public, ensure_ascii=False))
        self.assertEqual({source["state"] for source in public["source_files"]}, {"available"})

    def test_reindex_preserves_edited_notes_and_source_cache(self):
        store, _ = self.import_one()
        def edit(item):
            item["segments"][0]["text"] = "人工校对版本。"
            item["notes"] = [{"id": "n1", "category": "comment", "title": "我自己的笔记", "content": "保留。", "source_ids": ["s0001"], "review_status": "verified", "user_edited": True}]
        store.mutate("local-lesson-1", edit)
        before = store.get("local-lesson-1")
        manifest, prepared = prepare_manifest(self.plan)
        report = register(manifest, prepared, self.data_dir)
        self.assertEqual(report["lectures"][0]["status"], "already_indexed_preserved")
        self.assertEqual(store.get("local-lesson-1"), before)

    def test_unchanged_sync_preserves_manual_corrections_and_verification(self):
        store, _ = self.import_one()
        store.mutate("local-lesson-1", lambda item: item["segments"][0].update(text="人工版本。", review_status="verified"))
        item = sync_sources(store, "local-lesson-1")
        self.assertEqual(item["segments"][0]["text"], "人工版本。")
        self.assertEqual(item["segments"][0]["review_status"], "verified")

    def test_changed_draft_requires_confirmation_and_archives_old_references(self):
        store, _ = self.import_one()
        note = {"id": "n1", "category": "comment", "title": "旧笔记", "content": "解释。", "source_ids": ["s0001"], "review_status": "verified", "user_edited": True}
        store.mutate("local-lesson-1", lambda item: item["notes"].append(note))
        self.draft.write_text(self.original.replace("第一段", "更新后的第一段"), encoding="utf-8")
        old = copy.deepcopy(store.get("local-lesson-1"))
        self.assertEqual(source_state(old["local_sources"]["transcript"]), "changed")
        with self.assertRaises(LocalSourceError):
            sync_sources(store, "local-lesson-1")
        self.assertEqual(store.get("local-lesson-1"), old)
        item = sync_sources(store, "local-lesson-1", True)
        self.assertEqual(item["notes"], [])
        self.assertEqual(item["deleted_notes"][0]["source_snapshot"]["s0001"]["text"], "第一段。")
        self.assertIn("更新后的第一段", item["segments"][0]["text"])

    def test_changed_audio_blocks_playback_until_sync_and_invalidates_verification(self):
        store, _ = self.import_one()
        store.mutate("local-lesson-1", lambda item: item["segments"][0].update(review_status="verified"))
        self.write_audio(11)
        with self.assertRaises(LocalSourceError):
            store.audio_path(store.get("local-lesson-1"))
        item = sync_sources(store, "local-lesson-1")
        self.assertEqual(item["duration"], 11)
        self.assertEqual(item["segments"][0]["review_status"], "needs_review")
        self.assertEqual(store.audio_path(item), self.audio.resolve())

    def test_missing_source_keeps_cached_text_and_existing_notes(self):
        store, _ = self.import_one()
        self.draft.rename(self.root / "已移走.md")
        before = store.get("local-lesson-1")
        public = store.public_lecture(before)
        self.assertEqual(next(source["state"] for source in public["source_files"] if source["kind"] == "transcript"), "missing")
        self.assertEqual(len(public["segments"]), 2)
        with self.assertRaises(LocalSourceError):
            sync_sources(store, "local-lesson-1")
        self.assertEqual(store.get("local-lesson-1"), before)

    def test_path_replaced_by_symlink_is_not_followed(self):
        source = snapshot(self.draft, "transcript")
        moved = self.root / "moved.md"
        self.draft.rename(moved)
        self.draft.symlink_to(moved)
        self.assertEqual(source_state(source), "missing")

    def test_extra_reference_kept_out_of_speech(self):
        reference = self.root / "复听清单.md"
        reference.write_text("# 复听\n\n**00:02**\n\n这不是老师原话。", encoding="utf-8")
        entry = {**self.manifest["lectures"][0], "reference_paths": [str(reference)]}
        fresh = prepare(entry)
        self.assertEqual(len(fresh["segments"]), 2)
        self.assertIn("不是老师原话", fresh["source_context"]["references"][0]["text"])


if __name__ == "__main__":
    unittest.main()
