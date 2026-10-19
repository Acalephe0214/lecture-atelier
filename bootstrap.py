"""Project-local optional components. Basic mode never installs packages or models."""
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
PROFILES = ("basic", "pdf", "speech", "full")


def existing_asr():
    """Inspect configured paths without opening a database or displaying secrets."""
    settings = ROOT / ".runtime" / "settings.json"
    if not settings.is_file():
        return False
    try:
        value = json.loads(settings.read_text(encoding="utf-8"))
        return bool(value.get("local_asr", {}).get("model_path"))
    except (OSError, ValueError, AttributeError):
        raise ValueError("Existing settings could not be read; left unchanged. Check .runtime/settings.json.") from None


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
        # Retain any explicitly configured backend, including external MLX paths.
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


def install_component(component):
    requirements = ROOT / ("requirements-" + component + ".txt")
    ready = VENDOR / (".requirements-" + component + "-sha256")
    digest = hashlib.sha256(requirements.read_bytes()).hexdigest()
    if not ready.is_file() or ready.read_text().strip() != digest:
        print("Installing project-local " + component + " dependencies from PyPI…", flush=True)
        subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--only-binary=:all:", "--index-url", "https://pypi.org/simple", "--target", str(VENDOR), "--upgrade", "-r", str(requirements)], check=True)
        ready.write_text(digest)


def download_model():
    print('Checking multilingual Whisper small (~0.5 GB); existing download caches are reused.', flush=True)
    from huggingface_hub import snapshot_download, HfApi
    # Downloading fixed repo files only; never trust_remote_code, no executable
    # model code. Store the resolved revision and every file digest for audit.
    if not all((MODEL / file).is_file() for file in ("model.bin", "config.json", "tokenizer.json", "model-manifest.json")):
        try:
            revision = HfApi().model_info(REPO, token=False, timeout=15).sha
            snapshot_download(repo_id=REPO, revision=revision, token=False, etag_timeout=15, local_dir=str(MODEL), allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*", "preprocessor_config.json", "README.md", "LICENSE*"])
        except Exception:
            print('Model download did not complete. Check https://huggingface.co/Systran/faster-whisper-small and rerun the speech profile. Basic import/editing still work via launch.command or launch-windows.bat.', flush=True)
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
    bundled_configure()
    return True


def install(profile="basic"):
    if profile not in PROFILES:
        raise ValueError("Unknown setup profile.")
    if sys.version_info[:2] < (3, 10):
        raise ValueError("Python 3.10 or later is required.")
    if profile == "basic":
        print('Basic app ready. No packages or speech model were downloaded.', flush=True)
        return True
    if sys.version_info[:2] >= (3, 14):
        raise ValueError("Optional components require Python 3.10–3.13 (3.12 tested).")
    paths = (ROOT / ".portable", VENDOR, ROOT / ".portable" / "licenses", ROOT / "models", MODEL)
    if any(path.is_symlink() for path in paths):
        raise ValueError("Installation paths cannot be symbolic links.")
    retained = existing_asr() if profile in {"speech", "full"} else False
    components = (["pdf"] if profile in {"pdf", "full"} else [])
    if profile in {"speech", "full"} and not retained:
        components.append("speech")
    if components:
        VENDOR.mkdir(parents=True, exist_ok=True)
        os.environ["PYTHONPATH"] = str(VENDOR)
        sys.path.insert(0, str(VENDOR))
        for component in components:
            install_component(component)
        # Preserve dependency notices even when a later model download fails.
        collect_licenses()
    if retained:
        print('Existing speech configuration retained; no replacement model downloaded. Check it in Settings.', flush=True)
    elif profile in {"speech", "full"} and not download_model():
        return False
    print('Setup ready. No recordings uploaded. No paid APIs called.', flush=True)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--profile", choices=PROFILES, default="basic")
    parser.add_argument("--configure-bundled", action="store_true")
    args = parser.parse_args()
    if args.install:
        if not install(args.profile):
            sys.exit(2)
    elif args.configure_bundled:
        bundled_configure()
    else:
        parser.print_help()
