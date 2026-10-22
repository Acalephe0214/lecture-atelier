"""Build a fresh, allowlisted public source tree and optional source ZIP. No Git/network operations."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from package_for_friends import FILES as APP_FILES, check_public_content

ROOT = Path(__file__).resolve().parent
PUBLIC_DOCS = ("README.md", "README.zh-CN.md", "PRIVACY.md", "SECURITY.md", "requirements-dev.txt", ".gitattributes",
    "docs/ARCHITECTURE.md", "docs/VERIFICATION.md", "docs/EVALUATION.md", "docs/ROADMAP.md", "docs/PUBLISHING.md", "docs/TRY-IT.md", "docs/images/workspace.png", "docs/images/journey-map.png",
    "evaluate_transcripts.py",
    ".github/workflows/checks.yml", ".github/ISSUE_TEMPLATE/bug.yml", ".github/ISSUE_TEMPLATE/installation.yml",
    ".github/ISSUE_TEMPLATE/feature.yml", ".github/ISSUE_TEMPLATE/config.yml", ".github/ISSUE_TEMPLATE/output-quality.yml",
    "examples/import_demo.srt", "examples/untimed_demo.txt")
PUBLIC_TESTS = (
    "tests/test_acceptance.py", "tests/test_asr_guard.py", "tests/test_audio_processing.py", "tests/test_clean_workspace.py",
    "tests/test_connectors.py", "tests/test_delivery.py", "tests/test_diagnostic_catalog.py", "tests/test_end_to_end_audit.py",
    "tests/test_friend_guides.py", "tests/test_local_repair.py", "tests/test_local_sources.py", "tests/test_local_transcription.py",
    "tests/test_mixed_asr.py", "tests/test_note_jobs.py", "tests/test_output_language.py", "tests/test_overview_recovery.py",
    "tests/test_packaging.py", "tests/test_pipeline.py", "tests/test_quicktime.py", "tests/test_reading_transcript.py",
    "tests/test_redline.py", "tests/test_server.py", "tests/test_setup_check.py", "tests/test_video_prepare.py",
    "tests/test_workflow.py", "tests/test_workflow_audit.py", "tests/test_source_release.py", "tests/test_bootstrap_profiles.py", "tests/test_evaluate_transcripts.py",
    "tests/test_recycle.py", "tests/test_journey.cjs", "tests/test_note_checkpoints.py",
    "tests/test_i18n.cjs", "tests/test_paragraphs.cjs", "tests/test_playback.cjs", "tests/test_panels.cjs")
SOURCE_FILES = tuple(dict.fromkeys((*APP_FILES, "package_for_friends.py", "prepare_github.py", *PUBLIC_DOCS, *PUBLIC_TESTS)))


def _payloads():
    output=[]
    for name in SOURCE_FILES:
        relative=Path(name)
        path=ROOT/relative
        if relative.is_absolute() or ".." in relative.parts or path.is_symlink() or any((ROOT/parent).is_symlink() for parent in relative.parents) or not path.is_file() or not path.resolve().is_relative_to(ROOT):
            raise ValueError("Missing or unsafe public source: "+name)
        if any(part in {".runtime",".portable",".venv","models",".git","test-results"} for part in relative.parts):
            raise ValueError("Private directory in public allowlist: "+name)
        content=path.read_bytes();check_public_content(name,content)
        output.append((name,content))
    return output


def build(destination, archive=None):
    destination=Path(destination).expanduser().absolute()
    archive=Path(archive).expanduser().absolute() if archive else None
    if destination.exists() or destination.is_symlink() or (archive and (archive.exists() or archive.is_symlink())):
        raise FileExistsError("Use a fresh directory and ZIP filename; nothing was overwritten.")
    if destination==ROOT or ROOT.is_relative_to(destination):
        raise ValueError("The destination must not replace the project or a parent directory.")
    for target in (destination,archive):
        if target and any(parent.is_symlink() for parent in target.parents):
            raise ValueError("Release paths must not contain symbolic-link parents.")
    payloads=_payloads()  # Validate every source before creating any output.
    manifest={"format_version":1,"release_kind":"source-only","contains_git_history":False,
        "contains_models_or_runtime":False,"files":[{"path":name,"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)} for name,data in payloads]}
    payloads.append(("SOURCE-MANIFEST.json",(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode()))
    destination.mkdir(parents=True,exist_ok=False)
    for name,data in payloads:
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("xb") as output:output.write(data)
        path.chmod(0o755 if name.endswith(".command") or name.endswith("/MacOS/Launch") else 0o644)
    if archive:
        archive.parent.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as package:
            for name,data in payloads:
                entry=zipfile.ZipInfo("lecture-atelier/"+name);entry.create_system=3
                entry.external_attr=(0o100755 if name.endswith(".command") or name.endswith("/MacOS/Launch") else 0o100644)<<16
                entry.compress_type=zipfile.ZIP_DEFLATED;package.writestr(entry,data)
    return {"directory":str(destination),"archive":str(archive) if archive else None,"files":len(payloads),"git_initialized":False,"uploaded":False}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--zip",type=Path,dest="archive")
    args=parser.parse_args()
    print(json.dumps(build(args.output,args.archive),ensure_ascii=False,indent=2))
