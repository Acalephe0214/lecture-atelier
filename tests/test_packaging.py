"""Friend ZIP privacy, checksums and clean-copy startup. No model downloads."""
import hashlib
import http.client
import json
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest.mock import patch

from package_for_friends import build, FILES


class FriendPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lecture-friend-test-")
        self.root = Path(self.temp.name).resolve()
        self.zip = build(self.root / "friend.zip")

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_allowlist_checksums_and_private_files_excluded(self):
        with zipfile.ZipFile(self.zip) as archive:
            names = archive.namelist()
            self.assertEqual(set(names), {"LectureAtelier/"+name for name in FILES} | {"LectureAtelier/SHA256SUMS.txt"})
            self.assertFalse(any(part in name.split("/") for name in names for part in (".runtime", ".venv", "models", "test-results", ".git")))
            self.assertNotIn("LectureAtelier/README.md",names)
            self.assertFalse(any(name.startswith("LectureAtelier/examples/") for name in names))
            self.assertEqual(archive.getinfo("LectureAtelier/launch.command").external_attr >> 16 & 0o777, 0o755)
            self.assertEqual(archive.getinfo("LectureAtelier/setup-mac.command").external_attr >> 16 & 0o777, 0o755)
            self.assertIn("LectureAtelier/AGENTS.md",names)
            self.assertIn("LectureAtelier/CODEX_SETUP.md",names)
            self.assertIn("LectureAtelier/START-HERE.html",names)
            for line in archive.read("LectureAtelier/SHA256SUMS.txt").decode().splitlines():
                digest, name = line.split("  ",1)
                self.assertEqual(digest, hashlib.sha256(archive.read("LectureAtelier/"+name)).hexdigest())
            for name in names:
                body = archive.read(name)
                self.assertNotIn(("/"+"Users/"+"example-author/").encode(), body)
                for title in ("知觉现象学", "民主的历史与现实", "政治哲学", "西方政治思想"):
                    self.assertNotIn(title.encode(), body)

    def test_existing_archive_is_not_overwritten(self):
        before = self.zip.read_bytes()
        with self.assertRaises(FileExistsError): build(self.zip)
        self.assertEqual(self.zip.read_bytes(),before)

    def test_unlisted_private_file_and_symlink_never_packed(self):
        fake = self.root / "fake"; fake.mkdir()
        for name in FILES:
            target = fake / name; target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text("synthetic public source")
        runtime = fake / ".runtime"; runtime.mkdir()
        (runtime / "settings.json").write_text('{"api_key":"synthetic-private-test"}')
        (fake / "secret.txt").write_text("synthetic-private-test")
        with patch("package_for_friends.ROOT",fake):
            output = build(self.root / "clean.zip")
            with zipfile.ZipFile(output) as archive:
                self.assertFalse(any(b"synthetic-private-test" in archive.read(name) for name in archive.namelist()))
            public = fake / FILES[0]
            public.unlink(); public.symlink_to(fake / "secret.txt")
            with self.assertRaises(ValueError): build(self.root / "bad-link.zip")

    def test_known_private_marker_fails_before_creating_zip(self):
        fake = self.root / "fake"; fake.mkdir()
        (fake / "app.py").write_text('path="'+"/"+"Users/"+"example-author/private"+'"')
        with patch("package_for_friends.ROOT",fake), patch("package_for_friends.FILES",("app.py",)):
            with self.assertRaises(ValueError): build(self.root / "must-not-exist.zip")
        self.assertFalse((self.root / "must-not-exist.zip").exists())

    def test_extracted_clean_app_runs_without_author_settings_and_stops_on_sigint(self):
        with zipfile.ZipFile(self.zip) as archive: archive.extractall(self.root / "unpacked")
        project = self.root / "unpacked" / "LectureAtelier"
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0)); port = sock.getsockname()[1]
        process = subprocess.Popen([sys.executable,"-u","app.py","--port",str(port)], cwd=project,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,text=True)
        log = ""
        try:
            payload = None
            deadline = time.monotonic()+15
            while time.monotonic() < deadline:
                client = http.client.HTTPConnection("127.0.0.1",port,timeout=.5)
                try:
                    client.request("GET","/api/state")
                    response = client.getresponse()
                    if response.status == 200:
                        payload = json.loads(response.read()); break
                except OSError:
                    pass
                finally:
                    client.close()
                if process.poll() is not None: break
                time.sleep(.05)
            self.assertIsNotNone(payload,"Clean-copy server did not start")
            self.assertEqual(payload["lectures"],[])
            self.assertEqual([(row["id"], row["name"]) for row in payload["courses"]],[("course-sample","示例课程")])
            self.assertFalse(payload["settings"]["local_asr"]["configured"])
            for service in ("llm","asr"):
                self.assertFalse(payload["settings"][service]["configured"])
                self.assertNotIn("api_key",payload["settings"][service])
            process.send_signal(signal.SIGINT)
            log,_ = process.communicate(timeout=8)
            self.assertEqual(process.returncode,0,log)
            self.assertIn("已停止",log)
        finally:
            if process.poll() is None:
                process.terminate()
                try: process.communicate(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.communicate(timeout=5)


if __name__ == "__main__": unittest.main()
