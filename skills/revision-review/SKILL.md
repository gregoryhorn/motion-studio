---
name: revision-review
description: "Close scoped defects only with new media evidence."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Revision Review

## When to use

Close observed frame/audio defects through scoped revisions.

**Do not use for:** Exclude looping without new evidence or declaring fixed from source changes alone.

Role boundary: Turn observed frame/audio defects into scoped fixes; emit finding-to-change-to-evidence record for the latest render.

## Inputs and output contract

Required inputs: Current candidate/hash, findings with frame/audio references, scope and iteration limit.

Requested output artifacts: Finding-to-change-to-new-evidence record and current unresolved list.

Required capabilities: Inspect frames/audio; affected render/edit/mix operations; playback; dependency checks.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_review list/inspect/record; motion_project update; motion_caption correct/style if applicable; motion_plan compile; motion_run submit/collect.
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

1. Pin the current candidate hash, findings, frame/audio references and iteration limit. Reproduce each finding and keep unrelated accepted decisions out of the correction list.

2. Assign each defect a minimal owning source/change and required recheck. Treat a clipped title and delayed audio cue as separate findings with separate evidence needs.

3. Apply authorized scoped changes through the relevant scene/caption/edit/mix route and compile affected descendants only. Missing required operations block those findings, not unrelated valid work.

4. Collect the new candidate, inspect changed frames, audition affected audio and watch relevant playback. A source diff or successful render alone cannot establish closure.

5. Link each finding to change and exact new evidence; close only those supported. Stop at the stated limit, absent new evidence or concrete blocker and return the unresolved list rather than an unbounded loop.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Finding ID / prior hash and frame-sample / correction / affected descendants / new hash / recheck coverage / closed-or-open reason / iteration.

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

Required role case **SK-S61-output**:

A clipped title and delayed cue get separate fixes/evidence; an unfixed cue remains open even when the title passes, and previous-byte receipts cannot close it.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
