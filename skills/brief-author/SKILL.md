---
name: brief-author
description: "Turn requests into bounded actionable production briefs."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Brief Author

## When to use

Convert a request into a usable production brief.

**Do not use for:** Exclude obligatory interviews when supplied facts suffice.

Role boundary: Turn the request into explicit audience, outcome, assets and deliverables; emit brief without unnecessary interview gates.

## Inputs and output contract

Required inputs: User request, audience/outcome, supplied assets, constraints and requested deliverables.

Requested output artifacts: Brief artifact with assumptions, confirmed facts, variant list and unresolved critical choices.

Required capabilities: Core project/read/update; no media execution required.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project list/open/status/update; no production operation is required.
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

1. Preserve the exact outcome, audience, requested deliverables and supplied constraints. Inspect existing project state before creating a duplicate brief for resumed work.

2. Separate supplied facts from labelled reversible defaults and critical unknowns. A complete silent-title request needs neither a voice interview nor a mandatory new brand system.

3. Inventory approved assets, any supplied source/attribution facts and restrictions on local/remote execution or spend. Missing rights facts are not blocking decisions. Ask only missing decisions that block authority, claims or requested outputs.

4. Define requested aspects, durations, sidecars/editable sources and what evidence would establish delivery. Choose the smallest useful journey, not all available specialists.

5. Write the brief through motion_project update only with the currently advertised document/expected-revision schema; on conflict reread. Return the stored reference when supported, otherwise a proposed brief explicitly not persisted.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Outcome / audience-action / confirmed facts / reversible assumptions / assets-source-facts / variants / authority / critical gaps / evidence expectations.

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

Required role case **SK-S40-output**:

A complete silent-title request becomes a brief immediately without voice/brand interview; a requested missing asset right is recorded rather than assumed.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
