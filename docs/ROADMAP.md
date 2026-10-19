# Roadmap / 下一步：参考课件与课堂笔记

The following feature is **proposed, not implemented**. It is not advertised as an existing upload route.

## Why this is useful

Teacher slides can clarify terminology, notation and lecture structure. Personal notes can identify emphasis or questions that a transcript alone misses. They should supplement recorded evidence, not turn slide text or a student's interpretation into something the teacher supposedly said.

## First useful version

1. Attach reference material to one session, separately from audio/transcript. Start with text-based PDF and PPTX slides, plus TXT/Markdown notes. Legacy binary PPT, scanned-slide OCR and handwriting can follow later; unsupported files must be clearly reported.
2. Extract text locally and preview it before any model call. Preserve filename, slide/page number or note section, and distinguish `teacher_slides` from `personal_notes`. Do not execute slide macros, embedded objects, scripts or links. Detect empty extraction rather than claiming a scanned page was understood.
3. Let the user choose which documents/sections are included. Show the additional input/estimated cost and confirm external disclosure. Uploaded files are untrusted data, not system instructions. Files are not automatically added to GitHub or Notion.
4. Generate notes using three separate evidence types: transcript source IDs with real timecodes; slide references with page numbers; personal-note references with sections. No invented time alignment. A source label is required for claims based only on supplementary material.
5. Show conflicts or unsupported additions explicitly. For example: “slide lists a method, but the recording does not confirm it was discussed”; “personal note says Friday, recording says the Friday proposal was rejected.” Do not silently choose a winner or invent a final decision.
6. Keep attachment history and provide detach/delete controls, including dependent cache cleanup and explicit warnings for stale notes. Adding/removing an attachment must invalidate relevant estimates/results. Handle model context limits without silent truncation.

## Suggested output policy

> Recorded speech is evidence of what was said, not guaranteed truth. Slides are background teaching material; personal notes are the author's observations. Cite each source type distinctly. Do not invent speaker statements, decisions, agreement or timing from slides or notes. Report unresolved conflicts and label context-only additions.

参考资料可帮助理解和术语校对，但不能凭课件补写缺失录音。个人笔记里“我觉得老师的意思是……”也不能自动改写成“老师明确指出……”。校对仍应以最小修改、可回听和人工确认优先。

## Acceptance cases before release

- Slide-only content stays labeled slide-only; it never appears as a verbatim transcript.
- A rejected proposal in audio does not become an action just because slides or notes mention it.
- Page/section anchors survive export and reopening; no fabricated timestamps are added.
- Empty PDFs, corrupt PPTX, large documents and unsupported scanned pages fail safely.
- Prompt-injection text in references is treated as data, not executed or followed.
- Deselecting references excludes them from outgoing requests; attachments and private caches are excluded from public exports unless explicitly selected.

## Other follow-ups

Portable browser checks, Windows hardware verification, a small quality-evaluation dataset, and more multilingual/noisy-recording cases. No delivery date or accuracy guarantee is attached to this list.
