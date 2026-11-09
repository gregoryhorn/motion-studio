---
name: background-matte
description: "Create still cutouts with inspected alpha edges."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Background matte

## When to use

Remove a still asset's background or create a short static-object matte. Exclude temporal presenter matting or assuming a particular segmentation model.

## Inputs and retained outputs

Required: Supplied image, intended background, edge/alpha requirements and selected binding.

Produce: Cutout, matte, provenance and light/dark composite proof. Attach each output to its current
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

Require `media.matte@1` with `temporal:false` and compatible alpha output,
`image.alpha`, `media.probe@1` and `inspection.visual@1`. Composite proof uses
selected `scene.author@1`/`scene.render@1` with the relevant scene feature or
`edit.assemble@1` with an exact supported composition schema. Do not invent a
composite API. A short static-object sequence additionally needs declared format
support and applicable `video.alpha`; it does not establish temporal matting.

## Procedure

1. Inspect original dimensions, orientation, compression, subject holes,
   reflections, hair/fine edges and the intended replacement background. Retain
   original bytes/hash and any supplied source facts. Set edge criteria and select the declared matte
   method without requiring any named model or installing one.
2. Request foreground and matte from the frozen source with transparent or mask
   output as selected. Collect both actual outputs; associate each with the source
   asset. A generated lookalike subject is not a segmentation result.
3. Decode the matte and cutout, checking size/orientation alignment and whether
   alpha is actually present. Inspect opaque body, fully clear holes and soft edge
   pixels; a checkerboard baked into RGB or a JPEG is not transparency.
4. Render proof composites over light and dark backgrounds through the supported
   composition route. Inspect fine edges at useful scale for halos, color spill,
   cropped detail and unintended transparent body areas. Record sample locations
   and exact proof hashes; do not infer edges from a small thumbnail.
5. Preserve cutout/matte as editable assets with provenance and unresolved edge
   issues. Hand temporal human motion to `motion-studio:presenter-matte`; if a
   requested refinement lacks support, retain the current candidate and report
   the precise gap rather than flattening it to the intended background.

## Verification

**SK-S50-output (future empirical acceptance, not yet passed):** A supplied product image preserves holes and soft edges on white and dark proof composites; a JPEG without alpha is not accepted as a transparent cutout.


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
