"""Optional worker state handling, without loading a real model."""
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from core.workflow import digest
from audio_processing import fingerprint
from core.asr_guard import VERSION

from local_transcription import Jobs, checked_config, configuration
from store import Store


class FakeProcess:
    def __init__(self, *_args, **_kwargs):
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(json.dumps({"kind": "init", "duration": 1}) + "\n" + json.dumps({"kind": "chunk", "index": 0, "result": {"segments": [{"start": 0, "end": 1, "text": "合成识别"}], "issues": [], "attempts": 1}}) + "\n" + json.dumps({"kind": "complete"}) + "\n")
        self.returncode = 0
    def wait(self, timeout=None):
        return self.returncode
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = -15


class LocalTranscriptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lecture-local-asr-")
        self.store = Store(self.temp.name)
        self.item = self.store.create("course-sample", "合成转写", "2026-10-17")
        audio = self.store.audio_dir / "synthetic.wav"
        audio.write_bytes(b"fake-local-asr-audio")
        self.store.mutate(self.item["id"], lambda row: row.update(audio={"storage_name": audio.name, "name": audio.name, "mime": "audio/wav", "size": audio.stat().st_size}))
        self.jobs = Jobs(self.store)
        self.config = {"model_path": self.temp.name, "python_path": sys.executable, "language": "auto"}
    def tearDown(self):
        self.jobs.close()
        self.temp.cleanup()

    def run_worker(self, process=FakeProcess):
        job = {"id": "synthetic-job", "lecture_id": self.item["id"], "status": "queued", "progress": 0, "message": "", "cancel": threading.Event()}
        from core.workflow import digest
        from audio_processing import fingerprint
        item = self.store.get(self.item["id"])
        path = self.store.audio_path(item)
        self.jobs.jobs[job["id"]] = job
        with patch("local_transcription.subprocess.Popen", process):
            self.jobs._run(job, path, self.config, fingerprint(path), digest([item["segments"], item["notes"], item["audio"]]), False)
        return job

    def test_success_keeps_unreviewed_and_no_cloud(self):
        job = self.run_worker()
        self.assertEqual(job["status"], "completed", job)
        item = self.store.get(self.item["id"])
        self.assertEqual(item["segments"][0]["text"], "合成识别")
        self.assertEqual(item["segments"][0]["review_status"], "unreviewed")
        self.assertEqual(item["transcript_source"]["provider"], "local")
        self.assertNotIn("cancel", self.jobs.get(self.item["id"]))

    def test_incomplete_worker_does_not_write(self):
        class Incomplete(FakeProcess):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.stdout = io.StringIO('{"kind":"init","duration":60}\n')
        job = self.run_worker(Incomplete)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.store.get(self.item["id"])["segments"], [])

    def test_cancel_before_start_does_not_launch(self):
        from core.workflow import digest
        from audio_processing import fingerprint
        item = self.store.get(self.item["id"])
        event = threading.Event(); event.set()
        job = {"status": "queued", "cancel": event}
        path = self.store.audio_path(item)
        with patch("local_transcription.subprocess.Popen") as process:
            self.jobs._run(job, path, self.config, fingerprint(path), digest([item["segments"], item["notes"], item["audio"]]), False)
            process.assert_not_called()
        self.assertEqual(job["status"], "cancelled")

    def test_existing_transcript_is_not_overwritten_without_confirmation(self):
        with patch("local_transcription.checked_config", return_value=self.config), patch("local_transcription.shutil.which", return_value="/fake/ffmpeg"):
            self.store.mutate(self.item["id"], lambda row: row.update(segments=[{"text": "手工稿"}]))
            with self.assertRaisesRegex(ValueError, "确认替换"):
                self.jobs.start(self.item["id"], self.config)

    def test_no_remote_model_and_no_extra_command_arguments(self):
        with self.assertRaises(ValueError):
            checked_config({"model_path": "remote/model"})
        with self.assertRaises(ValueError):
            checked_config({"model_path": self.temp.name, "python_path": "/bin/zsh"})
        with self.assertRaises(ValueError):
            configuration({"language": "invalid"})
        with self.assertRaises(ValueError):
            configuration({"model_path": "bad\npath"})
        self.assertEqual(configuration({"language": "de"})["language"], "de")

    def test_checkpoint_survives_failure_then_resume_skips_good_chunks(self):
        key = "a" * 64
        first = {"segments": [{"start": 0, "end": 60, "text": "第一段已经完成的合成内容"}], "issues": [], "attempts": 1}
        second = {"segments": [{"start": 60, "end": 120, "text": "第二段恢复后的合成内容"}], "issues": [], "attempts": 1}
        def process_for(events):
            class Process(FakeProcess):
                def __init__(self, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.stdout = io.StringIO("\n".join(json.dumps(row) for row in events) + "\n")
            return Process
        item = self.store.get(self.item["id"])
        path = self.store.audio_path(item)
        snapshot = digest([item["segments"], item["notes"], item["audio"]])
        job = {"id": "first", "lecture_id": item["id"], "status": "queued", "progress": 0, "message": "", "cancel": threading.Event()}
        with patch("local_transcription.subprocess.Popen", process_for([{"kind": "init", "duration": 120}, {"kind": "chunk", "index": 0, "result": first}])):
            self.jobs._run(job, path, self.config, fingerprint(path), snapshot, False, key)
        self.assertEqual(job["status"], "failed")
        self.assertEqual(self.store.get(item["id"])["segments"], [])
        saved = self.jobs.checkpoints.load(key)
        self.assertIn("0", saved["chunks"])
        restarted = Jobs(self.store)
        self.assertTrue(restarted.get(item["id"])["resume_available"])
        job2 = {**job, "id": "resume", "status": "queued", "resumed_chunks": 1, "cancel": threading.Event()}
        with patch("local_transcription.subprocess.Popen", process_for([{"kind": "init", "duration": 120}, {"kind": "chunk", "index": 1, "result": second}, {"kind": "complete"}])):
            restarted._run(job2, path, self.config, fingerprint(path), snapshot, False, key, saved)
        self.assertEqual(job2["status"], "completed", job2)
        result = self.store.get(item["id"])
        self.assertEqual([row["text"] for row in result["segments"]], [first["segments"][0]["text"], second["segments"][0]["text"]])
        self.assertEqual(result["asr_report"]["resumed_chunks"], 1)

    def test_unresolved_gap_has_distinct_status_and_not_verified(self):
        class WithGap(FakeProcess):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.stdout = io.StringIO("\n".join(json.dumps(row) for row in [
                    {"kind": "init", "duration": 60},
                    {"kind": "chunk", "index": 0, "result": {"segments": [], "issues": [{"start": 0, "end": 60, "reasons": ["疑似循环"]}], "attempts": 3}},
                    {"kind": "complete"}]) + "\n")
        job = self.run_worker(WithGap)
        self.assertEqual(job["status"], "completed_with_warnings")
        self.assertEqual(job["processed_chunks"],1)
        self.assertEqual(job["completed_chunks"],0)
        item = self.store.get(self.item["id"])
        self.assertTrue(item["segments"][0]["asr_issue"])
        self.assertEqual(item["segments"][0]["review_status"], "needs_review")
        self.assertFalse(item["asr_report"]["complete_without_detected_issues"])

    def test_no_progress_watchdog_does_not_wait_forever(self):
        class BlockedStream:
            def __iter__(self):
                threading.Event().wait(.7)
                return iter(())
            def close(self):
                pass
        class Hung(FakeProcess):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.stdout = BlockedStream()
        with patch("local_transcription.WINDOW_TIMEOUT", .01):
            job = self.run_worker(Hung)
        self.assertEqual(job["status"], "failed")
        self.assertIn("长时间无进展", job["message"])
        self.assertEqual(self.store.get(self.item["id"])["segments"], [])

    def test_restarted_running_job_is_interrupted_not_still_running(self):
        self.store.mutate(self.item["id"], lambda row: row.update(local_asr_state={"id": "old", "lecture_id": row["id"], "status": "running", "resume_available": True}))
        self.assertEqual(Jobs(self.store).get(self.item["id"])["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
