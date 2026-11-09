---
name: brand-system
description: "Define versioned visual, motion and audio tokens."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Brand System

## When to use

Formalize an approved identity into reusable production tokens.

**Do not use for:** Exclude repeating intake or overwriting a supplied brand without a requested change.

Role boundary: Turn approved identity into reusable visual/motion/audio tokens; emit versioned brand contract, not another intake.

## Inputs and output contract

Required inputs: Approved intake, logo/font assets and any supplied source facts, project delivery aspects and audio identity constraints.

Requested output artifacts: Versioned brand artifact with type/color/layout/motion/audio tokens and sample frames.

Required capabilities: Font/layout support; render representative frame; inspect pixels.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_project open/status/update; motion_capabilities inspect; motion_plan compile; motion_run submit/collect; motion_review record.
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

1. Start from approved intake and any supplied provenance. Resolve exact font family/files and permitted fallback; unavailable fonts require disclosure and a decision rather than a visually similar silent substitution.

2. Define color roles, typography scale, spacing, logo exclusion zones and aspect-specific layout rules in one authoritative brand artifact. Mark every proposed value separately from approved values.

3. Add motion duration/easing roles and audio identity constraints only to the extent requested. A silent identity can explicitly omit audio rather than acquire a sound logo.

4. Compile sample layouts in each requested aspect using the same token revision. Render real representative frames, inspect actual glyphs/contrast/logo clearance and record failing cases.

5. Publish references to one approved brand revision; list dependent scenes needing review when it changes. Never create private per-scene token forks to conceal inconsistency.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Token role / value / source or approval / fallback / aspect rule; sample-frame references and affected scene list.

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

Required role case **SK-S08-output**:

Apply a supplied palette and supplied font to two scene aspects: actual samples use the same tokens, unavailable font is disclosed and no scene receives a private divergent brand copy.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
