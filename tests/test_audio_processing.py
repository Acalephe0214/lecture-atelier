from pathlib import Path
import hashlib
import shutil
import tempfile
import time
import unittest
import wave
from unittest.mock import patch

from audio_processing import fingerprint, processed_path, public_versions, generate, DenoiseJobs, media_duration
from local_sources import LocalSourceError
from store import Store


class ProcessedAudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)
        self.item = self.store.create("course-sample", "合成试听课", "2026-10-17")
        self.original = self.store.audio_dir / "original.m4a"
        self.original.write_bytes(b"original-synthetic-recording")
        self.item["audio"] = {"name": "原音.m4a", "mime": "audio/mp4", "size": self.original.stat().st_size, "storage_name": self.original.name}
        directory = self.store.root / "processed"
        directory.mkdir()
        self.processed = directory / "clean.m4a"
        self.processed.write_bytes(b"different-synthetic-denoised-recording")
        self.item["audio_derivatives"] = {"denoised": {"storage_name": self.processed.name,
            "source_fingerprint": fingerprint(self.original), "profile": "voice-light-v1", "generated_at": "test-revision"}}

    def tearDown(self):
        self.temp.cleanup()

    def test_versions_are_separate_and_original_is_unchanged(self):
        before = self.original.read_bytes()
        self.assertEqual(processed_path(self.store, self.item, "denoised"), self.processed.resolve())
        self.assertNotEqual(self.store.audio_path(self.item), self.processed)
        versions = public_versions(self.store, self.item)
        self.assertEqual([version["id"] for version in versions], ["original", "denoised"])
        self.assertIn("version=denoised", versions[1]["url"])
        self.assertEqual(self.original.read_bytes(), before)

    def test_qta_duration_uses_header_parser_without_ffprobe(self):
        with patch("audio_processing.audio_metadata", return_value={"duration": 12.345}) as metadata, patch("audio_processing.subprocess.check_output") as process:
            self.assertEqual(media_duration(Path("phone.qta")), 12.345)
            self.assertEqual(media_duration(Path("phone.qat")), 12.345)
            self.assertEqual(metadata.call_count, 2)
            process.assert_not_called()

    def test_private_cache_details_are_not_exported(self):
        public = self.store.public_lecture(self.item)
        self.assertNotIn("audio_derivatives", public)
        self.assertNotIn("storage_name", public["audio"])
        self.assertNotIn("source_fingerprint", str(public))
        self.assertNotIn(str(self.store.root), str(public))

    def test_source_change_invalidates_cached_denoise(self):
        self.original.write_bytes(b"replaced-original")
        with self.assertRaises(LocalSourceError):
            processed_path(self.store, self.item, "denoised")
        self.assertFalse(public_versions(self.store, self.item)[1]["available"])

    def test_missing_cache_does_not_remove_original(self):
        self.processed.rename(self.processed.with_suffix(".moved"))
        self.assertFalse(public_versions(self.store, self.item)[1]["available"])
        self.assertTrue(self.store.audio_path(self.item).exists())

    def test_cache_cannot_escape_processed_directory(self):
        self.item["audio_derivatives"]["denoised"]["storage_name"] = "../original.m4a"
        with self.assertRaises(LocalSourceError):
            processed_path(self.store, self.item, "denoised")

    def test_symlink_to_external_file_rejected(self):
        external = self.store.root / "outside.m4a"
        external.write_bytes(b"not-a-cache")
        link = self.store.root / "processed" / "link.m4a"
        link.symlink_to(external)
        self.item["audio_derivatives"]["denoised"]["storage_name"] = link.name
        with self.assertRaises(LocalSourceError):
            processed_path(self.store, self.item, "denoised")

    def test_unknown_and_unavailable_versions_rejected(self):
        with self.assertRaises(LocalSourceError):
            processed_path(self.store, self.item, "../../other")
        self.item.pop("audio_derivatives")
        with self.assertRaises(LocalSourceError):
            processed_path(self.store, self.item, "denoised")
        self.assertEqual(len(public_versions(self.store, self.item)), 1)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg unavailable")
    def test_real_generation_never_changes_source_and_has_same_timeline(self):
        audio = self.store.audio_dir / "synthetic.wav"
        with wave.open(str(audio), "wb") as handle:
            handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
            handle.writeframes(b"\0\0" * 48000)
        self.store.mutate(self.item["id"], lambda row: row.update(audio={"name": audio.name, "mime": "audio/wav", "storage_name": audio.name, "size": audio.stat().st_size}))
        before = hashlib.sha256(audio.read_bytes()).hexdigest()
        progress = []
        result = generate(self.store, self.item["id"], on_progress=progress.append)
        self.assertEqual(result["status"], "generated")
        self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), before)
        self.assertAlmostEqual(media_duration(Path(result["path"])), 3, delta=.1)
        self.assertEqual(generate(self.store, self.item["id"])["status"], "cached")
        self.assertEqual(len(public_versions(self.store, self.store.get(self.item["id"]))), 2)
        keyboard = generate(self.store, self.item["id"], profile="keyboard")
        self.assertEqual(keyboard["profile"], "keyboard-declick-v1")
        self.assertAlmostEqual(media_duration(Path(keyboard["path"])), 3, delta=.1)
        self.assertEqual(hashlib.sha256(audio.read_bytes()).hexdigest(), before)
        self.assertEqual(len(public_versions(self.store, self.store.get(self.item["id"]))), 3)

    @patch("audio_processing.generate")
    def test_background_cache_job_is_bounded_and_reports_result(self, build):
        self.store.mutate(self.item["id"], lambda row: row.update(audio=self.item["audio"]))
        build.return_value = {"status": "cached"}
        jobs = DenoiseJobs(self.store)
        with patch("audio_processing.shutil.which", return_value="/fake/ffmpeg"):
            jobs.start(self.item["id"])
        deadline = time.monotonic() + 2
        while jobs.get(self.item["id"])["status"] == "running" and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(jobs.get(self.item["id"])["status"], "completed")
        jobs.close()


if __name__ == "__main__":
    unittest.main()
