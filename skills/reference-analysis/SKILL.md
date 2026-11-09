---
name: reference-analysis
description: "Measure references and author distinct original treatments."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Reference Analysis

## When to use

Analyze reference motion for an independently authored treatment.

**Do not use for:** Exclude proprietary source extraction, asset copying and guaranteed style cloning.

Role boundary: Analyze reference timing/layout/type/motion; emit independently authored treatment and comparison, not proprietary extraction/copying.

## Inputs and output contract

Required inputs: Supplied reference video, intended principles, brief and permitted reuse scope.

Requested output artifacts: Timing/layout/type/motion analysis, original treatment and side-by-side comparison evidence.

Required capabilities: Probe/extract frames; inspect playback/pixels/audio; render original scene.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_asset import/probe; motion_plan compile for frame extraction/original rendering; motion_run submit/collect; motion_review record.
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

1. Confirm the supplied reference, requested analysis/reuse scope and intended principles. Preserve any supplied source/attribution facts without treating unknown rights as a blocker; access does not establish proprietary-source recovery or grant additional data access.

2. Probe and sample actual reference frames/playback, marking observed reveal timings and layout/type/motion behavior. Record inaccessible intervals as unknown, never inferred exact measurements.

3. Describe principles independently: hierarchy, temporal spacing, camera relation and contrast. Distinguish observed behavior from uncertain implementation guesses.

4. Reauthor with new content with retained source provenance and a distinct composition/sequence. Compile an authorized original scene; do not promise style cloning or convert inaccessible proprietary source.

5. Compare actual reference and original evidence side by side on declared principles. Retain differences and limitations; missing new render means analysis/treatment only, not a demonstrated recreation.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Reference hash / observed interval and frame / principle / uncertainty / original design decision / comparison artifact / retained difference.

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

Required role case **SK-S63-output**:

A reference with three timed reveals yields measured observations and a distinct original scene; missing reference frames stay unknown and no protected assets/source are extracted for reuse.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
