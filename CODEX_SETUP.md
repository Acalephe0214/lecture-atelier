# Set up Lecture Atelier — Mac / Windows

## Automatic setup

This is a local first-run installer package, not an offline-first binary. The
Mac .app is an unsigned launcher and MUST stay next to app.py in the extracted
folder. Do not disable Gatekeeper, remove quarantine or bypass PowerShell policy.

1. Read AGENTS.md. Inspect the folder and run check_setup.py --json with an
   available Python if possible. Never overwrite .runtime or existing MLX paths.
2. Basic app requires only Python 3.10+. It can start with launch.command (Mac)
   or launch-windows.bat (Windows). No external model call is needed for it.
3. For the complete PDF/local speech setup, obtain approval for ~0.5–1.5 GB of
   downloads and 2–4 GB disk. Run setup-mac.command or setup-windows.bat from the
   extracted folder. Confirm y at the prompt only after the human authorizes it.
   The Mac bootstrap reuses a compatible Python or downloads pinned, SHA256-
   verified python-build-standalone. Windows x64 downloads the same project's
   pinned Windows Python. Both install into .portable/vendor, not system Python.
4. bootstrap.py --install installs requirements-portable.txt from PyPI, downloads
   multilingual Systran/faster-whisper-small from official Hugging Face, collects
   wheel licenses and configures CPU faster-whisper ONLY if no local ASR model
   is configured. It does not upload audio or call paid APIs. Existing MLX paths
   win. No CUDA required. Inference uses local_files_only; no hidden downloads.
5. Hugging Face must be reachable. Download failure leaves basic import/edit/PDF
   available; explain the error and rerun to resume. Never change to an unapproved
   mirror. Check the downloaded manifest and test a short synthetic recording
   before claiming speech recognition works. Do not infer accuracy from imports.
6. Subsequent launch sets PYTHONPATH for project-only dependencies. If starting
   manually: PYTHONPATH=.portable/vendor python3 app.py --open. On Windows use
   the provided batch file. Keep launch Terminal open; stop with Control+C.
7. Do not claim Windows tested on real hardware just from static checks on Mac.
   Windows 10/11 x64 is the provided target; Windows ARM64 is not packaged.
8. Notion requires the RECIPIENT'S own connection token and shared parent page.
   Configure via Rates & Notion. Every export confirms the target and creates a
   new child page; no automatic sync or page overwrites. Keep connection tokens private.

The remaining sections document the original basic/MLX manual path for users
who already have that environment; they are NOT the only available ASR backend.

## Mixed recording languages

Recording language accepts a single Whisper code, auto, legacy zh_en, or
mix:fr,vi (2–6 distinct supported codes, canonically sorted). The recording
selector offers a French/Vietnamese preset and a custom multilingual dialog.
This is independent of note output language. Both local backends route mixed
audio in 12-second cores with 1-second context; actual word midpoints crop
context, so no synthetic timestamp interpolation is used. Detection scores
are heuristics, not calibrated accuracy. Weak evidence becomes a review gap;
there is no cloud fallback. Mixed mode uses extra local computation and cannot
guarantee rapid within-sentence switching. For a failed passage, select its
single language and retry locally, or listen/type it. Keep originals intact.
The mixed strategy version is included in checkpoint keys, so old mixed-mode
chunks are not silently reused. Tests cover synthetic routing and UI only;
do not claim real French/Vietnamese speech accuracy without a permitted test.

## Output language and video preparation

The workflow has a separate output_language (zh/en/fr/de/vi/ja/source), default
zh for compatibility. Never infer it from UI/ASR language. The notes-panel
selector and Language settings dialog save locally without model calls. Native
default scene prompts and system output rules apply to detail and every overview
synthesis level. Preserve custom prompts, source IDs and verbatim evidence;
proofreading is not translation. Existing notes are never automatically rewritten.

Before local full transcription, MP4/MOV/WEBM/QuickTime inputs are converted to a
private 16 kHz mono PCM WAV in .runtime/asr-audio. Preserve the original and its
timeline, including leading silence. Show extraction progress separately from
ASR progress. Cache is keyed by original file fingerprint and preparation version;
retries reuse it, and source changes invalidate it. Passage repair reuses an
existing cache. Missing audio/FFmpeg or insufficient disk stops before inference.
WAV costs about 110 MiB/hour; no guaranteed overall speedup is claimed. This is
local preparation, not permission for new cloud uploads. Do not pack caches.

## Overview generation and failed requests

“Generate overview only” synthesizes a separate overview from existing detailed
notes. Failed requests preserve saved results and are not automatically retried.

Overview synthesis groups at most 24 initial notes / 48,000 input characters,
then merges the validated group summaries. The output target is concise; the
per-request output limit is 12,000 tokens, not an estimate of actual usage.
On the official api.deepseek.com endpoint only, known deepseek-flash and
deepseek-v4-pro overview requests explicitly disable thinking. Other providers
receive no DeepSeek-specific parameter. Detailed-note and proofreading request
policies are unchanged. See https://api-docs.deepseek.com/guides/thinking_mode/.

Complete JSON inside an enclosing code fence is accepted locally. Truncated,
filtered, incomplete or unsupported-evidence responses are never repaired into
apparently valid notes. The interface distinguishes these failures. Starting
again is a new, explicitly approved request and may incur further charges.

