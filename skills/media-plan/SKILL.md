---
name: media-plan
description: "Assign media roles without acquiring unnecessary assets."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Media Plan

## When to use

Plan what media serves each narrative role.

**Do not use for:** Exclude downloading/acquiring assets or calling every available generator.

Role boundary: Choose asset roles and acquisition paths for the brief; emit asset/capability plan, delegating acquisition to asset-source.

## Inputs and output contract

Required inputs: Brief/beats, existing asset inventory, data/spend policy and any supplied source facts.

Requested output artifacts: Role-to-asset/capability plan with gaps and acquisition requests.

Required capabilities: Core artifact inspection
Optional capabilities: read-only source search.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status; motion_asset list/get/probe; motion_capabilities inspect; no motion_run submit during planning.
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

1. Read brief/beats, inventory and data/spend limits plus any supplied source facts. Identify what each scene must explain, prove or contextualize before selecting a media type.

2. Inspect existing suitable media using actual asset records. Prefer the local diagram that meets the role over speculative stock or generated replacements.

3. For each gap, specify required dimensions, duration, transparency, composition, authenticity and any supplied source facts (not clearance prerequisites). Mark desirable features separately from required ones.

4. Propose one selected acquisition path per actual gap with movement/spend implications. Optional read-only source search must respect policy; search results do not establish rights or valid staged bytes.

5. Return acquisition requests for asset-source or generated-media only where needed. This role never downloads/generates, submits a provider tournament or blocks independent scenes for optional media.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Beat and explanatory role / existing asset and fitness / required properties / source facts / data limit / gap / proposed acquisition binding.

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

Required role case **SK-S34-output**:

A scene with a valid local diagram reuses it; a missing contextual photo becomes a named acquisition gap and no bytes are downloaded during planning.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
