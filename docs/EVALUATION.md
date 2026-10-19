# Small-scale quality evaluation

Engineering tests and recognition/summarization quality are separate evidence.
Keep consented recordings and references outside the public repository. Use
synthetic or separately authorized material for any public examples.

## Transcripts

1. Select clips before looking at the output. Log duration, language, recording
   conditions, model/version, decoding settings and elapsed time locally. Keep
   deliberately selected failures in a separate challenge set.
2. Decode the same clips through each system being compared. If evaluating the
   retry guard, use identical first-pass settings. Report actual retry/gap counts.
3. Listen to each clip and prepare a reference. Record whether it was independently
   transcribed or edited from model output; the latter can introduce anchoring
   bias. Do not mark an unreviewed model output as a human reference. Mark unknown
   passages for review rather than inventing words; leave such clips unverified
   until the intended evaluation scope is resolved.
4. Score only fully verified references. Separately count terminology errors,
   repetitions and omissions by listening; character agreement does not cover
   every important error.

The standard-library scorer accepts this JSON structure (fictional example):

```json
{
  "cases": [{
    "id": "demo-01",
    "language": "en",
    "reference_status": "human_verified",
    "reference_method": "independent_listening",
    "reference": "The deadline is Monday.",
    "hypotheses": {
      "raw_decoder": "The deadline is Monday.",
      "guarded_workflow": "The deadline is Monday."
    }
  }]
}
```

`reference_method` may also be `edited_model_output`. Other statuses, including
`draft` and `missing`, are excluded. No verified references yields
`pending_reference`, **not** a zero error rate.

```sh
python3 evaluate_transcripts.py private-reviewed.json --output private-metrics.json
```

The output path must be new. The report omits transcript text, audio and source
paths, but still inspect case IDs and other metadata before sharing it.
CER counts Unicode code points after NFC normalization, case folding and removal
of punctuation, symbols and whitespace. WER uses whitespace-separated tokens;
it is not meaningful linguistic word segmentation for unsegmented Chinese or
Japanese, and Vietnamese whitespace tokens are often syllables. Prefer CER in
those cases and document the convention. Diacritics remain significant.

Aggregate rates are micro-averaged (total edits / total reference units), not
averages of clip percentages. Insertion-heavy errors can exceed 100%. Compare
systems only on the same clips: inspect `paired_system_coverage` and case counts.
Small single-environment samples do not establish representative accuracy.

## Notes and meeting decisions

Before calling a real model, prepare a small human checklist for each recording:
key facts, explicit decisions, rejected proposals, unresolved questions and any
stated owners/deadlines. Do not grade using another model as the sole judge.

For each generated output, manually count:

- Expected facts/decisions recovered, and important omissions.
- Unsupported decisions/actions, including proposals that were later rejected.
- Incorrect owners, deadlines, speaker attribution or specialist terminology.
- Source links that exist versus source passages that actually support the claim.

Record the prompt/mode, output language, model version, provider-reported usage
and review time. Compare any summary-only baseline on the same material; do not
claim superiority over a commercial service without a matched comparison.
API use needs separate consent and is not part of the offline transcript scorer.

No model-quality results are claimed merely because this protocol or scorer exists.
