"""Recipient-side installer. Downloads only after --install; no system changes."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / ".portable" / "vendor"
MODEL = ROOT / "models" / "faster-whisper-small"
REPO = "Systran/faster-whisper-small"


def bundled_configure():
    if not VENDOR.is_dir():
        return False
    sys.path.insert(0, str(VENDOR))
    if not ((MODEL / "model.bin").is_file() and (MODEL / "config.json").is_file() and (MODEL / "tokenizer.json").is_file()):
        return False
    from store import Store
    from local_transcription import checked_config
    store = Store(ROOT / ".runtime")
    existing = store.private_settings()["local_asr"]
    if existing.get("model_path"):
        # Existing working setups, including the author's MLX config, win.
        return True
    config = checked_config({"backend": "faster", "model_path": str(MODEL), "python_path": sys.executable, "language": "auto"})
    store.update_settings({"local_asr": config})
    print('Local Whisper configured. Inference is not tested by setup.')
    return True


def collect_licenses(target=ROOT / ".portable" / "licenses"):
    target.mkdir(parents=True, exist_ok=True)
    manifest = []
    for dist in importlib.metadata.distributions(path=[str(VENDOR)]):
        name = dist.metadata.get("Name", "unknown")
        safe = ''.join(c for c in name if c.isalnum() or c in '-_.')
        manifest.append({"name": name, "version": dist.version, "home": dist.metadata.get("Home-page", ""), "license": dist.metadata.get("License-Expression", dist.metadata.get("License", ""))})
        for file in dist.files or []:
            if any(word in str(file).lower() for word in ("license", "copying", "notice")) and str(file).lower().endswith((".txt", ".md", "license", "copying", "notice")):
                source = Path(dist.locate_file(file)).resolve()
                if source.is_file() and source.is_relative_to(VENDOR.resolve()) and source.stat().st_size < 2_000_000:
                    (target / (safe + "-" + str(file).replace('/', '_').replace('\\', '_'))).write_bytes(source.read_bytes())
    (target / "installed-packages.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def install():
    if not (3, 10) <= sys.version_info[:2] < (3, 14):
        raise ValueError("Please use Python 3.10–3.13 (3.12 tested).")
    if VENDOR.is_symlink() or (ROOT / ".portable").is_symlink() or MODEL.is_symlink():
        raise ValueError("Installation paths cannot be symbolic links.")
    VENDOR.mkdir(parents=True, exist_ok=True)
    os.environ["PYTHONPATH"] = str(VENDOR)
    sys.path.insert(0, str(VENDOR))
    ready = VENDOR / ".requirements-sha256"
    requirements = ROOT / "requirements-portable.txt"
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not ready.is_file() or ready.read_text().strip() != digest:
        print('1/3 · Installing isolated PDF / CPU Whisper dependencies from PyPI…', flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--target", str(VENDOR), "--upgrade", "-r", str(requirements)], check=True)
        ready.write_text(digest)
    print('2/3 · Checking / downloading multilingual Whisper small (~0.5 GB). Progress below; existing Hugging Face cache can resume.', flush=True)
    from huggingface_hub import snapshot_download, HfApi
    # Downloading fixed repo files only; never trust_remote_code, no executable
    # model code. Store the resolved revision and every file digest for audit.
    if not all((MODEL / file).is_file() for file in ("model.bin", "config.json", "tokenizer.json", "model-manifest.json")):
        try:
            revision = HfApi().model_info(REPO, token=False, timeout=15).sha
            snapshot_download(repo_id=REPO, revision=revision, token=False, etag_timeout=15, local_dir=str(MODEL), allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*", "preprocessor_config.json", "README.md", "LICENSE*"])
        except Exception:
            print('Model download did not complete. Check access to https://huggingface.co/Systran/faster-whisper-small ; rerun setup to resume. No unofficial mirror is used. PDF / import / editing still work via launch.command or launch-windows.bat.', flush=True)
            return False
        files = {}
        for file in MODEL.iterdir():
            if file.is_file():
                digest_file = hashlib.sha256()
                with file.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest_file.update(chunk)
                files[file.name] = digest_file.hexdigest()
        (MODEL / "model-manifest.json").write_text(json.dumps({"repo": REPO, "revision": revision, "license": "MIT", "downloaded_at": time.time(), "sha256": files}, indent=2))
    print('3/3 · Saving local paths and collecting dependency licenses…', flush=True)
    collect_licenses()
    bundled_configure()
    print('Ready. No recordings uploaded. No paid APIs called. Open launch.command (Mac) or launch-windows.bat (Windows).', flush=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--configure-bundled", action="store_true")
    args = parser.parse_args()
    if args.install:
        if not install():
            sys.exit(2)
    elif args.configure_bundled:
        bundled_configure()
    else:
        parser.print_help()
