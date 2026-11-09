---
name: procedural-audio
description: "Compose reproducible scored cues with measured audio."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Procedural audio

## When to use

Compose deterministic synthesized cues. Exclude assuming a browser audio library or pre-authorizing music generation services.

## Inputs and retained outputs

Required: Cue purpose, score/seed, tempo/tuning, sample rate and loudness limits.

Produce: Editable score/source, actual synthesized audio and duration/peak receipt. Attach each output to its current
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

Require `audio.generate@1` of the selected supported music/SFX kind through
a registered deterministic score-binding schema, `media.probe@1`,
`audio.measure@1` and `inspection.audio@1`. The editable score is a validated
artifact/registered recipe, not arbitrary shell code in a prompt. Require declared
determinism and `audio.sample_exact` where exact samples are claimed; an ordinary
stochastic generation provider is not a deterministic score renderer.

## Procedure

1. Freeze cue purpose, score events, tempo/tuning, seed, instruments/patches,
   sample rate, peak ceiling and maximum tail. Declare event/sample rounding and
   initialization state; a seed alone does not establish deterministic rendering.
   Select a binding whose registered schema actually accepts the score controls.
2. Author the editable score with explicit note onset, duration, pitch, amplitude,
   envelopes and effect tails. Retain any patch/sample dependencies and any supplied source facts.
   Map score to the supported audio.generate contract through its exact registered
   schema, without introducing a new operation or interpolated execution text.
3. Render offline against the selected sample clock into owned output. Collect
   actual PCM/audio, score revision, implementation/version and resource context.
   Do not substitute unrequested cloud music generation if the engine is absent.
4. Probe duration/rate and measure true peak/clipping. Audition attacks, inter-note
   balance, clicks and decay through the declared tail. Any normalization changes
   the waveform: preserve a reproducible rendered version and record transforms.
5. For the three-note acceptance cue, rerender with identical frozen inputs and
   pinned deterministic engine, comparing decoded sample arrays and their hashes
   rather than container metadata. Retain both execution receipts and measured
   tail. If exact determinism is unsupported or comparison differs, disclose that
   limit and leave this acceptance unmet, even if the cue sounds acceptable.

## Verification

**SK-S59-output (future empirical acceptance, not yet passed):** A three-note cue rerenders the same samples under the pinned deterministic engine, ends within declared tail and does not clip; unsupported determinism is disclosed.


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
