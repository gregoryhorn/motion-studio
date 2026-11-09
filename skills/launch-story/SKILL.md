---
name: launch-story
description: "Build launch narratives from supported product claims."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Launch Story

## When to use

Tell a product launch story.

**Do not use for:** Exclude premium-treatment direction alone or unsupported product claims.

Role boundary: Build product launch narrative from verified claims and supplied media; emit script/storyboard/scenes.

## Inputs and output contract

Required inputs: Verified differentiators, audience/action, assets and delivery duration.

Requested output artifacts: Claim-linked script, storyboard/animatic and scene outputs.

Required capabilities: Stage/probe; render scenes; edit/arrange; inspect/audition as required.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_asset import/probe; motion_plan compile/inspect; motion_run submit/collect; motion_review record.
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

1. Choose one launch message from verified differentiators and the audience's requested action. Map every benefit and feature sentence to the release evidence; remove unsupported superlatives.

2. Create reveal, use and action beats with clear product representations and a feasible duration. Premium material direction alone is not a launch story.

3. Stage approved assets and draft an original claim-linked script and storyboard. Do not add narration when the brief is silent; annotate any illustrative mock as such.

4. Compile an animatic or scene plan and run only the authorized selected operations. Preview claim reading times, the use demonstration and the final action without borrowing another campaign's sequence.

5. Reconcile actual scenes against the approved script. Return real scene/animatic references plus missing outputs; unsupported product claims cannot be fixed by more attractive rendering.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Claim / evidence / audience benefit / beat / asset / on-screen text / scene output / action and timing finding.

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

Required role case **SK-S31-output**:

A supplied release brief yields an original benefit/use/action sequence with evidence for every claim and no fabricated feature or mandatory voiceover.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
