"""Layered installation checks: temporary folders, no network or model inference."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, call

import bootstrap


class BootstrapProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lecture setup ")
        self.root = Path(self.temp.name).resolve()
        self.old_path = list(sys.path)
        self.stack = contextlib.ExitStack()
        for key, value in (("ROOT", self.root), ("VENDOR", self.root / ".portable/vendor"),
                           ("MODEL", self.root / "models/faster-whisper-small")):
            self.stack.enter_context(patch.object(bootstrap, key, value))
        self.stack.enter_context(patch.dict(os.environ))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def tearDown(self):
        self.stack.close()
        sys.path[:] = self.old_path
        self.temp.cleanup()

    def existing(self):
        settings = self.root / ".runtime/settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"local_asr": {"backend": "mlx", "model_path": "existing-local-model"},
                                       "llm": {"api_key": "synthetic-private-key"}}))
        return settings

    def test_basic_is_default_and_has_no_downloads_or_private_state(self):
        with patch.object(bootstrap, "install_component") as packages, \
             patch.object(bootstrap, "download_model") as model, \
             patch.object(bootstrap, "collect_licenses") as notices, \
             patch.object(bootstrap.subprocess, "run") as process:
            self.assertTrue(bootstrap.install())
        for mock in (packages, model, notices, process):
            mock.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_pdf_installs_no_speech_dependencies_or_models(self):
        with patch.object(bootstrap, "install_component") as install, \
             patch.object(bootstrap, "download_model") as model, \
             patch.object(bootstrap, "collect_licenses") as notices:
            self.assertTrue(bootstrap.install("pdf"))
        install.assert_called_once_with("pdf")
        model.assert_not_called()
        notices.assert_called_once()
        self.assertFalse((self.root / "models").exists())
        self.assertFalse((self.root / ".runtime").exists())

    def test_speech_does_not_install_pdf(self):
        with patch.object(bootstrap, "install_component") as install, \
             patch.object(bootstrap, "download_model", return_value=True) as model, \
             patch.object(bootstrap, "collect_licenses"):
            self.assertTrue(bootstrap.install("speech"))
        install.assert_called_once_with("speech")
        model.assert_called_once()

    def test_full_selects_both_components(self):
        with patch.object(bootstrap, "install_component") as install, \
             patch.object(bootstrap, "download_model", return_value=True), \
             patch.object(bootstrap, "collect_licenses"):
            self.assertTrue(bootstrap.install("full"))
        self.assertEqual(install.call_args_list, [call("pdf"), call("speech")])

    def test_existing_backend_prevents_replacement_download_and_preserves_keys(self):
        settings = self.existing()
        before = settings.read_bytes()
        with patch.object(bootstrap, "install_component") as install, \
             patch.object(bootstrap, "download_model") as model:
            self.assertTrue(bootstrap.install("speech"))
        install.assert_not_called()
        model.assert_not_called()
        self.assertEqual(settings.read_bytes(), before)
        self.assertFalse((self.root / ".portable").exists())

    def test_full_reuses_existing_speech_and_only_installs_pdf(self):
        self.existing()
        with patch.object(bootstrap, "install_component") as install, \
             patch.object(bootstrap, "download_model") as model, \
             patch.object(bootstrap, "collect_licenses"):
            self.assertTrue(bootstrap.install("full"))
        install.assert_called_once_with("pdf")
        model.assert_not_called()

    def test_corrupt_existing_settings_are_never_reset(self):
        settings = self.existing()
        settings.write_text("{invalid")
        with patch.object(bootstrap, "download_model") as model:
            with self.assertRaisesRegex(ValueError, "left unchanged"):
                bootstrap.install("speech")
        model.assert_not_called()
        self.assertEqual(settings.read_text(), "{invalid")

    def test_model_failure_keeps_collected_dependency_notices(self):
        order = []
        with patch.object(bootstrap, "install_component", side_effect=lambda _: order.append("packages")), \
             patch.object(bootstrap, "collect_licenses", side_effect=lambda: order.append("licenses")), \
             patch.object(bootstrap, "download_model", side_effect=lambda: order.append("model") or False):
            self.assertFalse(bootstrap.install("speech"))
        self.assertEqual(order, ["packages", "licenses", "model"])

    def test_invalid_profile_makes_no_changes(self):
        with self.assertRaises(ValueError):
            bootstrap.install("unknown")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_component_markers_are_separate_and_written_only_after_success(self):
        vendor = bootstrap.VENDOR
        vendor.mkdir(parents=True)
        (self.root / "requirements-pdf.txt").write_text("synthetic-package==1\n")
        with patch.object(bootstrap.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "synthetic")):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.install_component("pdf")
        self.assertFalse((vendor / ".requirements-pdf-sha256").exists())
        with patch.object(bootstrap.subprocess, "run") as process:
            bootstrap.install_component("pdf")
            bootstrap.install_component("pdf")
        process.assert_called_once()
        self.assertFalse((vendor / ".requirements-speech-sha256").exists())


class SetupEntryTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix" and shutil.which("zsh"), "Mac shell entry requires zsh")
    def test_mac_basic_profile_runs_in_a_spaced_directory_without_model(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="lecture clean setup ") as folder:
            root = Path(folder)
            for name in ("bootstrap.py", "bootstrap-mac.command"):
                shutil.copyfile(source / name, root / name)
            # A minimal executable shim selects this test's Python without installing it.
            python = root / ".venv/bin/python3"
            python.parent.mkdir(parents=True)
            python.write_text('#!/bin/sh\nexec "' + sys.executable + '" "$@"\n')
            python.chmod(0o755)
            result = subprocess.run(["zsh", str(root / "bootstrap-mac.command"), "--profile", "basic", "--yes", "--no-launch"],
                                    cwd=root, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("No packages or speech model", result.stdout)
            for name in (".runtime", "models", ".portable"):
                self.assertFalse((root / name).exists(), name)

    def test_native_mac_launcher_only_starts_the_basic_entry(self):
        source = Path(__file__).resolve().parents[1]
        launcher = (source / "LectureAtelier.app/Contents/MacOS/Launch").read_text()
        self.assertIn('"$lecture_root/launch.command"', launcher)
        self.assertNotIn("model-manifest", launcher)
        self.assertNotIn("setup-mac.command", launcher)
