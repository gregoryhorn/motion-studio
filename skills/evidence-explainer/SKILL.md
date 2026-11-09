---
name: evidence-explainer
description: "Build original editorial stories from cited evidence."
version: 0.1.0
author: "Project contributor attribution pending; Hermes Agent draft"
license: "Unspecified; project owner decision pending"
platforms: [linux]
metadata:
  hermes:
    tags: [motion-studio, B13, authored-guidance]
    related_skills: [studio-produce]
---

# Evidence Explainer

## When to use

Build a sourced original editorial explainer.

**Do not use for:** Exclude imitating a named publisher's identity or presenting unsupported causal claims.

Role boundary: Build an original editorial explainer from cited facts; emit sourced narration, data visuals and scene plan.

## Inputs and output contract

Required inputs: Cited facts/data, evidence dates, audience question, delivery constraints and any supplied source facts.

Requested output artifacts: Claim/source ledger, original narration/script, data scenes and explanatory sequence.

Required capabilities: Source reading; chart/scene render; edit; actual speech/captions if narration selected; inspect/audition.
Optional capabilities: None required by this role.
These are semantic requirements, not invented native action names or adapter IDs.

## Prerequisites and native actions

Inspect the live advertised schemas before acting. Relevant native actions:
read_file/web_extract for authorized sources; motion_plan compile; motion_run submit/collect; motion_caption get/timing_review when selected; motion_review record.
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

1. Inventory cited facts, data versions, dates and any supplied source facts; define one audience question. Mark inference, disputed claims and missing evidence distinctly from facts.

2. Outline question/evidence/conclusion and write original narration or silent text. Do not imitate a publisher's identity or turn correlation into causation.

3. Calculate derived values with execute_code or terminal and preserve denominator, units and formula. Tie chart axes, labels, periods and caveats to source data rather than illustrative invented values.

4. Compile data scenes and explanatory sequence with selected bindings. Speech/captions are optional only when selected; use actual speech/timing evidence and matching text rather than imagined narration duration.

5. Inspect rendered chart pixels, playback and actual audio if present against the claim ledger. Return script, data-scene references and unresolved factual/output issues; remove unsupported lines instead of making them sound certain.

## Small reviewed handoff

Use this role-specific record, adding real references only:

Claim / source and date / fact-or-inference / data derivation / narration-text / chart-scene / actual verification and caveat.

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

Required role case **SK-S64-output**:

A supplied trend dataset produces correctly labelled chart and qualified explanation; correlation is not rewritten as causation and unsupported lines are removed or marked unresolved.

Exercise that case with actual role artifacts and relevant final-byte review when
the required runtime exists; also check the exclusion and missing-capability paths.
A frontmatter/link check is authorship hygiene only. This draft does not claim
routing, live skill loading, provider execution, output acceptance or B13 completion;
B11/B12 production evidence and later independent review remain pending.
