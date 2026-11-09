---
name: delivery-complete
description: "Reconcile requested files against checked deliveries."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Delivery Complete

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

Reconcile requested delivery against actual checked artifacts.

**Do not use for:** Exclude manufacturing missing outputs or interpreting planned filenames as completed files.

Role boundary: Reconcile requested files with real checked outputs; emit completeness manifest, not blanket claims of success.

## Inputs and output contract

Required inputs: Requested variants, master/package manifests and exact promotion receipts.

Requested output artifacts: Completeness manifest with present/missing/blocked files and retrievable delivery references.

Required capabilities: Probe/check format; verify hash; inspect archive/sidecars; collect artifacts.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_deliver status/package_validate; motion_asset get/probe; motion_run collect for already executed work.
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

1. Expand only requested variants, sidecars and source-package requirements into a checklist. A planned path or encoder job name is not proof a file exists.

2. Read motion_deliver status and package manifests. Match each requirement to existing exact bytes, checksum, media probe and current promotion receipt; verify retrieval through supported artifact references.

3. Check sidecar language/timing association and package closure against its master. An archive alone is not reconstructability evidence; retain reconstruction as unresolved without an actual reconstruction receipt.

4. Classify every requested item as present, missing or blocked and name why. Preserve independently valid variants instead of hiding all results when another variant fails. For an editable filmmaking package, require the source JSON member closure, transitive assets/engine/font notices, soundtrack cues and reused-producer lineage. A cold reconstruction must execute extracted authored source and compare decoded video/format; do not infer audio equivalence from a video-only label or treat copied rendered masters as editable reconstruction.

5. Return the completeness manifest and real retrievable references. Never generate absent media to make the checklist green, call partial delivery complete, or upload/post it.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Requested item / present|missing|blocked / actual handle / checksum / approval and probe receipts / retrieval check / missing dependency.

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

Required role case **SK-S14-output**:

For requested landscape, portrait and SRT with portrait absent, report two real outputs and one missing variant, not overall completion; every delivered reference is retrievable.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
