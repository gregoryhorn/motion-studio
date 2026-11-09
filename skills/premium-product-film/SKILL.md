---
name: premium-product-film
description: "Direct an original product reveal from verified facts."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Premium Product Film

## When to use

Create an original premium product reveal.

**Do not use for:** Exclude copying a named launch campaign or requiring a brand's assets.

Role boundary: Translate premium product direction into original pacing/material/lighting decisions; emit storyboard and scenes, no brand imitation requirement.

## Inputs and output contract

Required inputs: Verified product claims, supplied product assets, approved direction and duration.

Requested output artifacts: Original storyboard, material/light/pacing treatment and rendered scenes.

Required capabilities: Probe/stage assets; render 2D or 3D; evaluate frame; inspect pixels.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
motion_asset import/probe; motion_capabilities inspect; motion_plan compile/inspect; motion_run submit/status/collect; motion_review record.
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

1. Build a claim/asset table: each product property needs supplied evidence; silhouette, gloss and atmosphere are treatment proposals, not new product facts.

2. Divide the reveal into silhouette, detail and use beats. Specify the purpose of each camera/framing choice and a readable hold for labels; do not reproduce a named campaign shot list.

3. For each material, state roughness/transparency/light intent and what real product detail must remain unchanged. Choose 2D or 3D from the approved asset and compatible binding, not prestige.

4. Compile representative stills before the full sequence. Compare actual frames for shape fidelity, highlight clipping and contrast; record proposed changes separately from approved direction.

5. Run only the approved scene plan; review the actual reveal transition and use beat. Missing rendering leaves a treatment/storyboard, not a rendered film.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Beat / verified claim / asset / framing-light intent / duration frames / actual frame reference / review finding.

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

Required role case **SK-S02-output**:

A supplied lamp gets silhouette/detail/use beats in an original sequence; every claim traces to supplied facts and no third-party logo or copied shot is introduced.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
