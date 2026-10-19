"""Paid-work recovery regressions using synthetic provider responses only."""
from copy import deepcopy
import json
import tempfile
import unittest
from unittest.mock import patch

from core import pipeline
from note_checkpoints import NoteCheckpoints
from note_jobs import NoteJobs
from store import Store
from test_note_jobs import fixture


def response(value):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(value, ensure_ascii=False), "reasoning_content": "HIDDEN-REASONING"}}]}


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.segments, self.notes, self.summary = fixture()
        item = self.store.create("course-sample", "Synthetic recovery", "2026-10-19")
        self.item = self.store.mutate(item["id"], lambda row: row.update(segments=self.segments, notes=self.notes))
        self.settings = {"llm": {"base_url": "https://example.com", "model": "synthetic", "api_key": "SECRET"}, "glossary": []}
        self.jobs = NoteJobs(self.store)

    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def wait(self):
        self.jobs.jobs[self.item["id"]]["_thread"].join(4)
        job = self.jobs.get(self.item["id"])
        self.assertNotIn(job["status"], {"queued", "running"})
        return job

    def model(self, endpoint, payload, headers, report):
        report({"usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}})
        data = json.loads(payload["messages"][1]["content"])
        if "segments" in data:
            return response({"notes": [{"category": "comment", "title": "Synthetic detail", "content": "Synthetic detail content.", "source_ids": [row["id"] for row in data["segments"]]}]})
        return response(self.summary)

    def test_failed_third_batch_reuses_first_two_after_restart_and_counts_new_usage_only(self):
        def fail_third(*args):
            answer = self.model(*args)
            data = json.loads(args[1]["messages"][1]["content"])
            if data.get("segments", [{}])[0].get("id") == self.segments[2]["id"]:
                return response({"notes": [{**self.notes[0], "source_ids": ["invented-id"]}]})
            return answer
        batches = [[row] for row in self.segments]
        with patch("core.pipeline._batches", return_value=batches), patch("core.chat_stream.chat", side_effect=fail_third) as network:
            self.jobs.start(self.item, self.settings)
            first = self.wait()
        self.assertEqual(first["status"], "failed")
        self.assertEqual(network.call_count, 3)
        self.assertEqual(first["failure_batch"], 3)
        self.assertEqual(first["draft_notes"], 2)
        self.assertEqual(self.store.get(self.item["id"])["notes"], self.notes)
        self.assertEqual(len(self.jobs.draft(self.item["id"])["notes"]), 2)
        self.assertNotIn("Synthetic detail content", json.dumps(first))
        self.jobs.close()
        self.jobs = NoteJobs(self.store)
        with patch("core.pipeline._batches", return_value=batches), patch("core.chat_stream.chat", side_effect=self.model) as network:
            plan = self.jobs.preview(self.item, self.settings, "all")
            self.assertEqual(plan["details_ready"], 2)
            self.jobs.start(self.item, self.settings)
            second = self.wait()
        self.assertEqual(second["status"], "completed", second)
        self.assertEqual(network.call_count, 2)  # third detail + overview, not all four
        self.assertEqual(second["reused_units"], 2)
        self.assertEqual(second["usage"]["total_tokens"], 240)

    def test_overview_failure_keeps_all_details_and_retry_only_calls_overview(self):
        def fail_overview(*args):
            answer = self.model(*args)
            data = json.loads(args[1]["messages"][1]["content"])
            if "sources" in data:
                bad = deepcopy(self.summary)
                bad["summary"]["source_ids"] = ["n0001"]
                return response(bad)
            return answer
        with patch("core.chat_stream.chat", side_effect=fail_overview):
            self.jobs.start(self.item, self.settings)
            job = self.wait()
        self.assertEqual(job["status"], "failed")
        self.assertTrue(job["draft_complete"])
        with patch("core.chat_stream.chat", side_effect=self.model) as network:
            self.jobs.start(self.item, self.settings)
            job = self.wait()
        self.assertEqual(job["status"], "completed", job)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(job["reused_units"], 1)

    def test_draft_adoption_is_local_and_preserves_prior_notes_in_history(self):
        with patch("core.chat_stream.chat", side_effect=[self.model("", {"messages": [{}, {"content": json.dumps({"segments": self.segments})}]}, {}, lambda _: None), response({})]):
            self.jobs.start(self.item, self.settings)
            self.wait()
        with patch("core.chat_stream.chat") as network:
            saved = self.jobs.adopt_draft(self.item["id"])
            network.assert_not_called()
        self.assertEqual(saved["note_history"][-1]["notes"], self.notes)
        self.assertEqual(saved["notes"][0]["title"], "Synthetic detail")

    def test_concurrent_manual_edit_blocks_draft_adoption(self):
        with patch("core.chat_stream.chat", side_effect=[self.model("", {"messages": [{}, {"content": json.dumps({"segments": self.segments})}]}, {}, lambda _: None), response({})]):
            self.jobs.start(self.item, self.settings)
            self.wait()
        self.store.mutate(self.item["id"], lambda row: row["notes"][0].update(content="MANUAL EDIT"))
        with self.assertRaises(pipeline.PipelineError):
            self.jobs.adopt_draft(self.item["id"])
        self.assertEqual(self.store.get(self.item["id"])["notes"][0]["content"], "MANUAL EDIT")

    def test_invalid_answer_is_private_and_never_marked_reusable(self):
        cache = NoteCheckpoints(self.store, self.item["id"])
        payload = pipeline.notes_payload(self.segments, [], {}, "synthetic")
        bad = response({"notes": [{**self.notes[0], "source_ids": ["n0001"]}]})
        with self.assertRaises(pipeline.PipelineError):
            cache.run("notes", "https://example.com", payload, lambda: bad, lambda value: pipeline.validate_model_notes(value, self.segments))
        self.assertFalse(cache.ready("notes", "https://example.com", payload))
        with self.store.connection() as conn:
            raw = conn.execute("SELECT response FROM note_checkpoints").fetchone()[0]
        self.assertNotIn("HIDDEN-REASONING", raw)
        self.assertNotIn("SECRET", raw)

    def test_exact_request_match_invalidates_model_source_prompt_language_glossary_endpoint(self):
        cache = NoteCheckpoints(self.store, self.item["id"])
        body = pipeline.notes_payload(self.segments, [], {}, "synthetic")
        good = response({"notes": self.notes})
        cache.run("notes", "endpoint", body, lambda: good, lambda value: pipeline.validate_model_notes(value, self.segments))
        self.assertTrue(cache.ready("notes", "endpoint", body))
        for key, value in (("model", "other"), ("messages", [{"role": "user", "content": "Changed source / glossary / language"}])):
            changed = deepcopy(body); changed[key] = value
            self.assertFalse(cache.ready("notes", "endpoint", changed))
        self.assertFalse(cache.ready("notes", "other-endpoint", body))
        self.assertFalse(NoteCheckpoints(self.store, "another-session").ready("notes", "endpoint", body))

    def test_final_overview_failure_reuses_completed_intermediate_groups(self):
        from core import overview
        cache = NoteCheckpoints(self.store, self.item["id"])
        notes = [{**deepcopy(self.notes[0]), "content": "Synthetic group " + str(index)} for index in range(44)]
        calls = []
        def model(endpoint, payload, headers, report):
            calls.append(payload)
            ids = [row["id"] for row in json.loads(payload["messages"][1]["content"])["sources"]]
            value = {"summary": {"title": "Synthetic summary", "content": "Combined findings.", "source_ids": ids}, "key_points": [], "decisions": [], "actions": [], "open_questions": []}
            if len(calls) == 3:
                value["summary"]["source_ids"] = ["invented"]
            return response(value)
        with patch("core.chat_stream.chat", side_effect=model):
            with self.assertRaises(pipeline.PipelineError):
                overview.synthesize(notes, self.segments, self.settings["llm"], {}, True, lambda _: None, cache)
            self.assertEqual(len(calls), 3)
            result = overview.synthesize(notes, self.segments, self.settings["llm"], {}, True, lambda _: None, cache)
        self.assertEqual(len(calls), 4)
        self.assertEqual(cache.reused, 2)
        self.assertTrue(result["summary"]["source_ids"])

    def test_cache_revalidation_rejects_corrupted_stored_citations(self):
        cache = NoteCheckpoints(self.store, self.item["id"])
        body = pipeline.notes_payload(self.segments, [], {}, "synthetic")
        key = cache.key("notes", "endpoint", body)
        corrupt = response({"notes": [{**self.notes[0], "source_ids": ["invented"]}]})
        with self.store.connection() as conn:
            conn.execute("INSERT INTO note_checkpoints VALUES (?,?,?,?,1)", (key, self.item["id"], "notes", json.dumps(corrupt)))
        with patch("core.chat_stream.chat", return_value=response({"notes": self.notes})) as network:
            cache.run("notes", "endpoint", body, lambda: network(), lambda value: pipeline.validate_model_notes(value, self.segments))
        self.assertEqual(network.call_count, 1)
        self.assertEqual(cache.reused, 0)

    def test_only_harmless_source_representation_is_normalized(self):
        candidate = deepcopy(self.summary)
        candidate["summary"]["source_ids"] = " s0001 "
        from core import overview
        self.assertEqual(overview.validate(candidate, self.segments)["summary"]["source_ids"], ["s0001"])
        for wrong in ("1", "n0001", "s1", "s0001,s0002", ["s0001", "bad"]):
            candidate["summary"]["source_ids"] = wrong
            with self.assertRaises(pipeline.PipelineError):
                overview.validate(candidate, self.segments)


if __name__ == "__main__":
    unittest.main()
