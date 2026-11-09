---
name: audio-post
description: "Mix approved stems and measure the actual master."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Audio post

## When to use

Mix and master approved audio stems. Exclude inventing narration or treating one LUFS target as universal.

## Inputs and retained outputs

Required: Timed stems, cue sheet, sample rates and explicit loudness/peak targets.

Produce: Editable mix recipe, actual master, loudness/peak/sync receipt. Attach each output to its current
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

Require `media.probe@1`, `audio.mix@1`, `audio.measure@1` and
`inspection.audio@1`. Normalization uses explicit mix targets, not an invented
normalize operation. Require `audio.sample_exact` when cue accuracy demands it.
Use `media.transform@1` with an explicit sample-conform record only when rates
need conversion. Final mux/encode is conditional on the requested deliverable.

## Procedure

1. Inventory approved stems and their sample rates, channel layouts, offsets,
   trim ranges and hashes. Listen for pre-existing clipping and latency; do not
   overwrite a defective original. Obtain explicit target LUFS, true-peak ceiling,
   measurement tolerance and output duration; a platform name is not a target.
2. Build the editable CueSheet using ordered input indices, start/source-in
   samples, duration, gain and fades at the output sample rate. Record resampling
   and frame-to-sample rounding. Verify fades fit their cues and tails fit the
   intended program; do not hide truncation by shortening the mix.
3. Set speech/music/SFX balance and authorized ducking in the binding's registered
   options. If it lacks required ducking, return that gap or propose an explicit
   revised mix, not an undocumented approximation. Preserve the approved voice
   take; narration synthesis belongs to `motion-studio:voice-produce`.
4. Freeze the source recipe and render the mix through the selected binding.
   Collect actual audio and the editable recipe. Measure integrated loudness,
   true peak and clipping on that final audio, not on an input or an intermediate.
   Compare against the declared targets/tolerance and retain the measurement.
5. Audition speech, cue attacks, tails and program boundaries with actual sample
   coverage. Check sync against the authoritative timeline and final mux if
   requested. Revise gains or placement only in a new candidate; changing the mix
   invalidates downstream encodes/audio reviews, not unchanged visual sources.

## Verification

**SK-S04-output (future empirical acceptance, not yet passed):** At a fixture's declared -16 LUFS target and -1.5 dBTP ceiling, measure final mix within predeclared tolerance, audition intelligible narration and verify no changed source stems.

Use the -16 LUFS/-1.5 dBTP fixture only for that fixture. Retain its measured
values, tolerance decision, intelligibility judgement and unchanged-stem hashes.
A meter pass alone does not prove narration is understandable.

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
