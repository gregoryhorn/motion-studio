---
name: scene-3d
description: "Author editable physical scenes and inspect real renders."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Scene 3d

## When to use

Author and render physical 3D scenes. Exclude flat graphics requiring no 3D or assuming one application.

## Inputs and retained outputs

Required: Scene intent, objects/assets, camera, lights, frame rate, color/alpha requirements.

Produce: Editable native scene source, scene manifest, real render and probe/frame evidence. Attach each output to its current
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

Require `scene.author@1`, `scene.render@1` with `scene.3d`,
`scene.frame@1` with `timing.frame_seek`, `media.probe@1` and
`inspection.visual@1`. Frame-exact sampling additionally needs
`timing.frame_exact`. Alpha is conditional: request the applicable `image.alpha`
or `video.alpha`, supported convention and format only when transparency is
required. Resource availability must cover the pinned renderer, not its label.

## Procedure

1. Resolve supplied geometry/textures and any supplied source facts, units, object transforms,
   camera/lens, lights, frame range/rate and output color intent. Reject missing
   assets instead of silently replacing them with primitives. Choose only a
   selected binding that declares the required materials, source format and limits.
2. Author native editable geometry references, materials, camera and lighting via
   the authorized source path. Keep scene manifest references to every asset,
   font/texture dependency and animation control so the supplied object remains
   identifiable and the source can be reopened.
3. Evaluate at least the two declared diagnostic frames: inspect silhouette,
   camera framing, highlights/shadows and rotation continuity. Use actual pixel
   evidence and record frame indices. A viewport screenshot is not a sequence.
4. Submit the bounded sequence render to owned output, collect native source and
   frames/media, then full-decode/probe dimensions, rational rate, duration and
   color/alpha where requested. Retain renderer implementation/version and
   settings needed to rerender; do not claim other engines can open this source.
5. Compare decoded diagnostic frames to the intended camera/material controls.
   Return the scene, actual render and unresolved defects. An unavailable renderer
   blocks rendering while preserving scene intent/source; it never permits a
   placeholder turntable to masquerade as the supplied object.

## Verification

**SK-S06-output (future empirical acceptance, not yet passed):** Render a rotating supplied object at two named frames and a short sequence; camera/materials remain editable, duration matches and absent renderer produces a precise gap rather than a placeholder render.


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
