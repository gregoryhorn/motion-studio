---
name: raster-scenes
description: "Evaluate raster scenes by frame and measure real renders."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Raster scenes

## When to use

Render deterministic frame-evaluated raster scenes. Exclude requiring one computer-vision library or using speed estimates as evidence.

## Inputs and retained outputs

Required: Scene geometry/data, fonts/assets, frame rate, dimensions and selected raster binding.

Produce: Editable raster-scene source, real sequence, sample frames and measured render receipt. Attach each output to its current
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

Require `scene.author@1`, `scene.render@1` with `scene.raster`,
`scene.frame@1` with `timing.frame_seek` and `timing.frame_exact` for exact parity,
`media.probe@1` with full decode and `inspection.visual@1`. Observe elapsed time
from actual job execution/receipts; no new timing operation is introduced.

## Procedure

1. Freeze dimensions, rational frame rate, frame range, data values, coordinate
   system, font files and source assets. Identify random/seeded parameters; each
   frame must be a function of the declared frame index and frozen inputs, not
   wall clock, prior playback state or mutable network data.
2. Author editable layout/draw source with deterministic evaluation order, text
   metrics, clipping and color choices. Validate font availability and supplied
   glyphs before rendering. Keep chart data linked to labels rather than hardcode
   a different picture for each preview.
3. Seek frames 0, 30 and 59 in nonsequential order for the acceptance fixture.
   Verify identical frame requests yield matching uncompressed pixels and do not
   advance hidden state. Inspect bounds, thin strokes, aliasing and label legibility.
4. Render the complete fixture sequence through the selected raster binding.
   Record actual execution start/end or elapsed receipt plus binding and resource
   context; do not estimate speed from a single still or claim a benchmark without
   a measured interval. Preserve source and all required raster dependencies.
5. Decode the encoded sequence at the same indices and compare to random seeks
   using a predeclared codec/color tolerance. An exact source frame can differ
   after lossy encode; report the measured difference and whether tolerance held.
   A sequential-only engine is a missing seek capability, not a passing renderer.

## Verification

**SK-S46-output (future empirical acceptance, not yet passed):** Render a chart/title at frames 0, 30, 59 plus the sequence: random seeks agree with decoded frames within declared codec tolerance, and elapsed time is observed.


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
