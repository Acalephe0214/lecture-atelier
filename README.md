# Lecture Atelier · 听课之间

A local-first workspace for **reviewable transcripts and source-linked notes**.

[中文说明](README.zh-CN.md) · [Downloads](https://github.com/Acalephe0214/lecture-atelier/releases) · [Architecture](docs/ARCHITECTURE.md) · [Checks and limitations](docs/VERIFICATION.md) · [Roadmap](docs/ROADMAP.md)

![Fictional transcript and meeting notes in Lecture Atelier](docs/images/workspace.png)

Lecture Atelier turns recordings into editable transcripts and structured notes for lectures, discussions and meetings. Recordings, transcript revisions and generated notes remain linked for review.

## Features

- Import recordings/video or TXT, SRT, VTT and supported JSON transcripts. Optional local Whisper transcription preserves original audio, checkpoints and visible transcription gaps.
- Edit transcript passages while listening, retain original text and timestamps, and accept or reject AI proofreading suggestions.
- Generate lecture, discussion or meeting notes through a configured Chat Completions-compatible endpoint. A separate overview highlights key information, decisions, actions and open questions, with source links.
- Export readable transcripts, revised editions, notes and subtitles, with optional one-way Notion export.

Chinese and English interfaces are available. Interface language, recording language and note output language are independent. Output choices include Chinese, English, French, German, Vietnamese, Japanese and matching the source.

## Quick start

Requires Python 3.10+. Transcript import, editing and reading use the Python standard library.

From the extracted project folder:

```sh
python3 app.py --open
```

The app opens at <http://127.0.0.1:8767/>. On Windows, use `py -3 app.py --open` or `launch-windows.bat`. A built-in fictional demo is available.

### Setup profiles

Mac: open `setup-mac.command`. Windows 10/11 x64: open `setup-windows.bat`.
The setup menu defaults to **basic**; downloads require confirmation.

| Profile | Installs |
| --- | --- |
| `basic` | Python only if missing; no packages or speech model |
| `pdf` | PDF export dependencies; no speech model |
| `speech` | CPU Whisper and media tools; downloads a model only when no speech backend is configured |
| `full` | PDF and speech components |

Speech setup may need 0.5–1.5 GB downloads and 2–4 GB disk. Existing speech settings, including Apple Silicon MLX paths, are retained. The Mac launcher opens the basic app independently of model installation.

Detailed installation and usage: [English guide](FRIEND-GUIDE-EN.html) · [Chinese guide](FRIEND-GUIDE.html) · [First-use trial](docs/TRY-IT.md).

### Optional AI notes and Notion

Configure a Chat Completions-compatible API root URL, model ID and API key in Settings. The adapter appends `/chat/completions`. AI proofreading and note generation require confirmation before sending text to the configured provider.

Notion export requires a connection token and authorized parent page. Each export creates a new child page. Recordings and application data stay local unless an external operation is selected; API keys are stored locally without app-level encryption. See [PRIVACY.md](PRIVACY.md).

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

Transcripts and generated notes require human review. Text-only proofreading uses transcript context rather than audio, and source links do not guarantee semantic accuracy. Token and cost estimates are approximate.

Software checks use synthetic fixtures and simulated model responses; there is no published transcription or summary-quality benchmark. Hosted Linux, macOS and Windows checks pass, including basic setup with an existing Python; clean end-user Windows installation and speech setup remain unverified. Windows ARM64 is unsupported. [Verification scope →](docs/VERIFICATION.md)

Supplementary slide and personal-note upload is planned. [Roadmap →](docs/ROADMAP.md)

## Development

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_i18n.cjs
node tests/test_paragraphs.cjs
node tests/test_playback.cjs
node tests/test_panels.cjs
```

PDF checks use the optional packages in `requirements-dev.txt`; some media checks need FFmpeg. Tests create temporary synthetic workspaces. See [source packaging](docs/PUBLISHING.md) for distribution tools.

## License

Project source uses [MIT](LICENSE). Upstream software/models keep their own licenses: see [third-party notices](THIRD-PARTY-NOTICES.txt) and [license copies and sources](licenses/README.md). No third-party runtimes, model weights or fonts are bundled in this source repository.

Developed with AI-assisted coding; local speech recognition integrates upstream Whisper implementations.
