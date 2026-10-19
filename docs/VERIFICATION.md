# Verification

The repository contains engineering regression checks. Transcription accuracy and summary quality have not yet been benchmarked against a representative evaluation dataset.

## Available checks

Synthetic tests cover transcript parsing, real/unknown timestamps, source-reference validation, manual edits, history, stale-result protection, task consent, local HTTP endpoints, streaming-response parsing, usage accounting, malformed/truncated responses, overview grouping, exports, clean-workspace behavior and source-package privacy.

Some integration checks run a loopback simulated SSE model. They exercise the application pipeline and transport, but their answers are constructed fixtures: they do not measure an LLM's reasoning or fidelity. Notion writes are mocked. Audio/video checks use synthetic samples; some require FFmpeg. PDF checks require optional libraries and may skip when unavailable.

Local development has also included an English synthetic-speech smoke test with an existing Whisper model and a checkpoint rerun. That demonstrates one setup path, not multilingual accuracy. Browser checks performed during development do not establish Windows compatibility. Windows hardware, broad language combinations, real classroom noise and summary quality remain unvalidated.

## Reproduce software checks

Use an isolated Python environment; tests create temporary data and never require real API keys. Python 3.12 is the development baseline.

```sh
python3 -m venv .venv
# Activate it using the command appropriate for your shell.
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p 'test_*.py'
```

With Node.js available, these checks need no npm packages:

```sh
node tests/test_i18n.cjs
node tests/test_paragraphs.cjs
node tests/test_playback.cjs
node tests/test_panels.cjs
```

Integration tests require loopback listeners. Optional dependencies are not installed by the tests; unavailable components are reported as skips. [GitHub Actions](https://github.com/Acalephe0214/lecture-atelier/actions/workflows/checks.yml) runs the software checks on Linux with Python 3.12 and Node.js 22.

## Next quality-evaluation work

Build a small consented or synthetic evaluation set, with recording language, noise conditions, reference transcript and expected decisions/non-decisions. Measure terminology errors, omissions, attribution errors, invented decisions/actions and unrecognized gaps separately. Record model/version/settings, time and actual provider-reported usage. Keep failed examples and human review criteria. None of those results are claimed in this release.
