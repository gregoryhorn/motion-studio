---
name: social-delivery
description: "Produce checked variants from sourced platform profiles."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Social Delivery

## When to use

Produce requested social delivery variants.

**Do not use for:** Exclude posting publicly or assuming platform limits from memory.

Role boundary: Recompose and encode requested social variants; emit checked masters against sourced versioned profiles.

## Inputs and output contract

Required inputs: Approved timeline/candidate, requested variants, sourced profile version and crop/safe-zone decisions.

Requested output artifacts: Per-variant candidates, checked masters/sidecars and profile receipts.

Required capabilities: Reframe/resize; encode/mux; decode/probe; profile check; inspect pixels/audio.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_plan compile/inspect; motion_run submit/collect; motion_deliver encode/status/validate/promote; motion_review gates/record.
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

1. Freeze requested variants and a sourced profile version or explicit user override. Retrieve current platform rules through permitted source tools; never assume limits from memory.

2. Read approved timeline/candidate and crop decisions. Recompose subject and captions for each aspect rather than blindly cropping the master; preserve meaningful claims and supplied safe zones.

3. Compile selected reframe/resize and encode operations with explicit delivery parameters. Changed data movement or cost needs authority; no public posting is included.

4. Use motion_deliver encode/validate as supported and inspect each actual final file: full decode/probe, pixel bounds, audio when present, playback and matching sidecars.

5. Promote independently only exact variants with current required gate evidence and authorization. A failed portrait remains failed while valid landscape remains available; return per-variant receipts and missing work.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Variant / sourced profile revision / crop-safe-zone choice / candidate hash / validation-review receipts / promotion status / sidecars.

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

Required role case **SK-S49-output**:

Landscape and portrait requested: both keep subject/captions inside declared safe zones and meet frozen profile; a failed portrait remains failed while valid landscape stays available.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
