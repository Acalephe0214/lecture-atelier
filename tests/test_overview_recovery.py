"""Overview failures and repair guards. Only synthetic responses, no paid API."""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from core import overview, pipeline, usage_estimate
from core.chat_stream import read_stream
from note_jobs import NoteJobs
from store import Store
from test_note_jobs import fixture
import test_server as server_helpers


def response(content, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}]}


class ResponseTests(unittest.TestCase):
    def test_length_error_is_not_swallowed_by_valueerror_handler(self):
        with self.assertRaisesRegex(overview.ModelOutputError, "额度上限") as failure:
            overview.parse_response(response('{"summary":', "length"))
        self.assertEqual(failure.exception.diagnostic["finish_reason"], "length")
        self.assertEqual(failure.exception.diagnostic["error_code"], "output_limit")

    def test_never_accept_complete_json_when_provider_reports_length(self):
        with self.assertRaises(overview.ModelOutputError):
            overview.parse_response(response('{}', "length"))

    def test_fenced_complete_json_is_parsed_without_another_request(self):
        for text in ('{"summary":{}}', '```json\n{"summary":{}}\n```', '```\n{"summary":{}}\n```'):
            value, _ = overview.parse_response(response(text))
            self.assertEqual(value, {"summary": {}})

    def test_never_salvage_partial_json_or_extract_it_from_prose(self):
        for text in ('{"summary":', '```json\n{"summary":{}}', 'Here is the result: {"summary":{}}'):
            with self.assertRaises(overview.ModelOutputError) as failure:
                overview.parse_response(response(text))
            self.assertEqual(failure.exception.diagnostic["error_code"], "invalid_json")

    def test_reasoning_only_is_distinguished_and_not_stored(self):
        value = response(None)
        value["choices"][0]["message"]["reasoning_content"] = "PRIVATE-REASONING"
        with self.assertRaisesRegex(overview.ModelOutputError, "没有返回总览正文") as failure:
            overview.parse_response(value)
        self.assertNotIn("PRIVATE-REASONING", json.dumps(failure.exception.diagnostic))

    def test_filter_and_bad_response_have_distinct_errors(self):
        with self.assertRaisesRegex(overview.ModelOutputError, "过滤或拒绝"):
            overview.parse_response(response('{}', "content_filter"))
        for value in (None, [], {}, {"choices": []}, {"choices": ["bad"]}):
            with self.assertRaisesRegex(overview.ModelOutputError, "响应结构无效"):
                overview.parse_response(value)

    def test_provider_error_not_reported_as_malformed_sse(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "模型流返回错误") as failure:
            read_stream(BytesIO(b'data: {"error":{"message":"SECRET"}}\n\n'), lambda _: None, pipeline.PipelineError)
        self.assertNotIn("SECRET", str(failure.exception))

    def test_callback_controlled_error_not_mislabeled_as_bad_sse(self):
        def stopped(_):
            raise pipeline.PipelineError("本地服务已关闭")
        with self.assertRaisesRegex(pipeline.PipelineError, "本地服务已关闭"):
            read_stream(BytesIO(b'data: {"choices":[]}\n\n'), stopped, pipeline.PipelineError)

    def test_thinking_toggle_is_only_sent_to_verified_supported_provider(self):
        for model in ("deepseek-flash", "deepseek-v4-pro"):
            self.assertEqual(overview.request_policy("https://api.deepseek.com/v1/chat/completions", model)["thinking"], {"type": "disabled"})
        for url, model in (("https://other.example/v1", "deepseek-flash"), ("https://api.deepseek.com.evil.example", "deepseek-flash"), ("https://api.deepseek.com", "unknown")):
            self.assertNotIn("thinking", overview.request_policy(url, model))


