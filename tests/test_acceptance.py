"""Black-box acceptance checks for the complete app; never use external APIs."""
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib import error, parse, request
import wave


ROOT = Path(__file__).resolve().parents[1]
LOCAL_HTTP = request.build_opener(request.ProxyHandler({}))


class ApplicationAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="lecture-acceptance-")
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            cls.port = probe.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.log = open(Path(cls.tmp.name) / "server.log", "w+", encoding="utf-8")
        cls.process = subprocess.Popen(
            [sys.executable, str(ROOT / "app.py"), "--port", str(cls.port),
             "--data-dir", str(Path(cls.tmp.name) / "data")],
            cwd=str(ROOT), stdout=cls.log, stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            try:
                with LOCAL_HTTP.open(cls.base + "/api/health", timeout=.5) as response:
                    if response.status == 200:
                        return
            except (OSError, error.URLError):
                pass
            if cls.process.poll() is not None:
                break
            time.sleep(.1)
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.log.seek(0)
        message = cls.log.read()
        cls.log.close()
        cls.tmp.cleanup()
        raise RuntimeError("Local server did not become ready: " + message)

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait(timeout=5)
        cls.log.close()
        cls.tmp.cleanup()

    def call(self, method, path, data=None, headers=None, raw=None):
        body = raw
        actual_headers = dict(headers or {})
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            actual_headers.setdefault("Content-Type", "application/json")
        req = request.Request(self.base + path, data=body, method=method, headers=actual_headers)
        try:
            response = LOCAL_HTTP.open(req, timeout=10)
        except error.HTTPError as exc:
            response = exc
        with response:
            payload = response.read()
            if "application/json" in response.headers.get("Content-Type", ""):
                payload = json.loads(payload)
            return response.status, payload, response.headers

    def make_lecture(self):
        _, state, _ = self.call("GET", "/api/state")
        status, lecture, _ = self.call("POST", "/api/lectures", {
            "course_id": state["courses"][0]["id"],
            "title": "合成验收材料", "date": "2026-10-15",
        })
        self.assertEqual(status, 201, lecture)
        return lecture

    def import_sample(self):
        lecture = self.make_lecture()
        status, detail, _ = self.call("POST", f"/api/lectures/{lecture['id']}/transcript", {
            "text": (ROOT / "examples/import_demo.srt").read_text(encoding="utf-8"),
            "format": "srt",
        })
        self.assertEqual(status, 200, detail)
        return detail

    def test_01_seed_and_static_resources(self):
        status, state, _ = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual({course["name"] for course in state["courses"]}, {"示例课程"})
        for path, mime in [("/", "text/html"), ("/static/app.js", "javascript"),
                           ("/static/style.css", "text/css")]:
            with self.subTest(path=path):
                code, body, headers = self.call("GET", path)
                self.assertEqual(code, 200)
                self.assertIn(mime, headers.get("Content-Type", ""))
                self.assertGreater(len(body), 100)

    def test_02_demo_is_idempotent_and_labelled(self):
        code, first, _ = self.call("POST", "/api/demo", {})
        self.assertEqual(code, 200, first)
        code, second, _ = self.call("POST", "/api/demo", {})
        self.assertEqual(code, 200, second)
        self.assertEqual(first["lecture_id"], second["lecture_id"])
        _, detail, _ = self.call("GET", f"/api/lectures/{first['lecture_id']}")
        self.assertTrue(detail["is_demo"])
        self.assertTrue(detail["segments"])
        self.assertTrue(detail["notes"])

    def test_03_import_extract_review_invalidation_and_exports(self):
        detail = self.import_sample()
        lecture_id = detail["id"]
        self.assertEqual(len(detail["segments"]), 7)
        status, detail, _ = self.call("POST", f"/api/lectures/{lecture_id}/notes/generate", {"mode": "local"})
        self.assertEqual(status, 200, detail)
        self.assertTrue(detail["notes"])
        source = {item["id"]: item for item in detail["segments"]}
        for note in detail["notes"]:
            self.assertTrue(note["source_ids"])
            self.assertTrue(all(sid in source for sid in note["source_ids"]))
            self.assertNotEqual(note["review_status"], "verified")
        note = detail["notes"][0]
        sid = note["source_ids"][0]
        original = source[sid]["original_text"]
        status, detail, _ = self.call("PUT", f"/api/lectures/{lecture_id}/notes/{note['id']}", {"review_status": "verified"})
        self.assertEqual(status, 200, detail)
        status, detail, _ = self.call("PUT", f"/api/lectures/{lecture_id}/segments/{sid}", {
            "text": source[sid]["text"] + " 补充人工校对。",
        })
        self.assertEqual(status, 200, detail)
        self.assertEqual(next(s for s in detail["segments"] if s["id"] == sid)["original_text"], original)
        linked = [n for n in detail["notes"] if sid in n["source_ids"]]
        self.assertTrue(all(n["review_status"] != "verified" for n in linked))
        for fmt in ["md", "json", "srt", "txt"]:
            code, body, headers = self.call("GET", f"/api/lectures/{lecture_id}/export?format={fmt}")
            self.assertEqual(code, 200, (fmt, body))
            self.assertIn("attachment", headers.get("Content-Disposition", ""))
            self.assertTrue(body)

    def test_04_replacements_and_invented_references_rejected(self):
        detail = self.import_sample()
        lecture_id = detail["id"]
        code, result, _ = self.call("POST", f"/api/lectures/{lecture_id}/transcript", {"text": "不应覆盖原文。", "format": "txt"})
        self.assertIn(code, [400, 409], result)
        self.call("POST", f"/api/lectures/{lecture_id}/notes/generate", {"mode": "local"})
        code, result, _ = self.call("POST", f"/api/lectures/{lecture_id}/notes/generate", {"mode": "local"})
        self.assertIn(code, [400, 409], result)
        code, result, _ = self.call("POST", f"/api/lectures/{lecture_id}/notes", {
            "category": "argument", "title": "无依据结论", "content": "这条应被拒绝。", "source_ids": ["invented-source"],
        })
        self.assertGreaterEqual(code, 400, result)

    def test_05_untimed_text_does_not_gain_fake_timestamps(self):
        lecture = self.make_lecture()
        code, detail, _ = self.call("POST", f"/api/lectures/{lecture['id']}/transcript", {
            "text": (ROOT / "examples/untimed_demo.txt").read_text(encoding="utf-8"), "format": "txt",
        })
        self.assertEqual(code, 200, detail)
        self.assertTrue(detail["segments"])
        self.assertTrue(all(s["start"] is None and s["end"] is None for s in detail["segments"]))
        code, _, _ = self.call("GET", f"/api/lectures/{lecture['id']}/export?format=srt")
        self.assertGreaterEqual(code, 400)

    def test_06_local_audio_roundtrip_and_range(self):
        lecture = self.make_lecture()
        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\0\0" * 800)
        audio_bytes = audio_buffer.getvalue()
        path = f"/api/lectures/{lecture['id']}/audio"
        code, detail, _ = self.call("POST", path, raw=audio_bytes, headers={
            "Content-Type": "audio/wav", "X-Filename": parse.quote("合成测试音频.wav"),
        })
        self.assertEqual(code, 200, detail)
        code, restored, _ = self.call("GET", path)
        self.assertEqual(code, 200)
        self.assertEqual(restored, audio_bytes)
        code, partial, headers = self.call("GET", path, headers={"Range": "bytes=0-9"})
        self.assertEqual(code, 206)
        self.assertEqual(partial, audio_bytes[:10])
        self.assertIn("bytes 0-9/", headers.get("Content-Range", ""))
        code, _, _ = self.call("POST", path, raw=audio_bytes, headers={"Content-Type": "audio/wav"})
        self.assertIn(code, [400, 409])

    def test_07_no_implicit_external_requests_or_key_disclosure(self):
        lecture = self.import_sample()
        sentinel = "NOT-A-REAL-KEY-acceptance-only"
        code, public, _ = self.call("PUT", "/api/settings", {
            "llm": {"base_url": "https://example.invalid/v1", "model": "test-only", "api_key": sentinel},
        })
        self.assertEqual(code, 200, public)
        self.assertNotIn(sentinel, json.dumps(public))
        _, state, _ = self.call("GET", "/api/state")
        self.assertNotIn(sentinel, json.dumps(state))
        code, result, _ = self.call("POST", f"/api/lectures/{lecture['id']}/notes/generate", {"mode": "llm", "allow_external": False})
        self.assertGreaterEqual(code, 400, result)
        _, exported, _ = self.call("GET", f"/api/lectures/{lecture['id']}/export?format=json")
        self.assertNotIn(sentinel, str(exported))
        self.call("PUT", "/api/settings", {"llm": {"base_url": "", "model": "", "clear_key": True}})

    def test_08_cross_origin_and_private_paths_blocked(self):
        code, _, _ = self.call("POST", "/api/demo", {}, headers={"Origin": "https://untrusted.example"})
        self.assertIn(code, [400, 403])
        for path in ["/.runtime/settings.json", "/.env", "/store.py", "/static/../store.py"]:
            code, _, _ = self.call("GET", path)
            self.assertGreaterEqual(code, 400, path)


if __name__ == "__main__":
    unittest.main()
