"""Create an allowlisted source-only ZIP, never copying a working runtime."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parent
LICENSE_FILES = ("LICENSE", "licenses/README.md", "licenses/openai-whisper-LICENSE", "licenses/faster-whisper-LICENSE",
    "licenses/ctranslate2-LICENSE", "licenses/mlx-LICENSE", "licenses/pyav-LICENSE.txt", "licenses/imageio-ffmpeg-LICENSE", "licenses/reportlab-LICENSE")
FILES = (
    "VERSION", "CHANGELOG.md",
    "app.py", "store.py", "recycle.py", "local_sources.py", "index_local_course.py",
    "local_transcription.py", "local_repair.py", "asr_checkpoints.py", "audio_processing.py", "note_jobs.py", "note_checkpoints.py",
    "launch.command", "setup-mac.command", "launch-windows.bat", "requirements.txt", "requirements-whisper-mac.txt",
    "AGENTS.md", "CODEX_SETUP.md", "check_setup.py", "START-HERE.html", "FRIEND-GUIDE-EN.html",
    "FRIEND-README.txt", "FRIEND-GUIDE.html", ".gitignore", ".env.example",
    "core/__init__.py", "core/pipeline.py", "core/workflow.py", "core/output_language.py", "core/audio_prepare.py", "core/asr_guard.py", "core/languages.py", "core/mixed_asr.py", "core/overview.py", "core/chat_stream.py", "core/word_export.py",
    "static/index.html", "static/app.js", "static/style.css", "static/workspace.css", "static/ui-copy.js", "static/journey.js", "static/workspace-tools.js", "static/playback.js", "static/paragraphs.js", "static/i18n.js", "static/i18n-en.js", "static/panels.js", "static/favicon.svg",
    "core/usage_estimate.py", "core/delivery.py", "core/pdf_export.py", "core/notion_export.py", "core/local_engine.py",
    "static/delivery.js", "bootstrap.py", "bootstrap-mac.command", "bootstrap-windows.ps1", "portable_runtime.json",
    "setup-windows.bat", "requirements-portable.txt", "requirements-pdf.txt", "requirements-speech.txt", "THIRD-PARTY-NOTICES.txt",
    "LectureAtelier.app/Contents/Info.plist", "LectureAtelier.app/Contents/MacOS/Launch",
    "SHARE-WITH-FRIEND.txt",
    "core/redline.py", "core/proofread_export.py", "core/paragraphs.py", "correction_jobs.py", "static/revisions.js",
) + LICENSE_FILES


def check_public_content(name, content):
    # Generic source guards, not an exhaustive secret detector. Do not embed an
    # author's real account names, email addresses or private course list here.
    patterns = (rb"/(?:Users|home)/[A-Za-z0-9_.-]+/", rb"[A-Za-z]:[\\/]Users[\\/][A-Za-z0-9_.-]+[\\/]",
        rb"(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", rb"\bsk-[A-Za-z0-9_-]{24,}\b",
        rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b", rb"\bgithub_pat_[A-Za-z0-9_]{40,}\b")
    if any(re.search(pattern,content) for pattern in patterns):
        raise ValueError("Private workspace marker or credential-shaped value detected: " + name)


def build(destination):
    destination = Path(destination).expanduser().absolute()
    payloads = []
    for relative in FILES:
        path = ROOT / relative
        if path.is_symlink() or any((ROOT/parent).is_symlink() for parent in Path(relative).parents) or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Missing or unsafe public source: " + relative)
        content = path.read_bytes()
        check_public_content(relative, content)
        payloads.append((relative, content))
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = "\n".join(hashlib.sha256(data).hexdigest() + "  " + name for name, data in payloads) + "\n"
    # Exclusive creation: never overwrite an earlier release or user archive.
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in payloads + [("SHA256SUMS.txt", manifest.encode())]:
            entry = zipfile.ZipInfo("LectureAtelier/" + name)
            entry.create_system = 3
            entry.external_attr = (0o100755 if name.endswith(".command") or name.endswith("/MacOS/Launch") else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError("ZIP integrity check failed")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.output)
    print(f"Private-data-free allowlisted package: {result} ({result.stat().st_size} bytes)")
