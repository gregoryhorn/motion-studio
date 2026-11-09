---
name: frame-safety
description: "Check actual delivery pixels against bounds and overlays."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Frame Safety

## When to use

Check bounds and platform overlays at actual delivery size.

**Do not use for:** Exclude treating bounding boxes alone as aesthetic approval.

Role boundary: Verify scene/caption bounds and platform overlays per aspect; emit proof frames plus unresolved visual issues.

## Inputs and output contract

Required inputs: Decoded frames, actual text/subject bounds, aspect and sourced overlay/safe-zone profile.

Requested output artifacts: Annotated proof frames and precise bound/legibility findings per variant.

Required capabilities: Extract/evaluate frame; layout bounds; inspect pixels.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_asset probe; motion_plan compile for selected frame extraction if needed; motion_run collect; motion_review check/record.
The action inventory is not implementation evidence: the inspected baseline exposes
production skeletons that return `NOT_IMPLEMENTED`. Stop at any unavailable action;
return the role document and an exact missing-operation blocker, not simulated
media, receipts or a private-handler workaround. Resolve concrete operations,
ports and required features through `motion_capabilities` and the selected plan
when supported. Never install dependencies or switch providers to bypass a gap.

For the shared production contract, use
`skill_view(name="motion-studio:studio-produce", file_path="references/production-contract.md")`
if the plugin is registered. Do not use a sibling traversal as file_path. If the
qualified skill is unavailable, report it; the boundaries below still apply.
Linux marks the inspected authoring host, not verified platform production support.

## Procedure

1. Resolve exact candidate/aspect, actual text/subject bounds and sourced overlay profile. Unknown platform safe zones remain an unresolved profile gap, not an invented inset.

2. Extract actual delivery frames at moving extrema, caption wraps, entrances and exits. Record frame indices and coverage; static center-frame checks cannot establish whole-sequence safety.

3. Compare bounding geometry with both canvas and declared overlays. A caption can be inside the canvas yet unreadable under a platform control; report that independently.

4. Inspect actual pixels at delivery size for clipping, wrapping, contrast and occlusion. Produce annotated proof frames without overwriting candidate or source, and distinguish safety from aesthetic approval.

5. Write severity, exact failing interval and minimal remedy. After a correction recheck new candidate bytes and affected extrema; do not carry the old pass across a changed encode.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Variant and hash / frame-interval / profile source / measured bounds / overlay intersection / pixel finding / severity / proof reference.

Attach project/document revision, input hashes where applicable, reviewer identity,
actual coverage and unresolved items. Distinguish proposed text, persisted document,
rendered candidate, checked master and user acceptance. Return the smallest useful
record, not a fabricated finished production or another parallel state store.

## Pitfalls and authority boundaries

- Open/status/discovery/plan inspection do not authorize rendering, generation,
  remote transfer or spend. A new preview is production, not passive viewing.
  Before an effect, pin selected binding and disclosed effects and use host approval.
- Use current expected revisions on supported writes. A stale response means reread
  and reconcile; preserve originals, approved masters and unaffected dependencies.
  Changed bytes/dependencies invalidate their bound review, not unrelated outputs.
- On unknown job effects, read status/reconcile rather than resubmit. Any typed
  handoff must use the advertised claim and normal native tool path, never hidden
  dispatch or embedded credentials.
- Technical results, agent judgement and identified user approval are distinct.
  Do not close an unseen/unheard interval or promote/package missing outputs.
  No public posting, unrelated cleanup or expanded authority is implicit.

## Verification and pending acceptance

Required role case **SK-S51-output**:

A portrait caption entering a declared bottom overlay gets a frame-specific failure even if its geometric text box is inside the canvas; corrected candidate is rechecked.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
