# Changelog

## 0.1.0-alpha.2 — 2026-10-19

- Save and revalidate private LLM answer checkpoints; explicit retries reuse matching successful detail batches and overview groups.
- Retain completed detail drafts on later failure, with local download/adoption and concurrent-edit protection.
- Display checkpoint reuse, failed batch/group location and new-request-only token accounting.
- Add a bilingual five-step journey map and clearer primary actions; fold supporting controls and explanations.
- Add confirmed course/session/audio removal, a recoverable local recycle bin and active-job/conflict guards. Original media files remain on disk.
- Add synthetic recovery, removal and bilingual interface regressions; retain documented real-world validation limits.
- Refresh English/Chinese repository previews and setup navigation; add an output-quality feedback form and version-specific user-package links.

## 0.1.0-alpha.1 — 2026-10-19

First versioned alpha distribution.

- Separate basic, PDF, speech and full setup profiles; basic startup downloads no speech model.
- Mac launcher starts the basic application independently of optional model installation.
- Retain configured speech backends and collect dependency notices before model downloads.
- Close SQLite backup handles explicitly and avoid reverse-DNS lookups during loopback startup.
- Publish terminal note-job states only after diagnostic preparation and final snapshot persistence.
- Add cross-platform software checks, installation-report templates and an offline human-reference scoring protocol.
- Provide transcript review, local Whisper, source-linked AI notes, exports and optional Notion delivery.

Platform checks and remaining manual-validation work are listed in the repository's [verification document](https://github.com/Acalephe0214/lecture-atelier/blob/codex/initial-publication/docs/VERIFICATION.md).
This is a source-based first-run distribution, not a signed or preinstalled offline application.
