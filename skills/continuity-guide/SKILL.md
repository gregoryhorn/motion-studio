---
name: continuity-guide
description: "Maintain compact references to approved scene rules."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Continuity Guide

## When to use

Maintain continuity rules across approved scenes.

**Do not use for:** Exclude a second brand/timeline state store or automatically changing approved art.

Role boundary: Maintain approved project visual/motion rules across scenes; emit compact versioned continuity references.

## Inputs and output contract

Required inputs: Approved brand/treatment/motion revisions and scene decisions.

Requested output artifacts: Compact versioned continuity guide referencing authoritative artifacts and approved exceptions.

Required capabilities: Core revision/reference inspection
Optional capabilities: frame comparison.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update; motion_asset get for existing proof frames; motion_review inspect/record if actual comparison occurs.
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

1. Resolve approved brand, treatment, motion and scene decision revisions from project state. Do not create another authoritative palette, timeline or approval store.

2. Extract only stable cross-scene rules such as type hierarchy, camera axis, transition family and cue role; point each rule to its authoritative source and revision.

3. List approved exceptions with affected scenes and approval identity. A local inconsistency is not automatically an approved exception or license to change accepted art.

4. When a source revision changes, compare linked rule dependencies and produce a stale-scene list. Update the reference once rather than copying divergent values into every scene.

5. Optionally compare actual scene frames for drift, recording evidence separately from rule text. Return a compact guide and proposed corrective scope; never rerender or rewrite unrelated scenes automatically.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Rule / authoritative artifact and revision / dependent scenes / approved exception / stale references / observed drift evidence.

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

Required role case **SK-S39-output**:

A revised brand token produces one updated linked rule and a stale-scene list; it does not duplicate conflicting palettes or rewrite unrelated scenes.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
