"""Scene, provenance and correction checks; synthetic text and mocked providers."""
import json
import unittest
from unittest.mock import patch

from core import pipeline, workflow
from test_connectors import model_response
import test_server as server_helpers


class WorkflowTests(unittest.TestCase):
    def test_scene_prompts_are_distinct_and_meeting_is_cautious(self):
        prompts = [workflow.scene_prompt({"scene": scene, "instructions": "自定义" if scene == "custom" else ""}) for scene in workflow.PROFILES]
        self.assertEqual(len(set(prompts)), 5)
        self.assertIn("不得从发言人标签推断负责人", workflow.scene_prompt({"scene": "meeting"}))
        self.assertIn("不将沉默当赞同", workflow.scene_prompt({"scene": "discussion"}))
        self.assertIn("不制造考试题", workflow.scene_prompt({"scene": "lecture"}))

    def test_custom_and_invalid_modes(self):
        for value in ([], {"scene": "invented"}, {"scene": "custom"}, {"scene": []}, {"instructions": "文" * 6001}):
            with self.subTest(value=str(value)[:50]), self.assertRaises(ValueError):
                workflow.normalize(value)
        result = workflow.normalize({"scene": "custom", "instructions": "读书会，保留提问"})
        self.assertEqual(result["scene"], "custom")

    def test_tingwu_json_milliseconds_and_speakers(self):
        raw = {"Transcription": {"Paragraphs": [{"SpeakerId": "2", "Words": [
            {"SentenceId": 1, "Start": 1200, "End": 1600, "Text": "先讨论。"},
            {"SentenceId": 2, "Start": 2000, "End": 3000, "Text": "未作决定。"}]}]}}
        result = pipeline.parse_transcript(json.dumps(raw), "json")
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["start"], 1.2)
        self.assertEqual(result["segments"][1]["end"], 3)
        self.assertEqual(result["segments"][1]["speaker"], "发言人 2")
        self.assertEqual(result["segments"][0]["review_status"], "unreviewed")
        raw["Transcription"]["Paragraphs"][0]["Words"][0]["Start"] = True
        with self.assertRaises(pipeline.PipelineError):
            pipeline.parse_transcript(json.dumps(raw))

    @patch("core.pipeline._request_bytes")
    def test_meeting_config_reaches_model_without_removing_guardrails(self, network):
        rows = pipeline.parse_transcript('[{"text":"建议下周再讨论","speaker":"发言人 1"}]')["segments"]
        network.return_value = model_response([{"category": "review", "title": "尚无决议", "content": "只有建议，未确认决定。", "source_ids": ["s0001"]}])
        result = pipeline.generate_llm_notes(rows, {"base_url": "https://example.com", "model": "synthetic"}, allow_external=True,
                                             workflow_config={"scene": "meeting", "prompt_override": "请尽量简短"})
        messages = json.loads(network.call_args.args[1])["messages"]
        self.assertIn("不得编造", messages[0]["content"])
        self.assertIn("请尽量简短", messages[2]["content"])
        self.assertEqual(json.loads(messages[1]["content"])["segments"][0]["speaker"], "发言人 1")
        self.assertEqual(result["scene"], "meeting")
        self.assertTrue(result["prompt_hash"])

    @patch("core.pipeline._request_bytes")
    def test_correction_proposals_never_mutate_source(self, network):
        rows = pipeline.parse_transcript("知决现象学")["segments"]
        settings = {"base_url": "https://example.com", "model": "synthetic"}
        body = {"corrections": [{"source_id": "s0001", "text": "知觉现象学", "reason": "疑似术语错字，需回听"}]}
        network.return_value = json.dumps({"choices": [{"message": {"content": json.dumps(body)}}]}).encode()
        with self.assertRaises(pipeline.PipelineError):
            pipeline.propose_corrections(rows, settings)
        network.assert_not_called()
        result = pipeline.propose_corrections(rows, settings, allow_external=True)
        self.assertEqual(rows[0]["text"], "知决现象学")
        self.assertEqual(result["corrections"][0]["after"], "知觉现象学")
        body["corrections"][0]["source_id"] = "s9999"
        network.return_value = json.dumps({"choices": [{"message": {"content": json.dumps(body)}}]}).encode()
        with self.assertRaises(pipeline.PipelineError):
            pipeline.propose_corrections(rows, settings, allow_external=True)


