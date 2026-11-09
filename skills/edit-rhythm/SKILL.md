---
name: edit-rhythm
description: "Design cuts from content, continuity and audio cues."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Edit Rhythm

## When to use

Design purposeful cut rhythm.

**Do not use for:** Exclude arbitrary rapid cutting or forcing every cut to a music beat.

Role boundary: Plan purposeful cuts from content and approved audio; emit cut list with continuity/readability checks.

## Inputs and output contract

Required inputs: Source clips, message beats, approved audio/timing and reading constraints.

Requested output artifacts: Frame-based cut list, continuity notes and actual paced preview.

Required capabilities: Probe; cut/arrange; audio audition; playback/frame extraction.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_asset probe; motion_plan compile/inspect; motion_run submit/status/collect; motion_review record.
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

1. Probe each clip and establish source frame ranges, rate and message content. Note continuity anchors and labels that must remain readable before shortening anything.

2. Audition approved audio and mark measured cues when present. Differentiate a semantic edit from a music accent; do not force every cut onto a beat or require music for silent media.

3. Build a frame-based cut list citing the purpose of each cut, source in/out, timeline start and intended hold. Compute durations and check that explanations and claims remain intact.

4. Compile and run an authorized assembly preview with the selected edit binding. Watch transitions and surrounding intervals at speed, audition sound where present and note jumps or truncated speech.

5. Revise only cuts whose observed pacing or continuity fails. A table of durations is a cut plan, not proof of a paced preview; retain missing playback/audio evidence as open.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Cut / source in-out / timeline interval / content purpose / cue evidence / readable hold / preview observation.

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

Required role case **SK-S30-output**:

A three-clip explanation retains its full claims and readable labels; the cut list cites purpose/cue and an actual preview is auditioned rather than inferring pace from durations alone.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
