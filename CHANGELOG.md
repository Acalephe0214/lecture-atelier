# Changelog

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
