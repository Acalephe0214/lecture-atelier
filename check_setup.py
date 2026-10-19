"""Read-only by default. No downloads, audio uploads, or API-key inspection."""
from __future__ import annotations
import argparse
import importlib.util
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
DEFAULT_MODEL = ROOT / "models" / "whisper-large-v3-turbo"


def inspect(model_path=DEFAULT_MODEL):
    system, architecture = platform.system(), platform.machine()
    native_arm = system == "Darwin" and architecture == "arm64"
    hardware_arm = native_arm
    if system == "Darwin" and not native_arm:
        try:
            hardware_arm = subprocess.check_output(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], text=True, stderr=subprocess.DEVNULL, timeout=3).strip() == "1"
        except (OSError, subprocess.SubprocessError):
            pass
    model = Path(model_path).expanduser().absolute()
    basic = sys.version_info >= (3,10)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    try:
        mlx = importlib.util.find_spec("mlx_whisper") is not None
    except (ValueError, ImportError):
        mlx = False
    model_files = (model / "config.json").is_file() and any((model / name).is_file() for name in ("weights.npz", "weights.safetensors"))
    missing = [label for label, ready in (("Python >=3.10",basic),("native Apple Silicon macOS Python",native_arm),("mlx-whisper in this interpreter",mlx),("ffmpeg",ffmpeg),("ffprobe",ffprobe),("MLX model files",model_files)) if not ready]
    return {"system":system,"architecture":architecture,"apple_silicon_hardware":hardware_arm,
        "native_apple_silicon_python":native_arm,"python":sys.executable,"python_version":platform.python_version(),
        "basic_app_ready":basic,"local_asr_prerequisites_present":basic and not missing,
        "ffmpeg":ffmpeg,"ffprobe":ffprobe,"mlx_whisper_package_present":mlx,
        "model_path":str(model),"model_files_present":model_files,"missing_for_local_asr":missing,
        "inference_tested":False,"api_keys_needed_for_basic_app":False,
        "notice":"No downloads, model loading or private settings inspection performed. File/package presence is not an inference test."}


def configure_local(model_path=DEFAULT_MODEL):
    result = inspect(model_path)
    if not result["local_asr_prerequisites_present"]:
        raise ValueError("Local ASR prerequisites missing: " + ", ".join(result["missing_for_local_asr"]))
    from local_transcription import checked_config
    from store import Store
    store = Store(ROOT / ".runtime")
    saved = store.public_settings()["local_asr"]
    config = checked_config({"python_path":sys.executable,"model_path":str(Path(model_path).expanduser().absolute()),"language":saved.get("language","auto")})
    store.update_settings({"local_asr":config})
    return {"configured":True,"inference_tested":False,"message":"Local ASR paths saved. API settings retained. No model test, download or upload performed."}


def inspect_faster(model_path=None):
    vendor=ROOT/".portable"/"vendor"
    if vendor.is_dir():
        sys.path.insert(0,str(vendor))
    model=Path(model_path or ROOT/"models"/"faster-whisper-small").expanduser().absolute()
    def present(name):
        try: return importlib.util.find_spec(name) is not None
        except (ImportError,ValueError): return False
    packages={name:present(name) for name in ("faster_whisper","av","reportlab")}
    files=all((model/file).is_file() for file in ("config.json","model.bin","tokenizer.json"))
    return {"system":platform.system(),"architecture":platform.machine(),"backend":"faster",
        "python":sys.executable,"basic_app_ready":sys.version_info >= (3,10),"packages":packages,
        "model_path":str(model),"model_files_present":files,
        "local_asr_prerequisites_present":packages["faster_whisper"] and packages["av"] and files,
        "inference_tested":False,"notice":"Read-only file/package presence check. No downloads, keys or model loading; use a short real inference test before claiming readiness."}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json",action="store_true",help="Print the read-only readiness report as JSON")
    parser.add_argument("--configure-local",action="store_true",help="Explicitly save local ASR paths only; requires installed prerequisites")
    parser.add_argument("--model-path",type=Path,default=DEFAULT_MODEL)
    parser.add_argument("--backend",choices=("mlx","faster"),default="mlx")
    args=parser.parse_args()
    try:
        if args.backend == "faster":
            if args.configure_local:
                raise ValueError("Use bootstrap.py --configure-bundled for the installed portable backend; this command remains read-only.")
            result=inspect_faster(None if args.model_path == DEFAULT_MODEL else args.model_path)
        else:
            result=configure_local(args.model_path) if args.configure_local else inspect(args.model_path)
    except ValueError as exc:
        parser.exit(1,str(exc)+"\n")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if not args.json and not args.configure_local:
        print("\nBasic app: python3 app.py --open\nEnglish UI: http://127.0.0.1:8767/?ui=en\nOptional speech setup: read CODEX_SETUP.md")


if __name__=="__main__": main()