class GroupingTests(unittest.TestCase):
    def test_44_notes_split_and_merge_without_source_omission(self):
        segments, notes, _ = fixture()
        notes = [{**deepcopy(notes[0]), "content": str(i) + "细节" * 90} for i in range(44)]
        seen = []
        def model(url, payload, headers, report):
            material = json.loads(payload["messages"][1]["content"])
            seen.append(material)
            self.assertEqual(payload["max_tokens"], 12000)
            self.assertNotIn("24000字", payload["messages"][0]["content"])
            ids = [row["id"] for row in material["sources"]]
            summary = {"summary": {"title": "综合", "content": "综合后的结论，详情保留在详细笔记。", "source_ids": ids}, "key_points": [], "decisions": [], "actions": [], "open_questions": []}
            return response(json.dumps(summary))
        with patch("core.chat_stream.chat", side_effect=model) as external:
            result = overview.synthesize(notes, segments, {"base_url": "https://example.com", "model": "synthetic"}, {"scene": "meeting"}, True, lambda _: None)
        self.assertEqual(external.call_count, 3)
        self.assertEqual(sum(len(group["entries"]) for group in seen[:2]), 44)
        self.assertEqual([row for group in seen[:2] for row in group["entries"]], [{key: row[key] for key in ("category", "title", "content", "source_ids")} for row in notes])
        self.assertEqual(set(result["summary"]["source_ids"]), {row["id"] for row in segments})
        estimated = usage_estimate.estimate({"segments": segments, "notes": notes}, {"llm": {}}, "overview")
        self.assertEqual(estimated["requests"][0], 3)
        self.assertGreaterEqual(estimated["requests"][1], 3)

    def test_oversized_or_orphaned_note_fails_before_any_call(self):
        segments, notes, _ = fixture()
        for source in (["missing"], notes[0]["source_ids"]):
            notes[0].update(content="过长" * 30000, source_ids=source)
            with patch("core.chat_stream.chat") as external:
                with self.assertRaises(pipeline.PipelineError):
                    overview.synthesize(notes, segments, {"base_url": "https://example.com", "model": "synthetic"}, {}, True, lambda _: None)
                external.assert_not_called()


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        row = self.store.create("course-sample", "虚构诊断", "2026-10-18")
        self.segments, self.notes, self.summary = fixture()
        self.item = self.store.mutate(row["id"], lambda item: item.update(segments=self.segments, notes=self.notes, overview={"previous": "keep"}))
        self.settings = {"llm": {"model": "synthetic", "base_url": "https://example.com", "api_key": "SECRET"}, "glossary": []}
        self.jobs = NoteJobs(self.store)

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def run_job(self, answer):
        with patch("core.chat_stream.chat", return_value=answer) as external:
            self.jobs.start(self.item, self.settings, "overview")
            self.jobs.jobs[self.item["id"]]["_thread"].join(4)
            self.assertEqual(external.call_count, 1)
        return self.jobs.get(self.item["id"])

    def test_length_failure_diagnostic_private_persisted_and_notes_untouched(self):
        answer = response('{"summary": "UNFINISHED SECRET https://example.com', "length")
        answer["choices"][0]["message"]["reasoning_content"] = "HIDDEN-REASONING"
        job = self.run_job(answer)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["finish_reason"], "length")
        self.assertTrue(job["diagnostics_available"])
        self.assertNotIn("UNFINISHED", json.dumps(job))
        self.assertNotIn("SECRET", json.dumps(job))
        saved = self.store.get(self.item["id"])
        self.assertEqual(saved["notes"], self.notes)
        self.assertEqual(saved["overview"], {"previous": "keep"})
        diagnostic = NoteJobs(self.store).diagnostics(self.item["id"])
        self.assertEqual(diagnostic["error_code"], "output_limit")
        self.assertIn("UNFINISHED", diagnostic["answer_excerpt"])
        for hidden in ("SECRET", "https://example.com", "HIDDEN-REASONING", "Authorization"):
            self.assertNotIn(hidden, json.dumps(diagnostic))
        path = Path(self.temp.name) / "note-diagnostics" / (job["id"] + ".json")
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_invalid_evidence_also_saves_answer_for_diagnosis(self):
        self.summary["decisions"][0]["evidence_quote"] = "INVENTED"
        job = self.run_job(response(json.dumps(self.summary)))
        self.assertEqual(job["status"], "failed")
        diagnostic = self.jobs.diagnostics(self.item["id"])
        self.assertEqual(diagnostic["error_code"], "invalid_evidence_or_schema")
        self.assertIn("INVENTED", diagnostic["answer_excerpt"])

    def test_fenced_valid_answer_saves_without_replacing_notes(self):
        job = self.run_job(response('```json\n' + json.dumps(self.summary) + '\n```'))
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(self.store.get(self.item["id"])["notes"], self.notes)
        self.assertFalse(job.get("diagnostics_available"))
        with self.assertRaises(KeyError):
            self.jobs.diagnostics(self.item["id"])

    def test_old_job_does_not_pretend_a_raw_response_was_preserved(self):
        self.store.mutate(self.item["id"], lambda item: item.update(generation_job={"id": "old", "status": "failed", "message": "old error"}))
        with self.assertRaises(KeyError):
            self.jobs.diagnostics(self.item["id"])


class DiagnosticApiTests(unittest.TestCase):
    setUp = server_helpers.ServerTests.setUp
    tearDown = server_helpers.ServerTests.tearDown
    call = server_helpers.ServerTests.call
    lecture = server_helpers.ServerTests.lecture
    imported = server_helpers.ServerTests.imported

    def test_explicit_diagnostic_download_and_no_automatic_paid_retry(self):
        item = self.imported()
        base = "/api/lectures/" + item["id"]
        store = self.server.store
        segments, notes, _ = fixture()
        store.mutate(item["id"], lambda value: value.update(segments=segments, notes=notes))
        store.update_settings({"llm": {"base_url": "https://example.com", "model": "synthetic", "api_key": "SECRET"}})
        with patch("core.chat_stream.chat", return_value=response('{"summary":"PRIVATE-DRAFT', "length")) as external:
            status, _, _ = self.call("POST", base + "/notes/jobs", {"scope": "overview", "allow_external": True})
            self.assertEqual(status, 202)
            self.server.note_jobs.jobs[item["id"]]["_thread"].join(4)
            status, public, _ = self.call("GET", base + "/notes/jobs")
            self.assertEqual(status, 200)
            self.assertNotIn("PRIVATE-DRAFT", json.dumps(public))
            status, diagnostic, _ = self.call("GET", base + "/notes/jobs/diagnostics")
            self.assertEqual(status, 200)
            self.assertIn("PRIVATE-DRAFT", diagnostic["answer_excerpt"])
            self.assertEqual(diagnostic["finish_reason"], "length")
            self.assertEqual(external.call_count, 1)
        other = self.lecture()
        self.assertEqual(self.call("GET", "/api/lectures/" + other["id"] + "/notes/jobs/diagnostics")[0], 404)
