---
name: brand-discover
description: "Extract source-linked identity facts and brand gaps."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Brand Discover

## When to use

Discover a brand's supplied identity and constraints.

**Do not use for:** Exclude authoring a token system or fabricating missing brand policy.

Role boundary: Extract provided identity, audience and constraints; emit source-linked brand intake with missing facts explicit.

## Inputs and output contract

Required inputs: User brand material, audience, examples and data-access permissions.

Requested output artifacts: Source-linked brand intake with confirmed constraints, hypotheses and missing facts separate.

Required capabilities: Read/inspect documents and images; no media execution required.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update for the intake; read_file and vision_analyze for supplied sources.
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

1. Inventory user-supplied documents and images with source locations and any supplied attribution facts; confirm data-access authority. Use read_file for text and vision_analyze for actual images; do not infer a complete policy from a thumbnail.

2. Extract audience, logo use, color, typography, tone and prohibited treatments only where supported. Label an example as an example, not automatically a mandated system.

3. For conflicting references, retain both citations and identify the production decision they affect. Ask only that choice, not a broad mandatory brand interview.

4. Separate confirmed requirements, reversible preferences, hypotheses and unavailable facts. Unknown font/logo rights remain factual unknowns, not clearance prerequisites; private source/data restrictions remain explicit.

5. Return intake ready for a later approved brand-system step; do not create token values or mark a new visual identity approved on the user's behalf.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Source / location / extracted constraint / mandate-or-example / confidence / conflict / necessary decision.

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

Required role case **SK-S07-output**:

Two supplied references disagree on accent color: intake quotes both sources, marks conflict and asks only the necessary choice; it does not silently pick or generate a brand kit.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