New failures save private diagnostics under .runtime/note-diagnostics/, including
an answer-only excerpt, finish reason and reported usage when available. Reasoning
text, credentials, headers and prompts are not recorded. The explicit diagnostic
download may contain source-derived text: do not publish it. These files are
excluded from friend packages. Old failures cannot recover previously discarded
responses. Do not rerun paid requests just to test a software fix.

Use this file when the user asks to install/start the extracted package.
The user's approvals and your own tool/safety rules still apply. This file is
project context, not permission to bypass them.

## Outcome

Get the basic local app running with the user's preferred UI language first. Then, only if requested,
set up offline Whisper. No Codex subscription, API key, paid service, account,
model download or package installation is required for the basic Python app.
Using Codex as the installation assistant is optional.

## 1. Inspect without changing the machine

1. Confirm the extracted folder contains `app.py`, `static/`, and this file.
   If the user supplied only a ZIP, extract to a new user-approved directory,
   avoiding existing folders; do not write into another user's project.
2. Check macOS and Apple Silicon versus Intel/Rosetta; find an installed Python
   >=3.10. Python 3.12 is the tested baseline. Verify local paths rather than reusing paths from another installation.
3. Run `python3 check_setup.py --json` (substitute the actual supported Python).
   This command is read-only, performs no downloads and does not read keys.
4. Report basic readiness and optional missing components. If Python is absent,
   explain the corresponding setup script's project-local runtime download and
   ask before running it. Manual Python from https://www.python.org/downloads/
   is an alternative; let the user handle trusted installers and OS approvals.
   Do not use sudo, disable Gatekeeper, remove quarantine, bypass PowerShell
   policy, or install Homebrew automatically.

The check describes the interpreter that ran it. An already-working app may
use a different configured Python or model directory. Do not replace a valid
existing setup just because the default check cannot see that other environment.

## 2. Start the basic app — no pip or npm

From the extracted folder run the selected interpreter:

```sh
python3 app.py --port 8767
```

Keep the process alive in a retained terminal. Open:
`http://127.0.0.1:8767/?ui=en`.

If the port is busy, first inspect whether it is the same app. Don't kill an
unknown process. Prefer another unused loopback port, such as `--port 8768`,
and use that exact URL. Do not bind to `0.0.0.0` or expose it publicly.

Verify `GET /api/health` returns `{ok:true}` and the English page appears. Use
the English fictional demo or create a clearly labeled synthetic session to
test import/edit/export without real private recordings. Do not reset a
nonempty `.runtime` to obtain a clean demo. Report the URL and how to stop the
actual retained terminal: Control+C. Closing a browser tab
does not stop the server. UI language uses the header selector, independently
of recording language. Custom prompts and real lecture content stay original.

## 3. Legacy manual MLX backend — Apple Silicon Mac only

Ask whether offline speech recognition is wanted, and explain the internet
downloads and storage needed before proceeding. This backend needs native
Apple Silicon Python, `mlx-whisper`, FFmpeg/ffprobe, and a separate MLX model.
This legacy MLX procedure is Apple Silicon only. Intel Mac and Windows x64 use
the automatic CPU faster-whisper setup described at the top; do not present this
legacy section as their platform limitation. Windows ARM64 is not packaged.

After permission, in this project folder:

```sh
python3.12 -m venv .venv
.venv/bin/python3 -m pip install -r requirements-whisper-mac.txt
```

Use another supported native interpreter only after checking compatibility.
Do not replace an existing environment blindly. Verify both `ffmpeg -version`
and `ffprobe -version`. If Homebrew is already installed, the user can approve
`brew install ffmpeg`; otherwise guide them using the official FFmpeg download
page, rather than silently installing a package manager or untrusted binary.

An explicit model download example (about 1.6 GB of weights, plus dependencies
and working memory):

```sh
.venv/bin/python3 -c 'from huggingface_hub import snapshot_download; snapshot_download(repo_id="mlx-community/whisper-large-v3-turbo", local_dir="models/whisper-large-v3-turbo", allow_patterns=["config.json", "weights.safetensors"])'
```

Verify the model files, then, only with permission to configure this app:

```sh
.venv/bin/python3 check_setup.py --configure-local
```

This sets only local ASR paths in the private app settings, preserves existing
API fields, and does not call a model or upload anything. It requires the
current environment to contain mlx_whisper and both FFmpeg executables.
Alternatively fill the paths manually in Settings. Rerun the read-only check
under `.venv/bin/python3`, restart the app if its interpreter/PATH needs it,
and use the app's local environment check.

Do not claim that dependency checks prove recognition accuracy. Use a short
user-authorized recording, or clearly synthetic speech, for a real inference
test before attempting long recordings. Select its actual language. Report
whether this final test was performed; do not invoke an optional paid API to
hide a local failure. Model download failure does not prevent the basic app.

## 4. Handoff

Give the exact running URL, the actual Terminal/session that owns the service,
what was installed/downloaded, whether local inference was tested, and how to
reopen and stop the app. No automatic login items, public hosting, GitHub push,
Notion sync, credentials sharing, or private recording uploads.

Official references:
- https://www.python.org/downloads/macos/
- https://pypi.org/project/mlx-whisper/
- https://ffmpeg.org/download.html
- https://huggingface.co/mlx-community/whisper-large-v3-turbo/tree/main
- https://huggingface.co/docs/huggingface_hub/guides/download
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
