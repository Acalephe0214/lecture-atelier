# Privacy and data boundaries

Lecture Atelier is a local application, not a hosted service. It binds to `127.0.0.1`. Do not expose its port on a public interface or treat it as a hardened multi-user deployment.

## On this computer

`.runtime/` can contain recordings, SQLite data, transcripts, manual edits, generated notes, checkpoints, audio caches and configuration including API keys. Secrets are not encrypted by the app: protect your account, disk and backups. File-permission behavior varies by platform.

CLI-registered local sources can remain outside the project. Their paths and cached text are private; backing up `.runtime/` alone does not back up those external originals. Ordinary web requests cannot register arbitrary filesystem paths.

First setup may download dependencies and model weights. Installed local transcription then runs without a speech API and does not upload recordings. Basic transcript import/edit/export does not call a model.

## Explicit external operations

- AI proofreading and note generation send relevant transcript text and configured context to the chosen endpoint. Text-only proofreading does not hear the audio.
- An optional speech gateway sends the selected recording to the configured gateway, after separate confirmation.
- Notion export sends the selected overview and detailed notes to Notion, potentially including quotations. It creates a child page and is not automatic synchronization.
- Browser handoff instructions for an external transcription website may contain a private local path. They do not mean the app has logged in, uploaded or transcribed anything.

Do not send confidential material to a provider just because it is compatible with the API. Obtain permission for recordings and course/meeting materials, and check your institution's and provider's rules. Uploaded media and reference documents are untrusted content, not instructions to the app.

## Sharing and bug reports

Never upload a used installation folder. Exclude `.runtime/`, environments, models, personal manifests, audio/video, transcripts, keys and diagnostics. JSON exports and failure diagnostics can contain private source-derived text even when credentials are excluded.

Use synthetic material for screenshots and issue reports. Do not paste API keys, cookies, raw logs, private provider responses or other people's speech into a public issue. Local privacy checks and `.gitignore` reduce mistakes; they are not a security audit or a substitute for reviewing Git history.
