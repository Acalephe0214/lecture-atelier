# Lecture Atelier · 听课之间

A local-first workspace for **reviewable transcripts and source-linked notes**.

[中文说明](README.zh-CN.md) · [Architecture](docs/ARCHITECTURE.md) · [Checks and limitations](docs/VERIFICATION.md) · [Roadmap](docs/ROADMAP.md)

![Fictional transcript and meeting notes in Lecture Atelier](docs/images/workspace.png)

Useful notes should let you return to what was actually said. Lecture Atelier keeps recordings, transcripts, suggested corrections and generated notes separate, with human review between them.

## Features

- Import recordings/video or TXT, SRT, VTT and supported JSON transcripts. Optional local Whisper transcription preserves original audio, checkpoints and visible transcription gaps.
- Listen and edit **any** passage. Keep initial text and real timestamps; accept or reject suggested AI proofreading changes.
- Generate lecture, discussion or meeting notes through an explicitly configured Chat Completions-compatible endpoint. A separate overview highlights key information, explicit decisions, actions and open questions, with source links.
- Export readable transcript paragraphs, revised editions, notes and subtitles. Optional Notion export creates a new child page after confirmation; it is not two-way synchronization.

Chinese and English interfaces are available. Interface language, recording language and note output language are independent. Output choices include Chinese, English, French, German, Vietnamese, Japanese and matching the source.

## Quick start

The **basic app** needs Python 3.10+; Python 3.12 is the local development baseline. No Node.js, npm or extra Python packages are needed for transcript import, editing and reading.

From the extracted project folder:

```sh
python3 app.py --open
```

Open the printed address, normally <http://127.0.0.1:8767/>. Keep the terminal open; stop with **Control+C**, not Command+C. On Windows with Python installed, use `py -3 app.py --open` or `launch-windows.bat`.

Do not open `static/index.html` as the app: a `file://` preview cannot save to the database. A fresh workspace has no personal sessions. **Explore fictional demo** creates one optional synthetic example.

### Optional local speech and PDF setup

- Mac: run `setup-mac.command` from Finder, or `/bin/zsh ./setup-mac.command`.
- Windows 10/11 x64: run `setup-windows.bat`.
- Review the download prompt before accepting. Setup downloads a project-local runtime/dependencies and a multilingual Whisper small model. Allow roughly 2–4 GB disk space and initial network access. This is **not a preinstalled offline binary**.
- The portable path uses CPU faster-whisper. Existing Apple Silicon MLX Whisper configuration can be reused. Windows installation scripts are provided but **not verified on Windows hardware**; Windows ARM64 is not packaged.

See the [English user guide](FRIEND-GUIDE-EN.html), [Chinese guide](FRIEND-GUIDE.html), and [coding-assistant setup instructions](CODEX_SETUP.md). The Mac `.app` is an unsigned launcher, not a notarized standalone application; keep it inside the project folder. Do not disable system protections to run it.

### Optional AI notes and Notion

Enter your provider's API root URL, exact model ID and API key in Settings. The adapter appends `/chat/completions`. Saving configuration makes no model call. External operations require confirmation and may incur charges; a web-chat subscription does not necessarily include API access. Arbitrary provider compatibility is not guaranteed.

Local speech inference does not upload audio. AI proofreading and note generation send session text/context to the configured provider. Notion needs a separate connection token and authorized parent page. Read [PRIVACY.md](PRIVACY.md) before using private recordings.

## Workflow

```text
Recording or imported transcript
    → local transcription, if needed
    → listen, edit and review suggestions
    → detailed notes + source-linked overview
    → local export / explicitly confirmed Notion export
```

The Python server binds only to loopback. SQLite and private caches live in `.runtime/`. The buildless interface uses HTML/CSS/JavaScript; optional speech engines run in separate processes. [Architecture and module map →](docs/ARCHITECTURE.md)

## Limits

This is a personal workflow prototype, not an authoritative transcript or verified decision record. Whisper can hallucinate; guards can miss errors or flag real repetition. Valid source IDs and matching quotations do not establish semantic correctness. Text-only proofreading does not hear the recording.

Token/cost estimates are planning ranges, **not spending caps**. There is no published transcription or summary-quality benchmark. Automated checks mainly use synthetic fixtures and simulated model responses. [Verification scope →](docs/VERIFICATION.md)

**Supplementary slide and personal-note upload is planned, not implemented.** The proposed design distinguishes slide pages and personal observations from recorded speech. [Reference-material workflow →](docs/ROADMAP.md)

## Development and publishing

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_i18n.cjs
node tests/test_paragraphs.cjs
node tests/test_playback.cjs
node tests/test_panels.cjs
```

PDF checks need the optional packages in `requirements-dev.txt`; some media checks need FFmpeg. Tests use temporary synthetic workspaces. Never point them at personal data.

Read [publishing instructions](docs/PUBLISHING.md). Upload a clean source export, not a used installation folder. Exclude recordings, transcripts, databases, API keys, diagnostics, models and dependency environments.

## License

Project source uses [MIT](LICENSE). Upstream software/models keep their own licenses: see [third-party notices](THIRD-PARTY-NOTICES.txt) and [license copies and sources](licenses/README.md). No third-party runtimes, model weights or fonts are bundled in this source repository.

The app integrates upstream Whisper implementations; it does not introduce a newly trained speech model. It was developed with AI-assisted coding. The source license does not grant rights to third-party recordings, course slides, private notes or trademarks.
