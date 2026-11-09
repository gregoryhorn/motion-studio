---
name: beat-plan
description: "Translate scripts into frame-based narrative beats."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Beat Plan

## When to use

Convert approved script and intent into timed narrative beats.

**Do not use for:** Exclude full scene implementation or an obligatory beat rewrite for caption edits.

Role boundary: Author frame-based narrative beats and audio cue references; emit beat sheet and timing constraints.

## Inputs and output contract

Required inputs: Script, project rational frame rate, duration constraint and audio cue references.

Requested output artifacts: Beat sheet with integer-frame boundaries, story purpose and cue dependencies.

Required capabilities: Core timing/validation only
Optional capabilities: audio probe and audition for supplied cues.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update; optional motion_asset probe and motion_review record for actual audio observations.
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

1. Read the approved script and rational frame rate as numerator/denominator. Use execute_code or terminal for frame arithmetic; retain the exact rate rather than rounding it to a nominal integer.

2. Name the message purpose of each beat and text to be read. Allocate reading holds before transition decoration; respect the requested total frame budget.

3. Compute integer start/end frames with an explicit end-exclusive convention. Check ordered coverage of the total interval and explain every overlap as a transition.

4. For supplied audio, reference measured cue positions and actual asset IDs; optional probe/audition can establish cues. Without audio evidence, leave cue times unresolved and do not fabricate beat markers.

5. Write the beat document using the current project revision and identify downstream scenes affected by changed timing. Caption-only spelling edits do not automatically justify rewriting all beats.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Beat ID / purpose and text / start frame / end-exclusive frame / transition overlap / cue reference or unresolved dependency.

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

Required role case **SK-S05-output**:

A 240-frame brief has fully covered ordered beats, explicit transitions and no accidental gaps; cue references resolve to actual audio or are marked unresolved, never guessed.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
