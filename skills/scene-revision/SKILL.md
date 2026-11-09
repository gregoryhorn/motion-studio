---
name: scene-revision
description: "Correct existing scenes with minimal dependency changes."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Scene Revision

## When to use

Revise an existing scene with minimal change.

**Do not use for:** Exclude restarting approved production or editing originals destructively.

Role boundary: Diagnose and revise existing source without restarting approved work; emit minimal source diff and rechecked output.

## Inputs and output contract

Required inputs: Existing source/revision, exact defect/change, approved assets and dependencies.

Requested output artifacts: Scoped source diff, revised preview/candidate and invalidation/review record.

Required capabilities: Selected scene/edit operation; evaluate frame; dependency tracking; inspect pixels/audio as affected.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update; motion_plan compile/inspect; motion_run submit/collect; motion_review record.
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

1. Read the existing source/revision and exact requested change. Reproduce the defect using current frames or playback and identify the owning source element; preserve originals.

2. Map dependencies and set the smallest correction scope. Moving one clipped label must not regenerate narration or replace otherwise approved source assets.

3. Apply a non-destructive scoped source diff with current expected revision and approved assets only. On stale state reread before merging intent; no automatic engine conversion.

4. Compile only affected scene intervals and delivery descendants with reuse of valid upstream outputs. A new preview is an authorized job, not a read-only inspection.

5. Inspect corrected rendered frames and affected audio/playback, then the exact changed candidate. Return the diff, new evidence and remaining findings; unchanged originals and invalidated receipts must be identifiable.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Finding/frame / owning source and revision / minimal diff / preserved inputs / affected descendants / new candidate hash / recheck evidence.

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

Required role case **SK-S48-output**:

Move one clipped label: only that scene and delivery descendants rerun; narration/source assets are unchanged and the corrected decoded frame is inspected.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