class WorkflowServerTests(unittest.TestCase):
    setUp = server_helpers.ServerTests.setUp
    tearDown = server_helpers.ServerTests.tearDown
    call = server_helpers.ServerTests.call
    lecture = server_helpers.ServerTests.lecture
    imported = server_helpers.ServerTests.imported
    indexed = server_helpers.ServerTests.indexed

    def test_scene_saved_per_material_and_per_scene(self):
        first, second = self.lecture(), self.lecture()
        base = "/api/lectures/" + first["id"]
        self.assertEqual(self.call("PUT", base + "/workflow", {"scene": "custom"})[0], 400)
        status, item, _ = self.call("PUT", base + "/workflow", {"scene": "meeting", "instructions": "只列决议"})
        self.assertEqual(status, 200, item)
        self.assertEqual(item["workflow"]["scene"], "meeting")
        item = self.call("PUT", base + "/workflow", {"scene": "class"})[1]
        self.assertEqual(item["workflow_presets"]["meeting"]["instructions"], "只列决议")
        self.assertEqual(self.call("GET", "/api/lectures/" + second["id"])[1]["workflow"]["scene"], "class")

    def test_tingwu_handoff_private_path_only_on_explicit_prepare(self):
        audio, draft, base = self.indexed()
        self.assertEqual(self.call("POST", base + "/external-transcription/prepare", {})[0], 400)
        status, result, _ = self.call("POST", base + "/external-transcription/prepare", {"acknowledge_privacy": True})
        self.assertEqual(status, 200, result)
        self.assertIn(str(audio), result["prompt"])
        self.assertIn("准备此任务包不等于上传授权", result["prompt"])
        self.assertEqual(result["lecture"]["external_transcription"]["status"], "prepared")
        self.assertNotIn("external_transcription_private", result["lecture"])
        export = self.call("GET", base + "/export?format=json")[1]
        self.assertNotIn(str(audio), json.dumps(export))
        status, detail, _ = self.call("POST", base + "/transcript", {"text": "导回的完整稿", "source": "tingwu", "replace": True})
        self.assertEqual(status, 200, detail)
        self.assertEqual(detail["external_transcription"]["status"], "imported")
        self.assertEqual(detail["transcript_source"]["provider"], "tingwu")
        self.assertEqual(len(detail["transcript_history"]), 1)
        self.assertNotIn("local_sources", detail["transcript_history"][0])

    def test_handoff_changed_audio_blocks_wrong_import(self):
        audio, draft, base = self.indexed()
        self.call("POST", base + "/external-transcription/prepare", {"acknowledge_privacy": True})
        audio.write_bytes(audio.read_bytes() + b"changed")
        status, error, _ = self.call("POST", base + "/transcript", {"text": "wrong file", "source": "tingwu", "replace": True})
        self.assertEqual(status, 409, error)

    def test_selective_correction_invalidates_notes_and_stale_proposals(self):
        item = self.imported()
        base = "/api/lectures/" + item["id"]
        self.call("POST", base + "/notes/generate", {"mode": "local"})
        item = self.server.store.get(item["id"])
        proposal = {"id": "p1", "model": "synthetic", "source_hash": workflow.digest(item["segments"]),
                    "corrections": [{"source_id": "s0001", "before": item["segments"][0]["text"], "after": "仅为合成修订", "reason": "合成测试"}]}
        self.server.store.mutate(item["id"], lambda row: row.update(correction_proposal=proposal))
        self.assertEqual(self.call("POST", base + "/corrections/apply", {"proposal_id": "p1", "source_ids": []})[0], 400)
        status, item, _ = self.call("POST", base + "/corrections/apply", {"proposal_id": "p1", "source_ids": ["s0001"]})
        self.assertEqual(status, 200, item)
        self.assertEqual(item["segments"][0]["text"], "仅为合成修订")
        self.assertNotEqual(item["segments"][0]["original_text"], "仅为合成修订")
        self.assertEqual(item["notes"][0]["review_status"], "needs_review")
        self.assertEqual(len(item["correction_history"]), 1)
        self.call("PUT", base + "/segments/s0001", {"text": "人工再修改"})
        self.assertEqual(self.call("POST", base + "/corrections/apply", {"proposal_id": "p1", "source_ids": ["s0001"]})[0], 409)

    @patch("app.pipeline.generate_llm_notes")
    def test_mode_sent_and_saved_in_generation(self, generate):
        item = self.imported()
        base = "/api/lectures/" + item["id"]
        generate.return_value = {"notes": [], "model": "fake", "warnings": []}
        self.call("PUT", base + "/workflow", {"scene": "meeting"})
        status, item, _ = self.call("POST", base + "/notes/generate", {"mode": "llm", "allow_external": True})
        self.assertEqual(status, 200, item)
        self.assertEqual(generate.call_args.kwargs["workflow_config"]["scene"], "meeting")
        self.assertEqual(item["generation"]["scene_label"], "会议纪要")

    @patch("app.probe")
    def test_local_configuration_and_explicit_start(self, probe):
        probe.return_value = {"ok": True, "message": "synthetic check"}
        status, result, _ = self.call("PUT", "/api/settings", {"local_asr": {"model_path": "/fake-model", "language": "fr"}})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["local_asr"]["language"], "fr")
        self.assertTrue(result["local_asr"]["configured"])
        item = self.lecture()
        self.assertEqual(self.call("POST", f"/api/lectures/{item['id']}/local-asr", {})[0], 400)
        self.assertIsNone(self.call("GET", f"/api/lectures/{item['id']}/local-asr")[1]["job"])
        self.assertEqual(self.call("POST", "/api/local-asr/check", {})[0], 200)

    def test_denoise_requires_local_confirmation_and_does_not_upload(self):
        item = self.lecture()
        base = "/api/lectures/" + item["id"]
        self.assertIsNone(self.call("GET", base + "/audio/denoise")[1]["job"])
        with patch.object(self.server.denoise_jobs, "start", return_value={"status": "running", "progress": 0, "message": "synthetic"}) as start:
            self.assertEqual(self.call("POST", base + "/audio/denoise", {})[0], 400)
            start.assert_not_called()
            self.assertEqual(self.call("POST", base + "/audio/denoise", {"confirm_local": True})[0], 202)
            start.assert_called_once_with(item["id"], "denoised")

    def test_per_recording_language_and_range_repair_consent(self):
        item = self.imported()
        base = "/api/lectures/" + item["id"]
        for value in ("vi", "ja", "zh_en", "fr", "de", "mix:fr,vi"):
            status, detail, _ = self.call("PUT", base, {"asr_language":value})
            self.assertEqual(status, 200, detail)
            self.assertEqual(detail["asr_language"], value)
        status, detail, _ = self.call("PUT", base, {"asr_language":"xx"})
        self.assertEqual(status, 400)
        self.assertIn("不会自动上传", detail["error"])
        with patch.object(self.server.repair_jobs, "start", return_value={"status":"running"}) as start:
            self.assertEqual(self.call("POST", base+"/local-repair", {"segment_ids":["s1"]})[0], 400)
            start.assert_not_called()
            status, _, _ = self.call("POST", base+"/local-repair", {"confirm_local":True,"segment_ids":["s1"]})
            self.assertEqual(status, 202)
            self.assertEqual(start.call_args.args[2]["language"], "mix:fr,vi")
        with patch.object(self.server.jobs, "start", return_value={"status":"running"}) as start:
            self.assertEqual(self.call("POST", base+"/local-asr", {"confirm_local":True})[0], 202)
            self.assertEqual(start.call_args.args[1]["language"], "mix:fr,vi")
        status, detail, _ = self.call("PUT", base, {"asr_language":"mix:vi,fr"})
        self.assertEqual(status,200)
        self.assertEqual(detail["asr_language"],"mix:fr,vi")

    def test_manual_gap_resolution_removes_active_issue_preserving_original(self):
        item = self.imported()
        sid = item["segments"][0]["id"]
        def gap(row):
            segment = row["segments"][0]
            segment.update(text="【转写缺口，非录音原文】",asr_issue=True)
            row["asr_report"] = {"issues":[{"start":segment["start"],"end":segment["end"],"reasons":["synthetic"]}]}
        self.server.store.mutate(item["id"], gap)
        base = f"/api/lectures/{item['id']}/segments/{sid}"
        self.assertEqual(self.call("PUT",base,{"resolve_gap":True})[0],400)
        status, detail, _ = self.call("PUT",base,{"text":"我回听补上的合成测试文字。","resolve_gap":True,"review_status":"verified"})
        self.assertEqual(status,200,detail)
        self.assertFalse(detail["segments"][0]["asr_issue"])
        self.assertEqual(detail["segments"][0]["review_status"],"verified")
        self.assertTrue(detail["asr_report"]["issues"][0]["resolved"])


if __name__ == "__main__":
    unittest.main()
