"""Local API integration and privacy tests. Uses only synthetic temp data."""
from pathlib import Path
import http.client
import json
import os
import stat
import struct
import sys
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import make_server
from store import Store
from index_local_course import register
from local_sources import prepare
from audio_processing import fingerprint


class LoopbackBindingTests(unittest.TestCase):
    def test_startup_does_not_resolve_a_hostname(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("socket.getfqdn", side_effect=AssertionError("Unexpected reverse DNS")):
                server = make_server(0, directory)
            try:
                self.assertEqual(server.server_name, "localhost")
                self.assertGreater(server.server_port, 0)
                self.assertEqual(server.server_address[0], "127.0.0.1")
            finally:
                server.server_close()


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lecture-server-test-")
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.server = make_server(0, self.temp.name)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()
        self.env.stop()

    def call(self, method, path, body=None, headers=None, raw=None):
        headers = dict(headers or {})
        if body is not None:
            raw = json.dumps(body).encode()
            headers.setdefault("Content-Type", "application/json")
        client = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        client.request(method, path, body=raw, headers=headers)
        response = client.getresponse()
        payload = response.read()
        status, response_headers = response.status, dict(response.getheaders())
        if "application/json" in response_headers.get("Content-Type", ""):
            payload = json.loads(payload)
        client.close()
        return status, payload, response_headers

    def lecture(self):
        status, item, _ = self.call("POST", "/api/lectures", {"course_id": "course-sample", "title": "合成测试", "date": "2026-10-15"})
        self.assertEqual(status, 201, item)
        return item

    def imported(self):
        item = self.lecture()
        status, item, _ = self.call("POST", f"/api/lectures/{item['id']}/transcript", {
            "text": "1\n00:00:00,000 --> 00:00:10,000\n虚构课堂问题：观察是否等于解释？\n", "format": "srt"})
        self.assertEqual(status, 200, item)
        return item

    def test_seed_state_and_demo_idempotence(self):
        status, state, _ = self.call("GET", "/api/state")
        self.assertEqual(status, 200)
        self.assertEqual([(row["id"], row["name"]) for row in state["courses"]], [("course-sample", "示例课程")])
        self.assertEqual(state["lectures"], [])
        first = self.call("POST", "/api/demo", {})[1]
        second = self.call("POST", "/api/demo", {})[1]
        self.assertEqual(first["lecture_id"], second["lecture_id"])
        self.assertEqual(len(second["lectures"]), 1)
        lecture = self.call("GET", "/api/lectures/" + first["lecture_id"])[1]
        self.assertTrue(lecture["is_demo"])
        self.assertIn("虚构", lecture["segments"][0]["text"])

    def test_english_demo_shared_identity_and_public_help(self):
        status, result, _ = self.call("POST","/api/demo",{"ui_language":"en"})
        self.assertEqual(status,200,result)
        self.assertEqual(result["lecture_id"],"lecture-synthetic-demo")
        status, detail, _ = self.call("GET","/api/lectures/"+result["lecture_id"])
        self.assertIn("Fictional",detail["title"])
        self.assertIn("FICTIONAL",detail["segments"][0]["text"])
        self.assertTrue(detail["notes"][0]["title"].startswith("Source excerpt"))
        self.call("POST","/api/demo",{"ui_language":"en"})
        self.assertEqual(len(self.server.store.lectures()),1)
        self.assertEqual(self.call("POST","/api/demo",{"ui_language":"zh"})[1]["lecture_id"],"lecture-synthetic-demo")
        self.assertEqual(len(self.server.store.lectures()),1)
        self.assertEqual(self.server.store.get(result["lecture_id"])["segments"], detail["segments"])
        for path, marker in [("/help?ui=en",b"English"),("/help?ui=zh","听课之间".encode()),("/START-HERE.html",b"CODEX_SETUP.md")]:
            status, body, _ = self.call("GET",path)
            self.assertEqual(status,200)
            self.assertIn(marker,body)
        self.assertNotEqual(self.call("GET","/CODEX_SETUP.md")[0],200)

    def indexed(self):
        root = Path(self.temp.name)
        audio = root / "synthetic.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(8000)
            handle.writeframes(b"\0\0" * 80000)
        draft = root / "synthetic.md"
        draft.write_text("# 合成初校稿\n\n**00:00**\n\n需要核对的合成原句。\n", encoding="utf-8")
        entry = {"id": "indexed-test", "title": "合成索引课次", "date": "2026-10-15", "audio_path": str(audio), "transcript_path": str(draft)}
        register({"course_id": "course-sample"}, [(entry, prepare(entry))], self.temp.name)
        return audio, draft, "/api/lectures/indexed-test"

    def test_indexed_audio_range_private_paths_and_sync(self):
        audio, draft, base = self.indexed()
        code, public, _ = self.call("GET", base)
        self.assertEqual(code, 200)
        self.assertNotIn(self.temp.name, json.dumps(public))
        self.assertNotIn("local_sources", public)
        self.assertEqual(len(public["source_files"]), 2)
        code, content, headers = self.call("GET", base + "/audio", headers={"Range": "bytes=4-14"})
        self.assertEqual(code, 206)
        self.assertEqual(content, audio.read_bytes()[4:15])
        self.assertIn("Content-Range", headers)
        self.assertEqual(self.call("POST", base + "/sources/sync", {})[0], 200)
        self.call("PUT", base, {"local_sources": {"audio": {"path": "/etc/passwd"}}})
        self.assertEqual(self.server.store.get("indexed-test")["local_sources"]["audio"]["path"], str(audio.resolve()))

    def test_denoised_audio_range_does_not_replace_original(self):
        audio, _, base = self.indexed()
        directory = self.server.store.root / "processed"
        directory.mkdir()
        path = directory / "test-clean.m4a"
        path.write_bytes(b"SYNTHETIC_DENOISED_AUDIO")
        self.server.store.mutate("indexed-test", lambda item: item.update(audio_derivatives={"denoised": {
            "storage_name": path.name, "source_fingerprint": fingerprint(audio), "profile": "voice-light-v1", "generated_at": "test"}}))
        code, public, _ = self.call("GET", base)
        self.assertEqual(code, 200)
        self.assertTrue(public["audio_versions"][1]["available"])
        self.assertNotIn("audio_derivatives", public)
        code, content, headers = self.call("GET", base + "/audio?version=denoised", headers={"Range": "bytes=2-10"})
        self.assertEqual(code, 206)
        self.assertEqual(content, path.read_bytes()[2:11])
        self.assertEqual(headers["Content-Type"], "audio/mp4")
        code, original, _ = self.call("GET", base + "/audio", headers={"Range": "bytes=2-10"})
        self.assertEqual(code, 206)
        self.assertEqual(original, audio.read_bytes()[2:11])
        self.assertEqual(self.call("GET", base + "/audio?version=../../bad")[0], 400)

    def test_indexed_source_change_blocks_generation_then_archives_on_explicit_sync(self):
        _, draft, base = self.indexed()
        self.assertEqual(self.call("POST", base + "/notes/generate", {"mode": "local"})[0], 200)
        draft.write_text("# 合成初校稿\n\n**00:00**\n\n改动后的原句。\n", encoding="utf-8")
        self.assertEqual(self.call("POST", base + "/notes/generate", {"mode": "local", "replace": True})[0], 409)
        self.assertEqual(self.call("POST", base + "/sources/sync", {})[0], 400)
        code, public, _ = self.call("POST", base + "/sources/sync", {"confirm_replace_transcript": True})
        self.assertEqual(code, 200, public)
        self.assertEqual(public["notes"], [])
        self.assertEqual(len(public["deleted_notes"]), 1)
        self.assertIn("改动后的原句", public["segments"][0]["text"])

    def test_import_requires_replace_and_preserves_original(self):
        item = self.imported()
        path = f"/api/lectures/{item['id']}/transcript"
        self.assertEqual(self.call("POST", path, {"text": "新的原文", "format": "txt"})[0], 409)
        status, replaced, _ = self.call("POST", path, {"text": "新的原文", "format": "txt", "replace": True})
        self.assertEqual(status, 200)
        self.assertEqual(replaced["original_transcript"], "新的原文")
        self.assertIsNone(replaced["segments"][0]["start"])
        self.assertGreaterEqual(self.call("GET", f"/api/lectures/{item['id']}/export?format=srt")[0], 400)

    def test_segment_edits_invalidate_verified_notes(self):
        item = self.imported()
        base = f"/api/lectures/{item['id']}"
        _, item, _ = self.call("POST", base + "/notes/generate", {"mode": "local"})
        note, segment = item["notes"][0], item["segments"][0]
        self.call("PUT", base + "/notes/" + note["id"], {"review_status": "verified"})
        _, item, _ = self.call("PUT", base + "/segments/" + segment["id"], {"text": "人工修订：观察不等于解释。"})
        self.assertEqual(item["segments"][0]["original_text"], segment["original_text"])
        self.assertEqual(item["notes"][0]["review_status"], "needs_review")

    def test_manual_note_refs_and_user_edits(self):
        item = self.imported()
        base = f"/api/lectures/{item['id']}"
        note = {"category": "question", "title": "测试问题", "content": "什么是解释？", "source_ids": ["fake"]}
        self.assertEqual(self.call("POST", base + "/notes", note)[0], 400)
        note["source_ids"] = [item["segments"][0]["id"]]
        status, item, _ = self.call("POST", base + "/notes", note)
        self.assertEqual(status, 200)
        self.assertTrue(item["notes"][0]["user_edited"])
        self.assertEqual(self.call("POST", base + "/notes/generate", {"mode": "local"})[0], 409)

    def test_secrets_private_and_key_preservation(self):
        sentinel = "fake-test-api-key-never-real"
        body = {"llm": {"base_url": "https://example.invalid/v1", "model": "fictional", "api_key": sentinel}}
        status, settings, _ = self.call("PUT", "/api/settings", body)
        self.assertEqual(status, 200)
        self.assertTrue(settings["llm"]["configured"])
        self.assertNotIn(sentinel, json.dumps(settings))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((Path(self.temp.name) / "settings.json").stat().st_mode), 0o600)
        self.call("PUT", "/api/settings", {"llm": {"api_key": ""}})
        self.assertEqual(self.server.store.private_settings()["llm"]["api_key"], sentinel)
        self.call("PUT", "/api/settings", {"llm": {"clear_key": True}})
        self.assertEqual(self.server.store.private_settings()["llm"]["api_key"], "")
        self.assertNotIn(sentinel, json.dumps(self.call("GET", "/api/state")[1]))

    def test_no_network_without_explicit_action_consent(self):
        item = self.imported()
        with patch("core.pipeline.generate_llm_notes") as generate:
            status, _, _ = self.call("POST", f"/api/lectures/{item['id']}/notes/generate", {"mode": "llm", "allow_external": False})
            self.assertEqual(status, 400)
            generate.assert_not_called()
        with patch("core.pipeline.transcribe_audio") as transcribe:
            self.assertEqual(self.call("POST", f"/api/lectures/{item['id']}/transcribe", {})[0], 400)
            transcribe.assert_not_called()

    def test_audio_round_trip_ranges_unique_names_and_replace(self):
        item = self.lecture()
        path = f"/api/lectures/{item['id']}/audio"
        status, item, _ = self.call("POST", path, raw=b"0123456789", headers={"Content-Type": "audio/wav", "X-Filename": "../../example.wav"})
        self.assertEqual(status, 200)
        self.assertEqual(item["audio"]["name"], "example.wav")
        self.assertNotIn("storage_name", item["audio"])
        stored = list((Path(self.temp.name) / "audio").iterdir())
        self.assertEqual(len(stored), 1)
        self.assertNotEqual(stored[0].name, "example.wav")
        status, data, headers = self.call("GET", path, headers={"Range": "bytes=2-4"})
        self.assertEqual(status, 206)
        self.assertEqual(data, b"234")
        self.assertEqual(headers["Content-Range"], "bytes 2-4/10")
        self.assertEqual(self.call("GET", path, headers={"Range": "bytes=30-40"})[0], 416)
        self.assertEqual(self.call("POST", path, raw=b"new", headers={"Content-Type": "audio/wav"})[0], 409)
        self.assertEqual(self.call("POST", path + "?replace=1", raw=b"new", headers={"Content-Type": "audio/wav"})[0], 200)

    def test_security_boundaries_and_json_limits(self):
        for headers in [{"Origin": "https://malicious.example"}, {"Host": "attacker.example"}, {"Sec-Fetch-Site": "cross-site"}]:
            self.assertEqual(self.call("GET", "/api/state", headers=headers)[0], 403)
        for path in ["/../store.py", "/%2e%2e/store.py", "/.runtime/settings.json", "/static/../app.py"]:
            self.assertEqual(self.call("GET", path)[0], 404)
        self.assertEqual(self.call("POST", "/api/demo", raw=b"{}", headers={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.call("POST", "/api/demo", raw=b"{}", headers={"Content-Type": "application/json", "Content-Length": str(9 * 1024 * 1024)})[0], 413)

    def test_qta_upload_preserves_original_and_accepts_quicktime_mime(self):
        def box(kind, content):
            return struct.pack(">I4s", len(content) + 8, kind) + content
        header = b"\0\0\0\0" + struct.pack(">IIII", 0, 0, 1000, 12345) + b"\0" * 20
        raw = box(b"ftyp", b"qt  \0\0\0\0qt  ") + box(b"mdat", b"synthetic-audio") + box(b"moov", box(b"mvhd", header))
        item = self.lecture()
        path = f"/api/lectures/{item['id']}/audio"
        for name, mime in [("phone.qta", "video/quicktime"), ("phone.QTA", "audio/x-qta"), ("phone.qat", "application/octet-stream")]:
            status, result, _ = self.call("POST", path + "?replace=1", raw=raw, headers={"Content-Type": mime, "X-Filename": name})
            self.assertEqual(status, 200, result)
            self.assertEqual(result["audio"]["name"], name)
            self.assertEqual(result["audio"]["mime"], "audio/mp4")
            saved = self.server.store.audio_path(self.server.store.get(item["id"]))
            self.assertEqual(saved.suffix, Path(name).suffix.lower())
            self.assertEqual(saved.read_bytes(), raw)
            status, content, headers = self.call("GET", path, headers={"Range": "bytes=0-19"})
            self.assertEqual(status, 206)
            self.assertEqual(content, raw[:20])
            self.assertEqual(headers["Content-Type"], "audio/mp4")

    def test_invalid_qta_does_not_replace_existing_audio_or_accept_html(self):
        item = self.lecture()
        path = f"/api/lectures/{item['id']}/audio"
        self.call("POST", path, raw=b"original-wav", headers={"Content-Type": "audio/wav", "X-Filename": "original.wav"})
        for mime, content in [("video/quicktime", b"not-a-quicktime-container"), ("text/html", b"<html>not audio</html>")]:
            status, result, _ = self.call("POST", path + "?replace=1", raw=content, headers={"Content-Type": mime, "X-Filename": "wrong.qta"})
            self.assertEqual(status, 415, result)
        stored = list(self.server.store.audio_dir.iterdir())
        self.assertEqual(len(stored), 1)
        self.assertEqual(self.call("GET", path)[1], b"original-wav")
        self.assertEqual(self.server.store.get(item["id"])["audio"]["name"], "original.wav")

    def test_restart_persistence_and_private_exports(self):
        item = self.imported()
        other_store = Store(self.temp.name)
        self.assertEqual(other_store.get(item["id"])["segments"], item["segments"])
        for kind in ["md", "json", "txt", "srt"]:
            status, data, headers = self.call("GET", f"/api/lectures/{item['id']}/export?format={kind}")
            self.assertEqual(status, 200, data)
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertNotIn("settings.json", str(data))

    def test_note_removal_is_recoverable(self):
        item = self.imported()
        base = f"/api/lectures/{item['id']}"
        _, item, _ = self.call("POST", base + "/notes/generate", {"mode": "local"})
        original = item["notes"][0]
        status, item, _ = self.call("DELETE", base + "/notes/" + original["id"])
        self.assertEqual(status, 200, item)
        self.assertEqual(item["notes"], [])
        self.assertEqual(item["deleted_notes"][0]["content"], original["content"])
        self.assertTrue(item["deleted_notes"][0]["deleted_at"])
        status, item, _ = self.call("POST", base + "/notes/restore", {"note_id": original["id"]})
        self.assertEqual(status, 200, item)
        self.assertEqual(item["notes"][0]["content"], original["content"])
        self.assertEqual(item["notes"][0]["review_status"], "needs_review")
        self.assertEqual(item["deleted_notes"], [])
        self.assertNotIn("source_snapshot", item["notes"][0])
        self.assertNotIn("deleted_at", item["notes"][0])

    def test_archive_does_not_reattach_to_replaced_same_source_id(self):
        item = self.imported()
        base = f"/api/lectures/{item['id']}"
        _, item, _ = self.call("POST", base + "/notes/generate", {"mode": "local"})
        original = item["notes"][0]
        original_source = item["segments"][0]
        _, item, _ = self.call("DELETE", base + "/notes/" + original["id"])
        snapshot = item["deleted_notes"][0]["source_snapshot"]
        self.assertEqual(snapshot[original_source["id"]]["text"], original_source["text"])
        code, item, _ = self.call("POST", base + "/transcript", {
            "text": "1\n00:00:00,000 --> 00:00:10,000\n不同的虚构课堂材料。\n", "format": "srt", "replace": True,
        })
        self.assertEqual(code, 200, item)
        self.assertEqual(item["segments"][0]["id"], original_source["id"])
        code, error, _ = self.call("POST", base + "/notes/restore", {"note_id": original["id"]})
        self.assertEqual(code, 409, error)
        self.assertIn("原文", error["error"])
        _, item, _ = self.call("GET", base)
        self.assertEqual(item["notes"], [])
        self.assertEqual(item["deleted_notes"][0]["source_snapshot"], snapshot)
        _, exported, _ = self.call("GET", base + "/export?format=json")
        self.assertEqual(exported["deleted_notes"][0]["source_snapshot"], snapshot)

    def test_glossary_total_serialized_limit(self):
        entries = [{"term": "术语" + str(i), "meaning": "释义" * 900} for i in range(12)]
        code, result, _ = self.call("PUT", "/api/settings", {"glossary": entries})
        self.assertEqual(code, 400, result)
        self.assertIn("20000", result["error"])
        self.assertEqual(self.server.store.public_settings()["glossary"], [])


if __name__ == "__main__":
    unittest.main()
