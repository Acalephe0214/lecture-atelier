# Lecture Atelier — project guidance

This is a local Python standard-library + SQLite + buildless HTML/JS app. It is
not a hosted site or a request to publish anything. LectureAtelier.app is only
an unsigned Mac launcher; it is not a notarized offline native binary. The
cross-platform first-run installer is documented at the top of CODEX_SETUP.md.

## When asked to install or start this package

Read `CODEX_SETUP.md` and run `check_setup.py --json` with an available supported
Python first. Start the basic app before optional ML setup. `START-HERE.html`
and `FRIEND-GUIDE-EN.html` are the human onboarding entry points. Work from the
extracted project directory; merely attaching a ZIP does not start the app.

Ask before dependency/model downloads if not already explicitly authorized.
Use a project `.venv`; do not alter system Python, install a package manager,
use sudo, remove quarantine flags, disable security, or create login items
without separate user direction. Never upload recordings during installation,
call paid APIs, invent a successful model test, or overwrite private settings.

Only bind `127.0.0.1`. Reuse a confirmed matching running app; do not kill an
unrelated process occupying the port. Distinguish “server works”, “dependencies
exist”, and “real speech inference tested”. Tell the user which is verified.

## When developing

- Keep UI language distinct from recording language, prompts and source text.
- Translate explicit interface messages only. Never translate stored user data
  or use a document-wide live translator/observer on transcripts and notes.
- Keep `.runtime`, models, keys and user sources private. Package using the
  explicit allowlist in `package_for_friends.py`, not a recursive directory ZIP.
- Prepare public source repositories with `prepare_github.py` and its separate
  explicit allowlist. Keep README claims current and retain LICENSE/licenses/.
  Do not upload, push, choose repository visibility or set a public commit
  identity without the human's direction. Slides/notes upload is roadmap only.
- Preserve manual edits, original recordings, source IDs and review status.
- Do not create agents/subtasks unless the human explicitly requests them.
- If `tests/` is present, verify changed behavior with focused tests. For broad
  checks use `python3 -m unittest discover -s tests -p 'test_[!a]*.py'`, plus
  `test_asr_guard.py`, `test_audio_processing.py`, and Node `tests/test_i18n.cjs`,
  `tests/test_paragraphs.cjs`, `tests/test_playback.cjs`, and `tests/test_panels.cjs`
  when Node is available.
  Loopback HTTP tests may need normal local-server permission. Report untested
  hardware/dependency combinations accurately.
