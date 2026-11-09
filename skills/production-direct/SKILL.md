---
name: production-direct
description: "Resolve bounded craft tradeoffs within an accepted brief."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Production Direct

## When to use

Resolve production tradeoffs within the accepted brief.

**Do not use for:** Exclude expanding spend/authority or establishing parallel project state.

Role boundary: Resolve narrative/craft conflicts within the brief; emit bounded production decisions, not a second project state store.

## Inputs and output contract

Required inputs: Current project, alternatives, observed defect/conflict and approved constraints.

Requested output artifacts: Bounded decision record with rationale, affected nodes and next action.

Required capabilities: Core state/plan inspection; actual review evidence required for output judgements.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update; motion_plan inspect; motion_review list/inspect; no automatic motion_run submit.
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

1. Read the current brief, affected node dependencies and observed conflict. Distinguish an actual unreadable/too-long title from an unsupported stylistic preference.

2. Compare minimal remedies such as a longer hold, a layout change or an approved shorter wording. State tradeoffs against reading time, claim integrity and delivery duration.

3. Select an in-scope option that preserves approved work. New narration, changed claims, another engine or increased spend requires a separate user decision, not implied director authority.

4. Record rationale, affected nodes and invalidated descendants in the current project revision. Do not fork parallel project state or close an output finding from the decision alone.

5. Hand off the precise next authorized correction with its required evidence. If the alternatives all exceed the brief, return the blocking choice rather than expanding scope.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Conflict and evidence / alternatives / chosen remedy / constraints preserved / affected nodes / new authority if needed / next verification.

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

Required role case **SK-S42-output**:

A too-long title is resolved by an in-scope timing/layout choice with affected nodes identified; it does not silently buy new narration or rewrite the accepted claim.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
