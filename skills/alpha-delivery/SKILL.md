---
name: alpha-delivery
description: "Verify transparent masters from decoded alpha planes."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Alpha delivery

## When to use

Deliver transparent video or image sequences. Exclude flattening alpha silently or assuming opaque codecs carry alpha.

## Inputs and retained outputs

Required: Alpha-bearing source, requested codec/container, alpha convention and color requirements.

Produce: Alpha master, alpha-plane/color receipts and contrasting-background composites. Attach each output to its current
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

Require `scene.render@1` or `delivery.encode@1` with explicit alpha-capable
format/codec, `image.alpha` or `video.alpha` as appropriate, `media.probe@1` with
full decode and a decoder exposing alpha planes. Require selected composition
support and `inspection.visual@1`; motion also needs `inspection.playback@1`.
Actual alpha mode, pixel format and color-space constraints must match across
render/encode/decode. A container name is not an alpha feature guarantee.

## Procedure

1. Resolve source alpha, requested codec/container or image sequence, straight
   versus premultiplied convention, color/transfer/range and expected consumer.
   Inspect source bytes, not a checkerboard thumbnail. Negotiate actual encoder
   and decoder support; an opaque-only requested codec is a compatibility gap.
2. Freeze the candidate with explicit alpha/color options and retain the source.
   Any requested flattening is a separately authorized changed output via
   `media.transform@1` with `kind:flatten_alpha`, not a transparent master.
3. Encode/render actual owned candidate bytes. Full-decode representative moving
   shape frames and inspect alpha planes at known clear, partially transparent
   and opaque regions. Retain frame indices, sample coordinates and numeric
   ranges in receipts. Merely finding an alpha-labelled stream is insufficient.
4. Composite the decoded candidate over two contrasting backgrounds using the
   declared supported route. Inspect translucent color, halos, matte fringes and
   premultiplication mismatch, then play motion through relevant intervals.
   Verify the intended consumer where compatibility is part of the request.
5. Return alpha master, source, probe/plane/color receipts and proof composites
   with matching hashes. Send only this checked candidate to the shared gates
   for exact-byte promotion; do not self-promote or replace approved masters when
   alpha or color fails. Preserve the failed candidate for diagnosis.

## Verification

**SK-S60-output (future empirical acceptance, not yet passed):** A moving translucent shape preserves alpha 0/intermediate/opaque regions in actual decoded output; an opaque-only requested codec yields a compatibility gap, not a black-background success.


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
