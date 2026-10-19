"""Synthetic streaming, synthesis, persistence and DOCX regressions."""
from copy import deepcopy
from io import BytesIO
import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zipfile
from xml.etree import ElementTree as ET
from urllib import request, error

from core import pipeline, overview
from core.chat_stream import read_stream, chat
from core.word_export import export_docx
from note_jobs import NoteJobs
from store import Store
import test_server as server_helpers


def fixture():
    segments = pipeline.parse_transcript(json.dumps([
        {"start": 0, "end": 15, "text": "展示：本周有十二个反馈。建议周五上线方案 A。", "speaker": "发言人 1"},
        {"start": 15, "end": 30, "text": "方案 A 尚有风险，周五上线太急，需要先测试。", "speaker": "发言人 2"},
        {"start": 30, "end": 45, "text": "决定采用方案 B，先小范围测试。李明负责整理测试报告，下周二提交。", "speaker": "发言人 1"}
    ]))["segments"]
    notes = pipeline.validate_notes([{"category": "argument", "title": "发布方案讨论", "content": "最初提出方案 A 周五上线。经讨论风险，最终采用方案 B 并先做小范围测试。测试报告由李明负责，下周二提交。", "source_ids": [row["id"] for row in segments]}], segments)
    row = lambda title, content, ids: {"title": title, "content": content, "source_ids": ids}
    summary = {"summary": row("核心总结", "会议展示十二个反馈，讨论了上线风险，最终采用方案 B 并先小范围测试。", ["s0001", "s0002", "s0003"]),
        "key_points": [row("信息与风险", "本周十二个反馈，方案 A 的上线风险尚需测试。", ["s0001", "s0002"])],
        "decisions": [{**row("采用方案 B", "采用方案 B，先做小范围测试，而非周五直接上线方案 A。", ["s0003"]), "evidence_quote": "决定采用方案 B，先小范围测试。"}],
        "actions": [row("整理测试报告", "任务：整理测试报告\n负责人：李明\n截止时间：下周二（原文相对日期，未换算）", ["s0003"])],
        "open_questions": [row("正式上线时间", "原文没有给出正式上线日期，需要后续确认。", ["s0003"])]}
    return segments, notes, summary


