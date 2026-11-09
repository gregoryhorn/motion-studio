---
name: voice-produce
description: "Produce authorized narration and verify the actual take."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Voice produce

## When to use

Produce approved narration audio. Exclude unauthorized voice imitation and treating script text as timing evidence.

## Inputs and retained outputs

Required: Approved script/pronunciations, authorized voice, selected speech binding and data/spend policy.

Produce: Actual narration, pronunciation review, voice/source metadata and observed timing. Attach each output to its current
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

Require selected `speech.synthesize@1`, `media.probe@1` and
`inspection.audio@1`. Use `media.extract_audio@1` only if the take is embedded in
media. `speech.transcribe@1`/`speech.align@1` with `speech.segments` or
`speech.words` are conditional on actual timed captions/word treatment. TTS text
or a predicted duration never provides alignment evidence.

## Procedure

1. Resolve approved UTF-8 script/hash, language, pronunciations and authorized
   voice choice. Confirm privacy/identity consent and selected binding, including local or
   remote data destination, limits and charging basis. Reject unauthorized voice
   imitation; do not infer consent from a supplied name or reference recording.
2. Discover the existing user-configured TTS through public capability/host
   inventory without reading secrets or changing settings. A named Breeze voice
   may be used only if it actually exists in that user configuration, is exposed
   by the selected binding and is explicitly selected. This text neither claims
   Breeze exists nor supplies configuration, a model download or a default voice.
3. Freeze script, voice and supported seed/options; compile a single authorized
   synthesis job. Inspect the exact public host tool/schema if transport is a
   handoff, then claim and invoke it through normal approvals. A provider error
   never authorizes a different voice, paid retry or hidden fallback.
4. Collect actual audio bytes and take provenance, probe rate/channels/duration
   and audition the entire requested narration or state uncovered intervals.
   Check proper nouns, pronunciation, omissions, truncation, pauses and unwanted
   artifacts against the approved script. Retain the earlier approved take even
   when a new candidate fails.
5. Derive caption timing only from this chosen take, passing its hash/revision to
   `motion-studio:caption-author`. A script, pronunciation or voice change creates
   a new take and invalidates alignment and dependent mixes/encodes. Preserve all
   take choices and return observed duration and pronunciation findings, not an
   invented transcript or user acceptance.

## Verification

**SK-N01-output (future empirical acceptance, not yet passed):** A supplied proper noun is checked by audition; a changed script creates a new take/revision and invalidates alignment, while provider failure retains the approved earlier take without paid auto-retry.


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
