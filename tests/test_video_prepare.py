"""Synthetic video/PCM only; no model, cloud API or private recordings."""
from copy import deepcopy
import hashlib
import array
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave

from core import audio_prepare, workflow
from audio_processing import fingerprint
from local_transcription import Jobs
from store import Store
from test_local_transcription import FakeProcess


def write_wav(path):
    with wave.open(str(path), "wb") as handle:
        handle.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        handle.writeframes(b"\0\0" * 16000)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "synthetic.mp4"
        self.source.write_bytes(b"fake-video")
    def tearDown(self):
        self.temp.cleanup()

    def test_regular_audio_does_not_convert(self):
        with patch("core.audio_prepare.subprocess.Popen") as process:
            path, info = audio_prepare.prepare(self.root / "recording.mp3", self.root)
        self.assertFalse(info["converted"])
        process.assert_not_called()

    def test_cached_valid_wav_is_reused_without_ffmpeg_and_source_change_invalidates(self):
        path = audio_prepare._path(self.source, self.root)
        path.parent.mkdir()
        write_wav(path)
        with patch("core.audio_prepare.subprocess.Popen") as process:
            result, info = audio_prepare.prepare(self.source, self.root)
        self.assertEqual(result, path)
        self.assertTrue(info["cached"])
        process.assert_not_called()
        self.source.write_bytes(b"changed-video")
        self.assertIsNone(audio_prepare.cached(self.source, self.root))

    def test_corrupt_or_symlink_cache_is_not_used(self):
        path = audio_prepare._path(self.source, self.root)
        path.parent.mkdir()
        path.write_bytes(b"invalid-wav")
        self.assertIsNone(audio_prepare.cached(self.source, self.root))
        path.unlink()
        path.symlink_to(self.source)
        with self.assertRaises(ValueError):
            audio_prepare.cached(self.source, self.root)

    def test_missing_ffmpeg_and_cancellation_do_not_start_inference(self):
        with patch("core.local_engine.media_program", return_value=None):
            with self.assertRaisesRegex(ValueError, "FFmpeg"):
                audio_prepare.prepare(self.source, self.root)
        cancel = threading.Event(); cancel.set()
        with patch("core.audio_prepare.subprocess.Popen") as process:
            with self.assertRaisesRegex(ValueError, "取消"):
                audio_prepare.prepare(self.source, self.root, cancel=cancel)
            process.assert_not_called()

    def test_low_disk_space_stops_before_conversion(self):
        with patch("audio_processing.media_duration", return_value=100), patch("core.audio_prepare.shutil.disk_usage", return_value=type("Disk", (), {"free": 0})()):
            with self.assertRaisesRegex(ValueError, "磁盘空间不足"):
                audio_prepare.prepare(self.source, self.root, ffmpeg="synthetic")
        self.assertFalse(list((self.root / "asr-audio").glob(".preparing-*")))


class RealVideoTests(unittest.TestCase):
    def setUp(self):
        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            self.skipTest("FFmpeg not available for synthetic integration test")
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        if hasattr(self, "temp"):
            self.temp.cleanup()

    def make_video(self, audio=True):
        path = self.root / ("with-audio.mp4" if audio else "no-audio.mp4")
        args = [self.ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=32x32:r=10:d=2"]
        if audio:
            args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2", "-c:a", "aac"]
        args += ["-c:v", "mpeg4", "-t", "2", str(path)]
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=20)
        return path

    def test_real_video_extracts_16k_mono_once_without_changing_original(self):
        source = self.make_video()
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        progress = []
        path, info = audio_prepare.prepare(source, self.root, ffmpeg=self.ffmpeg, on_progress=progress.append)
        self.assertTrue(info["converted"])
        self.assertFalse(info["cached"])
        with wave.open(str(path), "rb") as audio:
            self.assertEqual((audio.getnchannels(), audio.getsampwidth(), audio.getframerate()), (1, 2, 16000))
            self.assertAlmostEqual(audio.getnframes() / 16000, 2, delta=.15)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        with patch("core.audio_prepare.subprocess.Popen") as process:
            reused, info = audio_prepare.prepare(source, self.root)
        self.assertEqual(reused, path)
        self.assertTrue(info["cached"])
        process.assert_not_called()
        self.assertEqual(progress[-1], 100)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_video_without_audio_fails_cleanly_and_removes_only_new_temp(self):
        source = self.make_video(False)
        before = source.read_bytes()
        with self.assertRaisesRegex(ValueError, "音轨"):
            audio_prepare.prepare(source, self.root, ffmpeg=self.ffmpeg)
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(list((self.root / "asr-audio").glob("*.wav")))

    def test_audio_start_offset_is_preserved_as_leading_silence(self):
        source = self.root / "delayed-audio.mp4"
        subprocess.run([self.ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "color=c=black:s=32x32:r=10:d=2", "-itsoffset", "0.5", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:v", "mpeg4", "-c:a", "aac", "-t", "2", str(source)], check=True, stderr=subprocess.PIPE, timeout=20)
        path, _ = audio_prepare.prepare(source, self.root, ffmpeg=self.ffmpeg)
        with wave.open(str(path), "rb") as audio:
            values = array.array("h", audio.readframes(audio.getnframes()))
        if sys.byteorder != "little":
            values.byteswap()
        self.assertTrue(all(abs(x) < 5 for x in values[:int(.3 * 16000)]))
        self.assertTrue(any(abs(x) > 100 for x in values[int(.6 * 16000):]))


class VideoJobTests(unittest.TestCase):
    def test_prepare_happens_before_worker_and_worker_gets_wav_not_video(self):
        with tempfile.TemporaryDirectory() as folder:
            store = Store(folder)
            item = store.create("course-sample", "合成视频课次", "2026-10-18")
            source = store.audio_dir / "synthetic.mp4"; source.write_bytes(b"video-original")
            item = store.mutate(item["id"], lambda row: row.update(audio={"storage_name": source.name, "name": source.name, "mime": "video/mp4"}))
            wav = Path(folder) / "prepared.wav"; write_wav(wav)
            job = {"id": "synthetic-video-job", "lecture_id": item["id"], "status": "queued", "progress": 0, "message": "", "cancel": threading.Event()}
            jobs = Jobs(store); jobs.jobs[job["id"]] = job
            order, workers = [], []
            def prepare(*args, **kwargs):
                order.append("prepare")
                kwargs["on_progress"](50)
                return wav, {"converted": True, "cached": False, "format": "WAV", "sample_rate": 16000, "channels": 1}
            class Captured(FakeProcess):
                def __init__(self, *args, **kwargs):
                    order.append("worker")
                    super().__init__(*args, **kwargs)
                    class Input(io.StringIO):
                        def close(self):
                            workers.append(json.loads(self.getvalue()))
                            super().close()
                    self.stdin = Input()
            snapshot = workflow.digest([item["segments"], item["notes"], item["audio"]])
            try:
                with patch("core.audio_prepare.prepare", side_effect=prepare), patch("local_transcription.subprocess.Popen", Captured):
                    jobs._run(job, source, {"python_path": sys.executable}, fingerprint(source), snapshot, False)
                self.assertEqual(job["status"], "completed", job)
                self.assertEqual(order, ["prepare", "worker"])
                self.assertEqual(workers[0]["audio_path"], str(wav))
                self.assertEqual(store.audio_path(store.get(item["id"])), source)
                self.assertNotIn(str(wav), json.dumps(jobs.public(job)))
            finally:
                jobs.close()