class StreamTests(unittest.TestCase):
    def stream(self, frames, done=True):
        content = b"".join(b"data: " + json.dumps(frame).encode() + b"\n\n" for frame in frames)
        return BytesIO(content + (b"data: [DONE]\n\n" if done else b""))

    def test_usage_only_last_frame_and_empty_choices(self):
        events = []
        response = read_stream(self.stream([{"choices": [{"delta": {"reasoning_content": "abc"}, "finish_reason": None}], "usage": None}, {"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]}, {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 4, "total_tokens": 24}}]), events.append, pipeline.PipelineError)
        self.assertIsNone(events[0]["usage"])
        self.assertEqual(events[1]["output_chars"], 2)
        self.assertEqual(events[1]["reasoning_chars"], 3)
        self.assertEqual(response["usage"]["total_tokens"], 24)
        self.assertEqual(response["choices"][0]["message"]["content"], "{}")

    def test_missing_usage_stays_unknown(self):
        response = read_stream(self.stream([{"choices": [{"delta": {"content": "{}"}, "finish_reason": "stop"}]}]), lambda event: None, pipeline.PipelineError)
        self.assertIsNone(response["usage"])

    def test_disconnected_stream_does_not_complete(self):
        with self.assertRaises(pipeline.PipelineError):
            read_stream(self.stream([{"choices": [{"delta": {"content": "{"}}]}], False), lambda event: None, pipeline.PipelineError)

    def test_bad_frames_and_provider_errors_do_not_leak_body(self):
        for body in (b'data: bad-SECRET\n\n', b'data: {"error":{"message":"SECRET"}}\n\n'):
            with self.assertRaises(pipeline.PipelineError) as error:
                read_stream(BytesIO(body), lambda event: None, pipeline.PipelineError)
            self.assertNotIn("SECRET", str(error.exception))

    def test_local_gateway_bypasses_proxy_and_accepts_nonstream_reply(self):
        body = BytesIO(b'{"choices":[{"finish_reason":"stop","message":{"content":"{}"}}],"usage":{"total_tokens":10}}')
        body.headers = {"Content-Type": "application/json"}
        events = []
        with patch("core.chat_stream.request.build_opener") as build, patch("core.pipeline._validate_dns"):
            build.return_value.open.return_value = body
            response = chat("http://127.0.0.1:9999/chat/completions", {"model": "synthetic"}, {}, events.append)
        self.assertTrue(any(isinstance(handler, request.ProxyHandler) and not handler.proxies for handler in build.call_args.args))
        self.assertEqual(response["usage"]["total_tokens"], 10)
        self.assertEqual(events[0]["usage"]["total_tokens"], 10)

    def test_unsupported_stream_is_not_automatically_retried(self):
        with patch("core.chat_stream.request.build_opener") as build, patch("core.pipeline._validate_dns"):
            build.return_value.open.side_effect = error.HTTPError("https://example.com/SECRET", 400, "SECRET", {}, None)
            with self.assertRaises(pipeline.PipelineError) as failure:
                chat("https://example.com/chat/completions", {"model": "synthetic"}, {}, lambda event: None)
            self.assertEqual(build.return_value.open.call_count, 1)
            self.assertNotIn("SECRET", str(failure.exception))


class OverviewTests(unittest.TestCase):
    def setUp(self):
        self.segments, self.notes, self.summary = fixture()

    def test_valid_summary_has_unreviewed_decisions_and_literal_quote(self):
        result = overview.validate(self.summary, self.segments)
        self.assertEqual(result["review_status"], "unreviewed")
        self.assertEqual(result["decisions"][0]["category"], "decision")

    def test_fake_sources_or_invented_decision_quote_rejected(self):
        for key, value in (("source_ids", ["made-up"]), ("evidence_quote", "大家一致同意周五上线方案 A")):
            candidate = deepcopy(self.summary)
            candidate["decisions"][0][key] = value
            with self.assertRaises(pipeline.PipelineError):
                overview.validate(candidate, self.segments)

    def test_no_decisions_is_not_filled_in(self):
        self.summary["decisions"] = []
        self.assertEqual(overview.validate(self.summary, self.segments)["decisions"], [])

    def test_content_hash_ignores_review_toggles_but_not_text(self):
        item = {"segments": self.segments, "notes": self.notes}
        before = overview.content_hash(item)
        item["notes"][0]["review_status"] = "verified"
        self.assertEqual(overview.content_hash(item), before)
        item["segments"][0]["text"] += "更新"
        self.assertNotEqual(overview.content_hash(item), before)

    def test_summary_requires_separate_external_consent(self):
        with patch("core.pipeline._request_bytes") as network:
            with self.assertRaises(pipeline.PipelineError):
                overview.synthesize(self.notes, self.segments, {"base_url": "https://example.com", "model": "test"}, {"scene": "meeting"})
            network.assert_not_called()

    def test_hierarchical_summary_preserves_sources_without_truncation(self):
        notes = [{"category": "comment", "title": "分组材料", "content": "细节" * 175, "source_ids": [row["id"]]} for row in self.segments]
        seen = []
        def respond(url, data, headers):
            material = json.loads(json.loads(data)["messages"][1]["content"])
            ids = [row["id"] for row in material["sources"]]
            seen.append(ids)
            result = {"summary": {"title": "综合", "content": "压缩后的综合信息", "source_ids": ids}, "key_points": [], "decisions": [], "actions": [], "open_questions": []}
            return json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result)}}]}).encode()
        with patch("core.overview.GROUP_LIMIT", 850), patch("core.pipeline._request_bytes", side_effect=respond):
            result = overview.synthesize(notes, self.segments, {"base_url": "https://example.com", "model": "test"}, {"scene": "meeting"}, allow_external=True)
        self.assertGreater(len(seen), 1)
        self.assertEqual(set(result["summary"]["source_ids"]), {row["id"] for row in self.segments})


class NoteJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.item = self.store.create("course-sample", "虚构会议", "2026-10-18")
        self.segments, self.notes, self.summary = fixture()
        self.item = self.store.mutate(self.item["id"], lambda row: row.update(segments=self.segments, notes=self.notes, workflow={"scene": "meeting"}))
        self.settings = {"llm": {"base_url": "https://example.com", "model": "synthetic", "api_key": "SECRET"}, "glossary": []}
        self.jobs = NoteJobs(self.store)

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def fake_chat(self, url, payload, headers, report):
        report({"output_chars": 100, "usage": None})
        report({"output_chars": 200, "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "prompt_cache_hit_tokens": 40}})
        # Reporting a cumulative usage twice must not double count it.
        report({"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120, "prompt_cache_hit_tokens": 40}})
        value = self.summary if '"summary"' in payload["messages"][0]["content"] else {"notes": self.notes}
        return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value, ensure_ascii=False)}}]}

    def wait(self):
        deadline = time.monotonic() + 4
        while self.jobs.get(self.item["id"])["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(.01)
        return self.jobs.get(self.item["id"])

    def test_full_job_progress_usage_history_and_persistence(self):
        with patch("core.chat_stream.chat", side_effect=self.fake_chat):
            self.jobs.start(self.item, self.settings)
            job = self.wait()
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(job["usage"]["total_tokens"], 240)
        self.assertEqual(job["usage"]["prompt_cache_hit_tokens"], 80)
        self.assertEqual(job["requests_finished"], 2)
        self.assertNotIn("SECRET", json.dumps(job))
        saved = self.store.get(self.item["id"])
        self.assertEqual(saved["note_history"][0]["notes"], self.notes)
        self.assertFalse(self.store.public_lecture(saved)["overview"]["stale"])
        self.assertEqual(NoteJobs(self.store).get(self.item["id"])["status"], "completed")

    def test_overview_only_keeps_existing_notes(self):
        with patch("core.chat_stream.chat", side_effect=self.fake_chat):
            self.jobs.start(self.item, self.settings, "overview")
            job = self.wait()
        self.assertEqual(job["requests_finished"], 1)
        self.assertEqual(self.store.get(self.item["id"])["notes"], self.notes)

    def test_failure_preserves_current_notes_and_no_automatic_retry(self):
        with patch("core.chat_stream.chat", side_effect=pipeline.PipelineError("模拟超时")) as model:
            self.jobs.start(self.item, self.settings)
            job = self.wait()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(model.call_count, 1)
        self.assertEqual(self.store.get(self.item["id"])["notes"], self.notes)

    def test_terminal_failure_waits_for_diagnostic_and_persisted_snapshot(self):
        entered, release = threading.Event(), threading.Event()
        save_diagnostic = self.jobs._save_diagnostic
        def slow_diagnostic(*args):
            entered.set()
            release.wait(3)
            save_diagnostic(*args)
        with patch("core.chat_stream.chat", side_effect=pipeline.PipelineError("Synthetic failure")), \
                patch.object(self.jobs, "_save_diagnostic", side_effect=slow_diagnostic):
            self.jobs.start(self.item, self.settings)
            try:
                self.assertTrue(entered.wait(2))
                self.assertEqual(self.jobs.get(self.item["id"])["status"], "running")
                with self.assertRaises(pipeline.PipelineError):
                    self.jobs.start(self.item, self.settings)
            finally:
                release.set()
            job = self.wait()
        self.assertEqual(job["status"], "failed")
        self.assertTrue(job["diagnostics_available"])
        persisted = self.store.get(self.item["id"])["generation_job"]
        self.assertEqual(persisted["status"], "failed")
        self.assertTrue(persisted["diagnostics_available"])
        self.assertEqual(self.jobs.diagnostics(self.item["id"])["job_id"], job["id"])

    def test_concurrent_user_edit_is_not_overwritten(self):
        def edited(*args):
            response = self.fake_chat(*args)
            self.store.mutate(self.item["id"], lambda row: row["notes"][0].update(content="人工修改保留"))
            return response
        with patch("core.chat_stream.chat", side_effect=edited):
            self.jobs.start(self.item, self.settings)
            job = self.wait()
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.store.get(self.item["id"])["notes"][0]["content"], "人工修改保留")

    def test_duplicate_submission_rejected_and_missing_usage_not_zero(self):
        gate, entered = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            gate.wait(3)
            payload = args[1]
            value = self.summary if '"summary"' in payload["messages"][0]["content"] else {"notes": self.notes}
            return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value)}}]}
        with patch("core.chat_stream.chat", side_effect=slow):
            self.jobs.start(self.item, self.settings)
            entered.wait(2)
            with self.assertRaises(pipeline.PipelineError):
                self.jobs.start(self.item, self.settings)
            gate.set()
            job = self.wait()
        self.assertEqual(job["status"], "completed", job)
        self.assertIsNone(job["usage"])
        self.assertEqual(job["usage_reports"], 0)

    def test_restart_marks_unfinished_task_interrupted(self):
        self.store.mutate(self.item["id"], lambda row: row.update(generation_job={"status": "running"}))
        self.assertEqual(NoteJobs(self.store).get(self.item["id"])["status"], "interrupted")

    def test_word_is_real_docx_with_summary_decision_and_editable_text(self):
        item = {**self.item, "overview": overview.validate(self.summary, self.segments), "generation": {"mode": "llm", "scene": "meeting"}}
        content = export_docx(item, "虚构项目讨论")
        with zipfile.ZipFile(BytesIO(content)) as archive:
            document = ET.fromstring(archive.read("word/document.xml"))
            words = "".join(document.itertext())
            self.assertIn("最终决策", words)
            self.assertIn("采用方案 B", words)
            self.assertIn("负责人：李明", words)
            self.assertNotIn("SECRET", words)
            ET.fromstring(archive.read("word/styles.xml"))
            self.assertIsNone(archive.testzip())


class NotesApiTests(unittest.TestCase):
    setUp = server_helpers.ServerTests.setUp
    tearDown = server_helpers.ServerTests.tearDown
    call = server_helpers.ServerTests.call
    lecture = server_helpers.ServerTests.lecture
    imported = server_helpers.ServerTests.imported

    def test_no_job_or_network_without_explicit_consent(self):
        item = self.imported()
        base = "/api/lectures/" + item["id"]
        with patch("core.chat_stream.chat") as external:
            self.assertEqual(self.call("POST", base + "/notes/jobs", {})[0], 400)
            external.assert_not_called()
        self.assertIsNone(self.call("GET", base + "/notes/jobs")[1]["job"])

    def test_docx_download_does_not_call_api_or_export_keys(self):
        item = self.imported()
        status, body, headers = self.call("GET", "/api/lectures/" + item["id"] + "/export?format=docx")
        self.assertEqual(status, 200)
        self.assertIn("wordprocessingml", headers["Content-Type"])
        self.assertEqual(body[:2], b"PK")
