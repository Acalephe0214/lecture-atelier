# Lecture Atelier · 听课之间

Turn lecture, talk or meeting **recordings into reviewable transcripts and source-linked notes**. A local workspace for listening, editing, organizing and exporting.

[Download alpha.2](https://github.com/Acalephe0214/lecture-atelier/releases/tag/v0.1.0-alpha.2) · [中文说明](README.zh-CN.md) · [Start here](#start) · [Full workflow](#workflow) · [Using Tingwu](#tingwu) · [Feedback](#feedback)

[![Software checks](https://github.com/Acalephe0214/lecture-atelier/actions/workflows/checks.yml/badge.svg?branch=codex%2Finitial-publication)](https://github.com/Acalephe0214/lecture-atelier/actions/workflows/checks.yml) · [MIT license](LICENSE) · **Alpha** · macOS / Windows x64 launchers

## What goes in? What comes out?

- **Input:** audio/video, or a TXT, SRT, VTT or supported JSON transcript. Add both for timed playback.
- **Output:** an editable transcript, optional AI revisions and notes, and files such as Word, PDF or Markdown; optional Notion pages.
- **What it does:** get a transcript → listen and edit → organize with AI → check sources → export. Use local Whisper or import a transcript from Tingwu or another service.

**Try it with no API key:** start the app and choose **Explore fictional demo**. Read, edit, save and export before installing speech components or configuring a model.

## What do I need to provide?

For **manual review**, bring a transcript. For **local recognition**, install `speech`. For **AI notes**, provide an API base URL, exact model ID and key.

<details>
<summary>Configuration checklist for each feature</summary>

| What you want to do | Required input or configuration |
| --- | --- |
| Import, manually review and export | Create a course/session and choose a transcript. Add the same recording for playback. No API key. |
| Transcribe on this computer | Add the recording, select its actual language and install `speech`. No speech API key. |
| Transcribe with Tingwu, then import | Sign in on the Tingwu website, confirm the recording upload and download its full transcript. Do not enter Tingwu credentials or Alibaba Cloud AccessKeys in this app. |
| AI corrections, overview and notes | In **Settings & glossary → LLM**, enter your provider's **API base URL, exact model ID and API key**. A brand name or website password is not a model ID/key. |
| Send notes to Notion (optional) | A **Notion connection token and parent page link/ID**; grant that connection access to the parent page in Notion. This is separate from the model API key. |

</details>

<a id="preview"></a>

## See the workspace

[![Fictional transcript review and notes workspace](docs/images/workspace.png)](docs/images/workspace.png)

*Current interface with fictional demo material. The example's source-copy cards are for exploring the workflow, not model-generated summaries.*

- **Listen and revise:** timed source links, paragraph reading, manual edits and AI changes you can accept or reject.
- **Organize by purpose:** class, talk, discussion and meeting modes; overview, detailed notes and traceable source references.
- **Resume interrupted work:** saved AI batches, completed-note drafts and provider-reported tokens for new requests.
- **Keep or take away:** local session storage, recoverable removal, document exports and optional one-way Notion delivery.

<details>
<summary>Explore the five-step Journey map</summary>

![Five-step journey map inside Lecture Atelier](docs/images/journey-map.png)

Open **Journey map** in the upper-right corner. Select a stop to see the relevant control and its output, then jump to that part of the app. Courses, sessions and audio links can be moved to the **Recycle bin** and restored; original media files remain on disk.

</details>

<a id="start"></a>

## First start

1. Download **[LectureAtelier-0.1.0-alpha.2.zip](https://github.com/Acalephe0214/lecture-atelier/releases/download/v0.1.0-alpha.2/LectureAtelier-0.1.0-alpha.2.zip)** and extract the entire folder. Choose the user package, rather than GitHub's automatic source archives, for the guided setup.
2. **Mac:** open `LectureAtelier.app` or `launch.command`. **Windows 10/11 x64:** open `launch-windows.bat`.
3. Open <http://127.0.0.1:8767/>. Choose English or Chinese in the upper-right corner, then **Explore fictional demo**. Edit a sentence, save, refresh and export TXT. The demo is not a model-quality benchmark.

With Python 3.10+ installed, run this from the project folder instead:

```sh
python3 app.py --open
```

Windows CLI: `py -3 app.py --open`. If Python is missing, the launcher guides you through a confirmed project-local runtime download. **Basic mode downloads no Whisper model.** This is a source-based local app, not a signed native installer with all dependencies preinstalled.

<details>
<summary>Optional setup profiles and download sizes</summary>

For optional components, open `setup-mac.command` on Mac or `setup-windows.bat` on Windows:

| Setup option | Purpose |
| --- | --- |
| `basic` (default) | Import, read, manually edit and export non-PDF files. Downloads Python only if missing. |
| `speech` | Local Whisper transcription. Installs speech/media components and downloads a model if no speech backend is configured. |
| `pdf` | PDF export without a speech model. |
| `full` | Both local transcription and PDF. |

Speech setup may need 0.5–1.5 GB downloads and 2–4 GB disk; existing speech settings are retained. Detailed setup: [English guide](FRIEND-GUIDE-EN.html) · [Chinese guide](FRIEND-GUIDE.html).

</details>

<a id="workflow"></a>

## Full workflow: from material to notes

```text
Existing transcript ──────────────────┐
Recording/video → local Whisper ──────┤
Recording/video → Tingwu → import ────┘
                                     ↓
                         Listen and edit the transcript
                                     ↓
                         Optional AI corrections → review
                                     ↓
                         Optional AI overview + detailed notes
                                     ↓
                         Check sources → export / Notion
```

### 1. Create a session and add material

Create a course in the left panel, then a session with a title and date. Meetings can use the same organization. Add the matching audio or video. **Adding a recording stores it locally; it is not consent to cloud upload.**

Select its actual language. Multilingual combinations, such as French + Vietnamese, are available. Recording language, interface language and note output language are independent: choosing an English interface does not translate the transcript.

### 2. Get a transcript — choose one route

**Already have one:** choose **Import transcript** and select a file or paste the full text. Supports TXT, SRT, VTT, segments JSON and supported Tingwu Transcription JSON, without retranscribing. For timed playback, prefer a transcript with real timestamps and add the same recording. Plain TXT is not given invented timestamps.

**Transcribe locally:** install `speech`, then select **Choose a transcription route → Local Whisper** and confirm the language. Installation needs a connection; subsequent local recognition does not upload audio. Video audio is extracted and cached first, preserving the original. Progress and gaps are visible; retry passages, compare/adopt candidates or listen and fill them manually. Retries are bounded and do not guarantee correct recognition.

**Use Tingwu:** if external audio upload is permitted, transcribe on its website and import the result; follow the [walkthrough below](#tingwu). A separate **Configured ASR endpoint** route supports compatible speech gateways. It requires configuration and confirmation to send audio externally, may incur charges, and is not required.

### 3. Listen and edit; optionally request AI corrections

In **Transcript & timeline**, choose paragraph or sentence reading. Use timestamps for playback, then **Listen & edit** or **Review**. Ordinary passages are editable too; original text, source IDs and edit history are retained. Without reliable timing, exact sentence-to-audio navigation is unavailable.

To check terminology or apparent mistakes with AI:

1. In **Settings & glossary → LLM**, enter the API base URL, model ID and key. The app appends `/chat/completions`; do not enter that suffix twice.
2. Choose **AI proofread**, add the topic/domain and relevant terms or name spellings, then confirm sending text.
3. Accept/reject marked suggestions individually or in bulk. Listen back where changes are uncertain.

**AI proofreading does not hear the recording:** it sends text/context, not audio. A proposed correction is not proof of what was said.

### 4. Choose a mode and language, then generate notes

In the right panel, select a class, talk, discussion, meeting or custom purpose, then a note output language: Chinese, English, French, German, Vietnamese, Japanese or matching the source. This affects the next AI generation, not existing transcripts/notes.

Choose **AI overview + detailed notes**, inspect the usage estimate and confirm. Stage progress and provider-reported tokens are displayed. Estimates are not spending caps; the provider's bill is authoritative.

**If generation fails:** successful detail batches and overview groups are checkpointed locally. **Continue from checkpoints** revalidates and reuses exact matching results; only new requests contribute to the current run's token count. Completed detail batches also remain available as a downloadable draft, with an explicit **Use completed notes** action. Existing notes stay intact until you choose to replace them. Changed source text, prompts, output language, model or endpoint invalidate affected checkpoints. A failed request may still be billed; checkpoints cannot recover answers discarded by older versions.

- **Executive overview:** global key information; meeting mode also separates explicit decisions, actions and unresolved questions. Rejected proposals must not become final decisions.
- **Detailed notes:** concepts, arguments, discussions or topics, depending on the purpose, with source links.
- **Generate overview only:** retains existing detailed notes and synthesizes the overview again; notes must already be available.

**Other tools → Source-copy cards** copies original passages without a model. It is not summarization or a substitute for AI notes.

### 5. Review, export or send to Notion

Follow citations to check terminology, omissions, attribution, decisions and owners before marking notes reviewed. **A source link does not guarantee accuracy.** Transcript changes can make linked notes need review again.

- **Full transcript:** use **Export transcript editions** in the middle panel. Choose the snapshot before this AI proofreading pass, a marked edition or a revised edition (accepted changes only). Reading layout merges passages into paragraphs.
- **Overview and notes:** use **Export** in the right panel for Word, Markdown, JSON, PDF and other applicable formats. PDF requires `pdf`; subtitles require real timing.
- **Notion page:** configure a connection token and writable parent page, choose **Send to Notion** and confirm. Each export creates a child page. No audio is uploaded, and it is not two-way synchronization.

<a id="tingwu"></a>

## How to use Tingwu

Use the [Tingwu application website](https://tingwu.aliyun.com/home); **this route does not require the Alibaba Cloud developer API**. The [official introduction](https://help.aliyun.com/zh/tingwu/product-introduction/) distinguishes personal website use from API integration. Controls, export choices, languages and quotas may change: use what your account actually shows. No free allowance or recognition-quality guarantee is made here.

### Operate the website yourself

1. Add the recording to the target session here. Select **Choose a transcription route → Tingwu · Browser handoff** and confirm preparation of instructions. The task is now **prepared, not uploaded**.
2. Choose **Open Tingwu** and sign in on the website. Handle account selection, QR codes and verification yourself. This app stores no Tingwu passwords or cookies.
3. Find the current audio/video upload or file-transcription entry. Select **this recording**, check language, file limits, quota and fees, and confirm permission to send it externally before submitting. This cloud route does upload audio to Tingwu.
4. Wait for recognition, then open the **full transcript**. Do not substitute an abstract, chapter overview or polished summary for source text.
5. From the export options actually available, prefer timestamped **SRT**; otherwise use **TXT**. If you already have official Transcription JSON, its supported structure can also be imported. Word is not a supported transcript input here; extract its body to TXT first if necessary.
6. Return to the **same session** here. Choose **Import the downloaded transcript** or **Import transcript**, set the source to **Tingwu**, choose the downloaded file and import.
7. Check text, timestamps and correspondence with the local recording. Back up before replacing an existing transcript: old text/notes remain in the JSON export history, but one-click transcript restoration is not implemented. Continue to correction and notes; **do not run full local Whisper again just because the transcript came from Tingwu**.

You can also use Tingwu independently, then create a session here, add the same recording and import its transcript. Preparing an in-app handoff is optional.

### Ask a browser-capable assistant to help

<details>
<summary>Optional browser handoff instructions</summary>

Choose **Copy for a browser assistant** in the handoff window and give it to a trusted assistant with actual browser and local-file-upload capabilities. Instructions include the recording path and return-session URL. A text-only chatbot cannot perform those browser actions.

The app does not launch an assistant, sign in or upload automatically. You still handle verification and upload consent. Stop for confirmation if credits are insufficient or new charges appear; no automatic purchase. Instructions contain private paths: do not post them in public repositories or issues. After download, complete steps 6–7 above.

</details>

<a id="feedback"></a>

## Help improve the app

Choose the report that matches your experience:

- [Installation help](https://github.com/Acalephe0214/lecture-atelier/issues/new?template=installation.yml) — launcher, runtime or optional-component setup.
- [Report a bug](https://github.com/Acalephe0214/lecture-atelier/issues/new?template=bug.yml) — a reproducible UI or workflow failure.
- [Report output quality](https://github.com/Acalephe0214/lecture-atelier/issues/new?template=output-quality.yml) — missing text, wrong citations, invented decisions or repeated costly failures.
- [Suggest a feature](https://github.com/Acalephe0214/lecture-atelier/issues/new?template=feature.yml) — the task you want to complete and what gets in the way.

Include the app version, platform and first failing step. Use a small fictional example and redact screenshots; keep recordings, real transcripts, keys and `.runtime/` private. For an independent first trial, follow the [short checklist](docs/TRY-IT.md).

## Data, limits and further reading

Recordings, transcripts, revisions and notes default to local `.runtime/` storage; the server binds only to `127.0.0.1`. Local Whisper does not upload audio. AI corrections/notes send relevant text to your endpoint; Tingwu or a speech gateway receives the recording; Notion receives confirmed note exports. Keys are local but not app-level encrypted. See [PRIVACY.md](PRIVACY.md).

This is an alpha. Automated checks mainly validate software behavior, not representative accuracy. Clean end-user Windows installation, real recognition and summary quality need further validation. Windows ARM64 is unsupported. Supplementary slide/personal-note upload is planned, not implemented. See [verification scope](docs/VERIFICATION.md) and [roadmap](docs/ROADMAP.md).

[Architecture](docs/ARCHITECTURE.md) · [First-use checklist](docs/TRY-IT.md) · [Source packaging](docs/PUBLISHING.md) · [Report a problem](https://github.com/Acalephe0214/lecture-atelier/issues/new/choose)

## Development

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -p 'test_*.py'
node tests/test_i18n.cjs
node tests/test_paragraphs.cjs
node tests/test_playback.cjs
node tests/test_panels.cjs
node tests/test_journey.cjs
```

Tests use temporary synthetic workspaces; some media checks need FFmpeg. See [verification](docs/VERIFICATION.md) for optional test dependencies and evaluation limits.

## License

Project source uses [MIT](LICENSE). Upstream software/models retain their own licenses: see [third-party notices](THIRD-PARTY-NOTICES.txt) and [license copies](licenses/README.md). The repository and source archives contain no third-party runtimes, model weights or fonts. Developed with AI-assisted coding; local speech recognition integrates upstream Whisper implementations.
