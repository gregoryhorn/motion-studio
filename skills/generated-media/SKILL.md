---
name: generated-media
description: "Generate one selected asset with explicit data authority."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Generated media

## When to use

Generate a selected image, video or music asset. Exclude automatic tool substitution, hidden upload and pretending every adapter generates all media types.

## Inputs and retained outputs

Required: Approved prompt/inputs, requested media type, chosen binding/features and explicit data/spend authority.

Produce: Actual staged generated asset, prompt/input revision, provider/model and rights/cost/provenance receipt. Attach each output to its current
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

Require exactly the selected `image.generate@1`, `image.edit@1`,
`video.generate@1` or `audio.generate@1` (music/SFX kind as requested), not all of
them. Require collection/staging of real bytes through the declared adapter and
`media.stage@1` when needed, `media.probe@1` and media-appropriate
`inspection.visual@1`, `inspection.audio@1` or `inspection.playback@1`.
Speech narration belongs to `motion-studio:voice-produce`.

## Procedure

1. Resolve the requested media kind, approved prompt, reference/input hashes,
   dimensions or duration/rate, intended use and any supplied source facts. `motion-studio:media-plan`
   may choose the asset role but does not authorize a generation call. Verify the
   selected adapter actually declares this operation and its required features;
   a video-only adapter cannot satisfy an image request.
2. Disclose actual provider/model/version if known, uploaded inputs and destination,
   charging basis/estimate or unknown cost, and known/unknown rights. Obtain
   authority for these effects before submission. A local wrapper may still upload;
   a previous approved request does not permit new destination or unlimited spend.
3. Freeze media-specific parameters and registered options, record request identity
   and submit only the authorized node. Do not send every available media request,
   silently edit instead of generate, or switch provider after rejection. Lost
   submission responses remain uncertain until lookup/reconciliation, not retry.
4. Collect retrievable result bytes into an owned staged asset. Record provider
   handle, prompt/input revision, seed if supported and actual observed cost only
   when a receipt provides it. HTTP success or a result URL with no accessible
   media fails output validation; preserve logs/handle without a fake artifact.
5. Probe actual dimensions/rate/duration/streams and inspect or audition content,
   including input fidelity, unwanted text and temporal/audio defects as relevant.
   Keep the stochastic take: regeneration is neither reconstruction nor guaranteed
   equivalence. Return real staged bytes, provenance and remaining rights/cost
   unknowns to the project; inspection is not license clearance or user approval.

## Verification

**SK-N02-output (future empirical acceptance, not yet passed):** An authorized image request returns an actual inspected image; a video-only adapter is rejected for it, and HTTP success with no retrievable media remains invalid output, not generated success.


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
