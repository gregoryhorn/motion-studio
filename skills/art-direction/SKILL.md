---
name: art-direction
description: "Establish a production-specific visual grammar."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Art Direction

## When to use

Establish visual grammar for a production.

**Do not use for:** Exclude compulsory luxury/minimal style and per-frame defect review.

Role boundary: Define typography, palette, composition and material language; emit approved visual grammar and representative frames.

## Inputs and output contract

Required inputs: Brief, approved brand, references, accessibility and delivery aspects.

Requested output artifacts: Type/palette/composition/material treatment and representative approved frame candidates.

Required capabilities: Layout/type; render representative frames; inspect pixels.
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

1. Read brief, approved brand and delivery aspects. Classify references by hierarchy, composition or material principle; do not treat a luxury/minimal preference as a universal requirement.

2. Specify headline/support hierarchy, contrast, focal region and background behavior with concrete layout rules. Preserve accessibility and the product's actual representations.

3. Choose material language and composition appropriate to the message, explaining exclusions. Hand temporal choreography to motion-language rather than duplicating its job.

4. Compile representative layouts for both dense and sparse scenes in the requested aspects. Inspect actual rendered type, crops and visual hierarchy, not only numerical bounding boxes.

5. Return proposed treatment, actual sample references and review findings. Only an identified approval converts the treatment to accepted direction; per-frame defect closure belongs to later review.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Hierarchy / palette role / composition / material / rationale / aspect adaptation / proposed-or-approved / sample evidence.

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

Required role case **SK-S24-output**:

Two aspects retain coherent supplied identity and legible type without forcing a preferred house style; unapproved treatment remains proposed, not an accepted brand change.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
