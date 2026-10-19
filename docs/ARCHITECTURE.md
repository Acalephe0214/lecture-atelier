# Architecture / 程序分工

The basic app is a Python standard-library HTTP server, SQLite storage and a buildless browser interface. Optional packages add local speech inference, audio/video handling and PDF export. No LLM request happens simply because a session is opened.

| Layer | Files | Input → work → output |
| --- | --- | --- |
| Browser | `static/app.js`, `static/index.html`, `static/style.css` | User actions → local HTTP requests → editable transcript, audio controls and notes |
| Interface helpers | `static/revisions.js`, `delivery.js`, `i18n*.js`, `panels.js` | Revisions, estimates and explicit UI text → review controls, language handling and resizable panels |
| API | `app.py` | Local requests → validate action, consent and snapshots → job state or updated session |
| Persistence | `store.py` | Validated records → SQLite transaction/private settings → saved state and history |
| Removal and recovery | `recycle.py` | Exact preview + confirmation → transactional record removal → local recycle bin and conflict-checked restore; original media retained |
| Speech jobs | `local_transcription.py`, `local_repair.py`, `asr_checkpoints.py` | Original audio and language choice → worker, guards, retries/checkpoints → unreviewed text or explicit gaps |
| Audio preparation | `core/audio_prepare.py`, `audio_processing.py` | Media → audio extraction/listening copies → private caches; originals retained |
| Model adapters | `core/pipeline.py`, `core/chat_stream.py` | Approved text and endpoint settings → structured request/SSE → validated proposals or notes |
| AI proofreading | `correction_jobs.py`, `core/redline.py` | Original text + context → minimal proposed changes → accept/reject marks and revision history |
| Notes and overview | `note_jobs.py`, `core/overview.py`, `core/workflow.py` | Notes + source evidence + scene rules → grouped synthesis → overview with real references |
| Paid-work checkpoints | `note_checkpoints.py` | Exact request digest → private answer checkpoint + revalidation → reuse successful batches/groups; failed responses stay ineligible for reuse |
| Usage estimates | `core/usage_estimate.py` | Actual/planned payloads → character-based ranges → input/output estimates; not a budget cap |
| Local export | `core/paragraphs.py`, `proofread_export.py`, `word_export.py`, `pdf_export.py` | Chosen edition/layout → serialization → readable files without a model call |
| Notion | `core/notion_export.py` | Explicitly approved overview/notes → one-way write → new child-page status |

## Example: editing while listening

The browser opens a paragraph editor containing the underlying source sentences and their real timecodes. Save sends changed sentences plus the text/status snapshot from when the editor opened. The server validates the whole batch and commits it atomically. A newer retry result or edit causes a conflict instead of being overwritten. Initial text and history remain; related reviewed notes become stale or need review.

Reading paragraphs are a presentation layer. They do not merge database source IDs or fabricate subtitle timings.

## Example: generating notes

Full generation extracts detailed notes and then synthesizes an overview. Overview-only keeps existing notes. Untouched source-copy cards can be represented as source indexes without sending their duplicated text; original evidence remains available. Uncited source passages are included rather than silently ignored.

First-pass planning is shared with estimates. Later levels depend on model output, so their count and token usage cannot be known exactly beforehand. Source IDs and decision quotations are structurally checked; this does not verify semantic correctness. Failed model requests are not automatically retried, and stale results cannot overwrite concurrent edits.

Every returned answer is saved in private SQLite before validation, with hidden reasoning and request credentials omitted. Only validated responses can be reused. Digests include the session, endpoint and complete request payload (source, model, language, glossary and prompts). Detail drafts are stored separately from current notes; adoption requires confirmation and a matching source/notes snapshot. Reused calls contribute no provider usage to the new run. Preview ranges remain conservative full-run estimates with reusable checkpoint counts listed separately.

## Three independent languages

UI language controls interface text; recording language guides speech recognition; output language guides generated notes. Do not translate stored transcripts through a page-wide DOM translator. Custom prompts and verbatim evidence are preserved.

## Future reference materials

Slides and personal notes will need a separate document store, page/section anchors, external-send consent and source-type-aware citations. They must not be inserted as alleged spoken transcript segments. See [ROADMAP.md](ROADMAP.md).
