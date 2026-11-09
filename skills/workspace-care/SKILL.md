---
name: workspace-care
description: "Inspect readiness and clean only owned project work."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Workspace Care

## When to use

Inspect project readiness and clean up owned work.

**Do not use for:** Exclude unrelated services, shared model eviction and arbitrary filesystem administration.

Role boundary: Resolve project/runtime paths and owned processes; emit readiness/cleanup records without managing unrelated services.

## Inputs and output contract

Required inputs: Host-provided runtime root, project ID, ownership records and authorized cleanup request.

Requested output artifacts: Readiness/ownership report and exact cleanup receipt.

Required capabilities: Read-only dependency/resource inspection; status/cancel owned jobs; scoped file cleanup.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status; motion_capabilities discover/list/inspect; motion_run status/cancel; no arbitrary service management.
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

1. Resolve project identity and runtime root from trusted host/project records. Reject user content masquerading as a runtime path and do not hardcode another machine's home directory.

2. Inspect dependencies and resource declarations read-only. Use motion_capabilities discover/list/inspect where available; discovery never installs, starts models or evicts shared resources.

3. Cross-check each job and temporary file against ownership records. A matching process name or path prefix alone is insufficient proof; exclude originals, approved artifacts and unrelated services.

4. Present the exact cancel/delete scope and obtain authorization for destructive effects. Use motion_run status/cancel for owned jobs; require observed terminal status before declaring cancellation complete.

5. Only remove explicitly approved owned temporary files with a supported scoped mechanism. If none exists, return a cleanup proposal, not a generic shell deletion bypass. Re-read owned status and retain an exact cleanup receipt.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Trusted root / project ID / readiness finding / owned job-file evidence / proposed effect / authority / observed postcondition.

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

Required role case **SK-S25-output**:

An interrupted owned job and an unrelated process coexist: cleanup handles only the owned resources and leaves unrelated PID/files and project originals unchanged.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
