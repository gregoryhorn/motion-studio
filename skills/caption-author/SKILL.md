---
name: caption-author
description: "Align real speech and verify caption export parity."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Caption author

## When to use

Transcribe, correct, align and style captions from real speech. Exclude timing from script text alone, mandatory prewritten SRT and captioning intentional silence.

## Inputs and retained outputs

Required: Actual audio/video, language hint, approved corrections, style and rational frame rate.

Produce: Timed transcription/alignment, edit history, sidecars and matched preview/candidate frames. Attach each output to its current
project and applicable scene/asset revision; retain editable source and actual
bytes, not only a screenshot, URL or completion message.

## Authority and execution boundary

Follow the shared production instructions in `motion-studio:studio-produce`
before this specialist procedure; load that qualified skill, not a relative
cross-skill file link. Resolve current project/scene/asset IDs, expected revision,
input hashes and selected binding from actual tools. Preserve supplied provenance/
attribution facts without demanding rights clearance. Unknown or restricted rights
and absent licenses do not block production, release or packaging. Work only on declared
task-owned candidates; preserve immutable sources and approved outputs. Changes
invalidate only affected descendants. Record binding/version, job/attempt, input
and output hashes and inspected frame/sample coverage in the project.

This is independently authored guidance, not a qualified runtime route. Linux
identifies the authoring host only; adapter/platform production support is not
established. Use only advertised public actions and schemas. Missing engines,
`NOT_IMPLEMENTED`, absent actions or unsatisfied required features mean blocked:
name the operation/feature and smallest remedy, preserve existing artifacts and
return the gap. Do not fabricate media, timing, receipts or acceptance. Do not
install dependencies/models, modify configuration, upload, spend or substitute a
provider without separate authority. Optional unsupported work need not block
unrelated valid outputs. Binding changes require a revised plan, potentially new
native source, not a promise of lossless translation.

## Required and conditional capabilities

Require `speech.transcribe@1` with `speech.segments` or `speech.words` as
needed, `speech.align@1` when lexical/timing edits require it, `caption.layout@1`,
`caption.render@1`, `caption.export@1`, `media.probe@1` and
`inspection.visual@1`. Inspect audio through `inspection.audio@1`.
Word highlighting requires actual word timing and `caption.word_highlight`;
`text.rtl` and `text.shaping` are conditional on language/treatment. Do not demand
word timing for plain segment captions or create words from segment intervals.

## Procedure

1. Resolve the exact source audio take/hash, language hint, rational frame rate,
   requested delivery variants and style/fonts. Extract actual audio if necessary
   with `media.extract_audio@1`. Intentional silence needs no invented transcript;
   preserve actual silence evidence and an empty caption source when applicable.
2. Transcribe/listen to real speech at supported granularity. Retain provider
   timing/confidence or null, original transcript and source-sample boundaries.
   A script or prewritten SRT may guide corrections but cannot prove speech timing.
3. Classify edits through public `motion_caption` actions: a verified spelling/name
   correction can retain timing; insertions, deletions or reordered spoken words
   need alignment to that audio and timing review. If alignment is unavailable,
   keep `needs_alignment`/`review_needed`; do not stretch intervals speculatively.
   Use `motion_caption.timing_review` only with actual timing evidence/authority.
4. Pin CaptionPlacement, style, fonts and renderer fingerprint for each variant.
   Layout and render previews from those same artifacts; verify line breaks,
   overflow, reading duration, shaping and safe placement. Any word-highlight
   request without word timestamps is blocked while plain captions may remain valid.
5. Export delivery SRT/VTT/ASS with the pinned placement, explicit rounding and
   delivery time origin; label a source-origin export as source, not a deliverable
   sidecar. Burn requested captions using the same pinned layout and candidate.
6. Decode the final candidate at identical preview frame indices, checking text,
   onset/offset and position including corrected boundaries. Retain sidecar hashes,
   edit history and actual audio/frame coverage. New narration invalidates its
   alignment and caption descendants; spelling-only changes do not regenerate the
   approved voice take.

## Verification

**SK-S55-output (future empirical acceptance, not yet passed):** Correct a name without retiming then insert a spoken word: spelling preserves timing, lexical edit requires alignment/review; preview and decoded export match at identical frames without invented word timing.


## Pitfalls and handback

Report actual artifacts separately from intended outputs and unresolved gaps.
Retain failed/partial jobs and any prior approved version. Compilation, selecting
a binding, source inspection and this authoring test are not production evidence;
a newly rendered preview is an execution job. Submit only a frozen authorized
plan, reconcile uncertain effects before any retry, and use normal host approval
for typed handoffs. Return the current revisions and real artifact handles to
`motion-studio:studio-produce`; candidate encode, decode/measurement, frame/audio/
playback review and exact-byte promotion remain required when applicable. Never
turn specialist judgement into user approval or mark a route exercised from mocks.
