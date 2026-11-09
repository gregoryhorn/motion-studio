---
name: release-review
description: "Reconcile exact-candidate evidence for release gates."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Release Review

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

Decide readiness of an exact candidate using all required gates.

**Do not use for:** Exclude rendering first or claiming human approval on behalf of a user.

Role boundary: Coordinate required gate evidence for exact candidates; emit release verdict and precise remaining defects.

## Inputs and output contract

Required inputs: Candidate hash/revision, brief, requested profile, gate receipts and review identities.

Requested output artifacts: Release review with per-gate pass/fail/review_needed/not_applicable and unresolved defects.

Required capabilities: Decode/probe; inspect frames; measure/audition audio; playback; profile check as applicable.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_review gates/check/record/list/inspect; motion_deliver status/validate; promotion is not part of this review.
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

1. Resolve the candidate checksum, revision, sidecars, requested profile and required gates through motion_deliver status and motion_review gates/list/inspect. Do not begin by rendering a replacement.

2. Build a gate ledger for technical, visual/art, audio when present, playback and requested delivery/package requirements. Use the actual gate policy; not_applicable needs an explicit reason.

3. Reject receipts bound to other bytes, dependencies or profile versions. Obtain missing decode/measurement and frame/audio/playback judgement through selected checks, with actual coverage recorded.

4. Keep deterministic checks, agent judgement and identified user acceptance separate. An unreadable title fails art even if technical decode passes; an unheard soundtrack stays review_needed.

5. Return precise unresolved findings and a per-gate verdict. Promotion is a separate authorized action only after current policy passes, never an invented approval or an automatic consequence of writing this review.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Candidate hash/revision / gate / evidence identity and coverage / pass|fail|review_needed|not_applicable / reason / unresolved defect.

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

Required role case **SK-S13-output**:

A decodable candidate with unreadable title fails art despite technical pass; a changed checksum invalidates all byte-bound review and cannot inherit a prior release verdict.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
