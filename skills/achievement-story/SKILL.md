---
name: achievement-story
description: "Reveal milestones with readable claim provenance."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Achievement Story

## When to use

Reveal a verified achievement or milestone.

**Do not use for:** Exclude unsupported celebratory numbers and generic launch scripts.

Role boundary: Present verified milestone data with restrained emphasis; emit reveal scene and claim provenance.

## Inputs and output contract

Required inputs: Value, units, period, source and approved comparison/context.

Requested output artifacts: Source-linked reveal script/scene and readable claim frame.

Required capabilities: Render/evaluate frame; inspect pixels; compute if derived value is requested.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update; motion_plan compile; motion_run submit/collect; motion_review record; execute_code for derived values.
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

1. Validate value, units, measurement period and source. Separate achieved metrics from targets and approved comparisons; reject a celebratory number that has no evidence.

2. If deriving a value, calculate using execute_code or terminal and retain inputs/formula/rounding. Do not inflate growth by switching denominator or comparison period.

3. Write a short reveal with restrained emphasis, retaining period and caveat in the claim frame. A count animation must end on the supported value and not imply unobserved intermediate measurements.

4. Compile/render the representative claim frame and reveal hold under the selected plan. Inspect actual pixels at delivery size for units, source and qualifier readability.

5. Review the reveal in playback and return the source-linked script, real scene/frame and findings. If rendering is unavailable, deliver only the labelled script proposal; never call the milestone visually verified.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Value / units / period / actual-or-target / source / derivation if any / reveal interval / qualifier frame and review.

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

Required role case **SK-S35-output**:

A supplied '100 deployments, Q3' is labelled with period and source; an aspirational 200 is not presented as achieved and reveal timing does not hide the qualifier.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
