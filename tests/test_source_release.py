"""Public source export checks. Synthetic data, no Git or network writes."""
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import prepare_github as release
from package_for_friends import check_public_content, LICENSE_FILES


class SourceReleaseTests(unittest.TestCase):
    def test_source_tree_and_zip_match_allowlist_and_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder).resolve()/"source";archive=Path(folder).resolve()/"source.zip"
            result=release.build(target,archive)
            self.assertFalse(result["uploaded"]);self.assertFalse(result["git_initialized"])
            actual={str(path.relative_to(target)) for path in target.rglob("*") if path.is_file()}
            self.assertEqual(actual,set(release.SOURCE_FILES)|{"SOURCE-MANIFEST.json"})
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(set(package.namelist()),{"lecture-atelier/"+name for name in actual})
                self.assertEqual(package.read("lecture-atelier/LICENSE"),(target/"LICENSE").read_bytes())
            for item in json.loads((target/"SOURCE-MANIFEST.json").read_text())["files"]:
                self.assertEqual(hashlib.sha256((target/item["path"]).read_bytes()).hexdigest(),item["sha256"])
            self.assertFalse((target/".runtime").exists());self.assertFalse((target/".git").exists())
            self.assertTrue((target/"docs/images/workspace.png").read_bytes().startswith(b"\x89PNG"))

    def test_existing_outputs_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder).resolve();(path/"used").mkdir();(path/"old.zip").write_bytes(b"keep")
            for target,archive in ((path/"used",None),(path/"new",path/"old.zip")):
                with self.assertRaises(FileExistsError):release.build(target,archive)
            self.assertFalse((path/"new").exists());self.assertEqual((path/"old.zip").read_bytes(),b"keep")

    def test_missing_file_or_private_marker_stops_before_output_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();target=root/"out"
            with patch.object(release,"ROOT",root),patch.object(release,"SOURCE_FILES",("app.py",)):
                with self.assertRaises(ValueError):release.build(target)
                (root/"app.py").write_text('path="'+"/"+"Users/"+"example-author/private"+'"')
                with self.assertRaises(ValueError):release.build(target)
            self.assertFalse(target.exists())

    def test_symbolic_link_parent_is_not_a_public_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();(root/"private").mkdir();(root/"private/file.txt").write_text("private")
            (root/"docs").symlink_to(root/"private",target_is_directory=True)
            with patch.object(release,"ROOT",root),patch.object(release,"SOURCE_FILES",("docs/file.txt",)):
                with self.assertRaises(ValueError):release.build(root/"out")
            self.assertFalse((root/"out").exists())

    def test_major_license_copies_and_relative_readme_links_are_present(self):
        names=set(release.SOURCE_FILES)
        self.assertTrue(set(LICENSE_FILES).issubset(names))
        self.assertIn("Copyright (c) 2022 OpenAI",(release.ROOT/"licenses/openai-whisper-LICENSE").read_text())
        self.assertIn("Copyright (c) 2026 Yanbo Qiao",(release.ROOT/"LICENSE").read_text())
        for name in ("README.md","README.zh-CN.md","docs/ARCHITECTURE.md","docs/ROADMAP.md","docs/PUBLISHING.md","licenses/README.md"):
            for link in re.findall(r"\]\(([^)]+)\)",(release.ROOT/name).read_text()):
                if "://" in link or link.startswith("#"):continue
                resolved=(Path(name).parent/link.split("#")[0]).as_posix()
                self.assertIn(resolved,names,(name,link))

    def test_public_source_scanner_uses_generic_paths_and_fake_secrets(self):
        for value in (("/"+"Users/"+"example-author/private").encode(),b"sk-"+b"x"*32,b"-----BEGIN PRIVATE KEY-----\nnot-real"):
            with self.assertRaises(ValueError):check_public_content("synthetic.py",value)
        check_public_content("LICENSE",b"Copyright (c) 2026 Example")
