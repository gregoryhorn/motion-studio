---
name: presenter-matte
description: "Preserve presenter motion with temporal alpha mattes."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Presenter matte

## When to use

Produce temporally coherent presenter cutouts. Exclude one-frame background removal as proof of video matting.

## Inputs and retained outputs

Required: Presenter clip, privacy/identity consent, motion/edge requirements and output alpha/timebase.

Produce: Matte sequence/video, tracked source, composite preview and temporal edge review. Attach each output to its current
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

Require `media.matte@1` with `temporal:true`, explicitly declared temporal
support in the binding schema/constraints, `video.alpha` or an alpha image sequence
with `image.alpha`, and `media.probe@1`. Require a selected supported composition
route (`edit.assemble@1` or `scene.author@1`/`scene.render@1`) and
`inspection.visual@1` plus `inspection.playback@1`. Use frame/audio extraction
only as needed to verify source alignment. A still segmenter is insufficient.

## Procedure

1. Verify presenter privacy/identity consent, original hash, rational timebase,
   audio stream mapping, dimensions and orientation. Identify challenging motion:
   turns, crossing hands, hair, occlusions, entering/exiting frame and fast motion.
   Declare output alpha convention and temporal consistency criteria.
2. Inspect selected matte support and duration/resource constraints. If it only
   segments still images, stop the temporal route; independently processing frames
   without temporal qualification is not a demonstrated replacement. Preserve the
   source and report the missing temporal constraint precisely.
3. Submit the frozen clip for foreground and matte outputs without modifying or
   replacing its audio. Collect actual matte sequence/video, original frame-to-
   output mapping and any explicit conform record. Check frame count, time origin,
   duration and alpha format by decoding, not filename extension.
4. Composite over contrasting backgrounds and inspect consecutive frames around
   all chosen difficult intervals. Look for edge chatter, hand disappearance,
   hair loss and halos; record interval/frame coverage rather than a single hero
   still. Review continuous playback as well as sampled edges.
5. Verify recomposition aligns with source timing/audio; disclose any shifts,
   dropped frames or unsupported variable-rate mapping. Keep original, matte and
   proof bytes plus unresolved intervals. Alpha encoding checks may use
   `motion-studio:alpha-delivery`, but do not turn an alpha pass into a temporal
   edge-quality pass.

## Verification

**SK-S54-output (future empirical acceptance, not yet passed):** A presenter turning and moving a hand has inspected motion samples with stable edges and unchanged time alignment; unsupported temporal matte capability is a named blocker.


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
