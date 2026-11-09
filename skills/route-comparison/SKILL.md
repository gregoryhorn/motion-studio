---
name: route-comparison
description: "Compare selected routes on the same authorized sample."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Route Comparison

## When to use

Compare explicitly selected production routes.

**Do not use for:** Exclude automatic paid tournaments or declaring a winner from a mock.

Role boundary: Compare selected tools on the same authorized sample and criteria; emit measured/visual comparison, no automatic paid tournament.

## Inputs and output contract

Required inputs: Same approved sample/criteria, selected bindings, resource/spend ceiling and any supplied source facts.

Requested output artifacts: Route comparison with actual artifacts, measurements, uncertainties and recommendation.

Required capabilities: Inspect compatibility; execute each selected production operation; probe/inspect; measure actual elapsed/cost if available.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_capabilities inspect; motion_plan compile/inspect; motion_run submit/status/collect; motion_review check/record.
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

1. Freeze one supplied sample, success criteria and features before route execution. Confirm exact selected bindings, source compatibility and per-route resource/spend ceilings.

2. Use motion_capabilities inspect for advertised compatibility. Missing implementation or incompatible source stays a blocked route, not permission to convert source or silently choose another provider.

3. Compile a separate bounded plan for each authorized route using the same sample and criteria. Obtain authority for each real effect; discovery/plan compilation never counts as a trial.

4. Collect actual artifacts and observed start/end times, failures and declared or observed costs. Unknown billing remains unknown; report nondeterminism rather than inventing repeatability.

5. Compare actual pixels/playback and required technical results against frozen criteria. Retain both outputs, state missing evidence and recommend only among routes that really ran; no automatic paid tournament.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Route and operation / authority / source revision / artifact / measured elapsed / cost basis or unknown / criterion observations / uncertainty.

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

Required role case **SK-S38-output**:

Two compatible authorized routes render the same test title; retain both outputs and actual elapsed readings, disclose unknown billing and do not prefer a route that never ran.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
