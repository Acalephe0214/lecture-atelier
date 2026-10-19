import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib import error

from core import pipeline


def model_response(notes, reason="stop"):
    return json.dumps({"choices": [{"finish_reason": reason, "message": {"content": json.dumps({"notes": notes}, ensure_ascii=False)}}]}).encode()


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.segments = pipeline.parse_transcript("课堂原文甲\n课堂原文乙")["segments"]
        self.settings = {"base_url": "https://example.com/v1", "model": "test-model", "api_key": "NEVER-LEAK-SECRET"}
        self.note = {"category": "concept", "title": "概念", "content": "整理后的内容", "source_ids": ["s0001"]}

    @patch("core.pipeline._request_bytes")
    def test_no_network_without_per_action_consent(self, network):
        with self.assertRaises(pipeline.PipelineError):
            pipeline.generate_llm_notes(self.segments, self.settings)
        with self.assertRaises(pipeline.PipelineError):
            pipeline.transcribe_audio("missing.wav", self.settings)
        network.assert_not_called()

    @patch("core.pipeline._request_bytes")
    def test_missing_config_no_network(self, network):
        for settings in ({}, {"base_url": "https://example.com", "model": ""}, {"base_url": "", "model": "test"}):
            with self.assertRaises(pipeline.PipelineError):
                pipeline.generate_llm_notes(self.segments, settings, allow_external=True)
        network.assert_not_called()

    @patch("core.pipeline._request_bytes")
    def test_llm_citations_and_unreviewed_and_missing_coverage(self, network):
        network.return_value = model_response([dict(self.note, review_status="verified", user_edited=True, id="invented")])
        result = pipeline.generate_llm_notes(self.segments, self.settings, allow_external=True)
        self.assertEqual(result["mode"], "llm")
        self.assertEqual(len(result["notes"]), 2)
        self.assertEqual(result["notes"][1]["content"], "课堂原文乙")
        self.assertEqual(result["notes"][1]["category"], "review")
        self.assertTrue(all(row["review_status"] == "unreviewed" and not row["user_edited"] for row in result["notes"]))
        url, payload, headers = network.call_args.args
        self.assertEqual(url, "https://example.com/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer NEVER-LEAK-SECRET")
        self.assertIn("source_ids", json.loads(payload)["messages"][0]["content"])

    @patch("core.pipeline._request_bytes")
    def test_hallucinated_source_rejected(self, network):
        network.return_value = model_response([dict(self.note, source_ids=["s9999"])])
        with self.assertRaises(pipeline.PipelineError):
            pipeline.generate_llm_notes(self.segments, self.settings, allow_external=True)

    @patch("core.pipeline._request_bytes")
    def test_truncated_response_rejected(self, network):
        network.return_value = model_response([self.note], "length")
        with self.assertRaisesRegex(pipeline.PipelineError, "截断"):
            pipeline.generate_llm_notes(self.segments, self.settings, allow_external=True)

    @patch("core.pipeline._request_bytes")
    def test_bad_service_payloads_safe(self, network):
        for body in (b"NEVER-LEAK-SECRET", b"{}", b'{"choices":[]}', b'\xff',
                     json.dumps({"choices": [{"message": {"content": "not json NEVER-LEAK-SECRET"}}]}).encode()):
            network.return_value = body
            with self.assertRaises(pipeline.PipelineError) as exc:
                pipeline.generate_llm_notes(self.segments, self.settings, allow_external=True)
            self.assertNotIn("NEVER-LEAK-SECRET", str(exc.exception))

    @patch("core.pipeline._request_bytes")
    def test_long_inputs_preserve_every_segment(self, network):
        rows = pipeline.parse_transcript(json.dumps([{"text": "文" * 7000} for _ in range(5)]))["segments"]
        seen = []
        def respond(url, data, headers):
            batch = json.loads(json.loads(data)["messages"][1]["content"])["segments"]
            seen.extend(row["id"] for row in batch)
            return model_response([{**self.note, "source_ids": [row["id"]]} for row in batch])
        network.side_effect = respond
        result = pipeline.generate_llm_notes(rows, self.settings, allow_external=True)
        self.assertEqual(seen, [row["id"] for row in rows])
        self.assertGreater(network.call_count, 1)
        self.assertEqual(len({row["id"] for row in result["notes"]}), len(result["notes"]))

    @patch("core.pipeline._request_bytes")
    def test_long_input_limit_is_not_silent_truncation(self, network):
        rows = [{"id": f"s{i}", "text": "文" * 16000} for i in range(17)]
        with self.assertRaisesRegex(pipeline.PipelineError, "不会静默截断"):
            pipeline.generate_llm_notes(rows, self.settings, allow_external=True)
        network.assert_not_called()

    def test_endpoint_restrictions(self):
        for url in ("http://example.com/v1", "https://192.168.0.2/v1", "https://169.254.169.254/v1", "https://10.0.0.1/v1", "file:///tmp/test", "https://user:pass@example.com/v1", "https://example.com/v1?key=secret", "https://example.com/a#fragment", "https://example.com:99999/v1", "https://example.com/\nx"):
            with self.subTest(url=url), self.assertRaises(pipeline.PipelineError):
                pipeline._endpoint(url)
        for url in ("http://localhost:1234/v1", "http://127.0.0.1:1234", "http://[::1]:1234/v1", "https://example.com/v1"):
            self.assertTrue(pipeline._endpoint(url))

    @patch("core.pipeline.socket.getaddrinfo")
    def test_dns_private_address_rejected(self, dns):
        dns.return_value = [(2, 1, 6, "", ("192.168.1.10", 443))]
        with self.assertRaises(pipeline.PipelineError):
            pipeline._validate_dns("https://example.com")

    def test_redirects_refused(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "重定向"):
            pipeline._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example")

    @patch("core.pipeline.request.build_opener")
    @patch("core.pipeline._validate_dns")
    def test_http_errors_do_not_leak_secrets(self, dns, opener):
        opener.return_value.open.side_effect = error.HTTPError("https://secret.example/NEVER-LEAK-SECRET", 401, "NEVER-LEAK-SECRET", {}, None)
        with self.assertRaises(pipeline.PipelineError) as exc:
            pipeline._request_bytes("https://example.com", b"{}", {})
        self.assertNotIn("NEVER-LEAK-SECRET", str(exc.exception))
        self.assertIn("认证", str(exc.exception))

    @patch("core.pipeline._request_bytes")
    def test_asr_json_and_multipart_contract(self, network):
        network.return_value = json.dumps({"segments": [{"start": 1.5, "end": 4, "text": "课堂文字"}]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice.wav"
            path.write_bytes(b"RIFF\0WAVE\0fake-audio-for-unit-test")
            result = pipeline.transcribe_audio(path, self.settings, allow_external=True)
        self.assertEqual(result["segments"][0]["start"], 1.5)
        url, payload, headers = network.call_args.args
        self.assertEqual(url, "https://example.com/v1")
        for field in (b'name="file"', b'name="model"', b'name="response_format"', b"verbose_json"):
            self.assertIn(field, payload)
        self.assertIn("multipart/form-data", headers["Content-Type"])
        self.assertIn("original_transcript", result)

    @patch("core.pipeline._request_bytes")
    def test_asr_srt(self, network):
        network.return_value = "1\n00:00:01,000 --> 00:00:02,000\n文字\n".encode()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice.mp3"
            path.write_bytes(b"fake")
            result = pipeline.transcribe_audio(path, self.settings, allow_external=True)
        self.assertEqual(result["format"], "srt")

    @patch("core.pipeline._request_bytes")
    def test_asr_missing_timestamps_not_fabricated(self, network):
        network.return_value = b'{"segments":[{"text":"a"}]}'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice.wav"
            path.write_bytes(b"fake")
            with self.assertRaisesRegex(pipeline.PipelineError, "真实"):
                pipeline.transcribe_audio(path, self.settings, allow_external=True)

    @patch("core.pipeline._request_bytes")
    def test_missing_and_empty_audio(self, network):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "voice.wav"
            with self.assertRaises(pipeline.PipelineError):
                pipeline.transcribe_audio(path, self.settings, allow_external=True)
            path.write_bytes(b"")
            with self.assertRaises(pipeline.PipelineError):
                pipeline.transcribe_audio(path, self.settings, allow_external=True)
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
