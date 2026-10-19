# Verification

The repository contains engineering regression checks. Transcription accuracy and summary quality have not yet been benchmarked against a representative evaluation dataset.

## Available checks

Synthetic tests cover transcript parsing, real/unknown timestamps, source-reference validation, manual edits, history, stale-result protection, task consent, local HTTP endpoints, streaming-response parsing, usage accounting, malformed/truncated responses, overview grouping, exports, clean-workspace behavior and source-package privacy.

Some integration checks run a loopback simulated SSE model. They exercise the application pipeline and transport, but their answers are constructed fixtures: they do not measure an LLM's reasoning or fidelity. Notion writes are mocked. Audio/video checks use synthetic samples; some require FFmpeg. PDF checks require optional libraries and may skip when unavailable.

Local development has also included an English synthetic-speech smoke test with an existing Whisper model and a checkpoint rerun. That demonstrates one setup path, not multilingual accuracy. Browser checks performed during development do not establish Windows compatibility. Clean end-user Windows setup, broad language combinations, noise-reduction quality and summary quality remain unvalidated.

## Recorded validation — 2026-10-19

- Alpha.2 local software regression: 349 Python tests and 233 buildless JavaScript assertions/checks passed using synthetic fixtures/mocked services. Recovery tests include a failed third detail batch, a failed final overview merge, restart reuse, invalid/corrupted citations, usage accounting and protection of manual edits.
- Local Chrome UI checks exercised Chinese/English desktop and mobile layouts, the five-step map, audio/course removal and restoration, cancellation of removal, and original transcript retention. A separate synthetic-provider browser run failed after three requests, adopted the completed draft locally, then completed with one new request and two reused batches. External browser requests were blocked. This is recovery/interaction verification, not a real-model quality result or independent user trial.
- [Cross-platform run at b6f918d](https://github.com/Acalephe0214/lecture-atelier/actions/runs/39242163440): Linux, macOS and Windows jobs passed. Mac and Windows exercised basic setup with the hosted runner's existing Python; this did not test runtime downloads or optional speech installation.
- Local regression run at the same revision: 319 Python tests passed. The buildless JavaScript checks also passed. Test counts include synthetic/mocked checks, not quality samples.
- A private local study decoded eight consented Chinese classroom clips, each 120 seconds (16 minutes total), using an already installed MLX Whisper backend with quantized weights. A matched raw decoder and guarded workflow used the same first-pass settings; no detected gaps or retry-triggering anomalies occurred in these clips. This does **not** establish transcription correctness or guard effectiveness on difficult cases.
- Human references are still pending. No CER/WER, summary-quality score, broad multilingual result or third-party usability success is claimed. Recordings, transcripts, model files and local paths are not distributed.

The [evaluation protocol](EVALUATION.md) and offline scorer distinguish missing references from measured results. Independent installation reports use [TRY-IT.md](TRY-IT.md).

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
node tests/test_journey.cjs
```

Integration tests require loopback listeners. Optional dependencies are not installed by the tests; unavailable components are reported as skips. [GitHub Actions](https://github.com/Acalephe0214/lecture-atelier/actions/workflows/checks.yml) targets Linux, macOS and Windows with Python 3.12 and Node.js 22, including no-model basic setup checks on Mac and Windows. Current job results, not the matrix definition, establish which checks passed.

Hosted-runner checks do not establish clean end-user installation, OS security prompts, real speech quality or browser usability. Independent first-use trials are tracked separately using [TRY-IT.md](TRY-IT.md). POSIX file-mode checks apply only on POSIX; Windows file ACLs require separate validation.

## Remaining quality-evaluation work

Complete human references for the private clips and add deliberately difficult samples, clearly separating ordinary samples from selected failure cases. For summaries, use expected decisions/non-decisions and measure terminology errors, omissions, attribution errors and invented decisions/actions separately. Record model/version/settings, time and actual provider-reported usage. Keep failed examples and human review criteria. None of those results are claimed in this release.
