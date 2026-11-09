---
name: sound-cues
description: "Source and place authorized effects on exact cue events."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Sound cues

## When to use

Source/generate and place purposeful sound effects. Exclude adding unrequested SFX or silently invoking a paid generator.

## Inputs and retained outputs

Required: Scene event/frame, sound intent, spend/data policy and any supplied source facts and audio target.

Produce: Staged SFX with provenance, sample/frame cue sheet and audition proof. Attach each output to its current
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

For acquisition use `asset.search@1` plus `media.stage@1`, or selected
`audio.generate@1` with `kind:sfx`; neither is needed for an already staged
approved effect. Require `media.probe@1`, `audio.mix@1` and
`inspection.audio@1`; require `audio.sample_exact` for sample-exact placement.
Measure through `audio.measure@1` where the target requires peak/loudness checks.

## Procedure

1. Identify the purposeful event/frame, intended emphasis, permitted acquisition
   route, spend/data limits and any supplied source facts. Do not add sounds merely because a cut
   exists. Determine available approved assets before proposing search/generation.
2. Acquire only the selected effect: retain search source and any supplied license facts or
   frozen generation prompt, provider destination and observed charge/unknown
   cost. A remote URL is not a staged asset; collect bytes and inspect actual
   format, rate, duration and decay. Keep missing rights unknown; do not infer clearance or block on it.
3. Audition the asset to distinguish leading silence from the audible attack.
   Compute cue placement from rational frame time to output samples with an
   explicit rounding policy; retain source-in trim, gain, fades and tail duration
   in the canonical CueSheet. Record any explicit sample-conform conversion.
4. Render the contextual cue mix, leaving room for decay or obtaining approval
   for an intentional trim. Audition the reveal against speech and other effects;
   a waveform start need not be the perceptual attack. Preserve source and update
   only this cue and dependent mix/encodes.
5. Return staged asset, provenance, cue sheet and actual audition coverage. Use
   `motion-studio:audio-post` for overall mix mastering and
   `motion-studio:procedural-audio` when authoring a deterministic score is the
   request; those are not automatic paid generation fallbacks.

## Verification

**SK-S53-output (future empirical acceptance, not yet passed):** A reveal chime begins at the declared cue and keeps its decay without masking speech; source, any supplied license facts and any generation destination are recorded.


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
