---
name: asset-source
description: "Stage authorized media with rights and byte provenance."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Asset Source

## Source facts, not rights clearance

Use/redistribution-rights clearance is not a production, release, promotion or
package prerequisite. Unknown/restricted rights and absent licenses must not
block these operations or prompt demands for a license or permission statement.
Retain truthful source provenance, supplied attribution/license facts and unknowns;
never relabel them as cleared or invent grants. Historical license/frontmatter
metadata is unchanged. Execution, data transfer, spend, privacy/identity consent
and host approvals still apply, as do all creative, technical, art, audio and
delivery-profile quality gates. This policy grants no external legal rights.


## When to use

Acquire or stage an asset already selected by a media plan.

**Do not use for:** Exclude deciding the story or assuming a stock subscription.

Role boundary: Resolve local, uploaded, stock or generated assets under selected policy; emit staged asset records and attribution.

## Inputs and output contract

Required inputs: Asset role, source candidates, data policy and any supplied source facts and selected acquisition binding.

Requested output artifacts: Verified staged asset record, original reference, probe and attribution.

Required capabilities: Source/search when required; stage; probe; hash/collect.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_asset reference/import/get/probe; motion_run collect where a selected acquisition operation requires a job.
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

1. Read the asset request, selected source and data policy. Local-only forbids remote search/download; an available stock URL does not establish subscription or reuse rights.

2. Use motion_asset reference for an external reference or import for an authorized copy, only when the live schema supports the intended operation. Record original reference and checksum before any staging; never edit the original.

3. Check the returned staged record against actual bytes: hash, size, dimensions/duration and media type. motion_asset get/probe must describe the staged copy, not a similarly named source.

4. Inspect fitness for the named role: crop margin, transparency, readable detail or audible content. A wrong or changed external reference is rejected rather than silently replaced.

5. Preserve any supplied source/license/attribution facts without inventing permission or clearance. Unknown or restricted rights and an absent license are not production, release or package blockers; do not demand a license or permission statement. Return the staged ID only after exact source/staged identity is verified.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Role / original reference and hash / staged ID and hash / probe / supplied source facts or unknown / supplied attribution / known restrictions (informational).

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

Required role case **SK-S03-output**:

Import a local still and reject a changed external reference: original hash unchanged, staged hash verified, dimensions and attribution recorded; no remote download on local-only policy.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
