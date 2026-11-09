---
name: "interaction-timing"
description: "Use when mapping interaction choreography to video frames."
version: "0.1.0"
author: "Hermes Agent (independent B14 authorship)"
license: "Unspecified; project owner decision pending"
platforms: ["linux"]
---

# Interaction Timing

## Trigger and exclusions

Translate interaction/scroll choreography into video timing. Exclude relying on live scrolling during offline export.

## Required inputs

- Interaction states, intended progression, frame rate and final duration.

## Production boundary and freshness

Use motion-studio:studio-produce for shared production authority, state reconciliation,
job handoffs and release rules; this role does not replace that coordinator.
Resolve IDs through `motion_project` list/open/status and `motion_asset` get as needed.
Pin project/document revisions, immutable input hashes, scene/asset relationships,
selected binding implementation/schema digests and execution authority before work.
Retain supplied source/attribution facts; unknown or restricted rights and absent
licenses do not block production, release or packaging. Do not demand clearance.
Authoring host: Linux; this is not verified cross-platform runtime support.

Discover/inspect selected bindings with `motion_capabilities`; inspect their exact
registered schemas, ports and supported formats before using the operations below.
Canonical operation IDs describe contracts, not callable host tool names. Use only
native actions actually advertised by the host. Selection, compilation and viewing
existing evidence do not execute; a newly rendered preview is a job. Use
`motion_plan` compile/inspect at current expected_revision, then authorized
`motion_run` submit/status/collect. No private dispatcher, hidden code execution,
setup-on-load, dependency installation or automatic provider spend is permitted.

A missing binding or mandatory feature is an actionable gap: name operation,
feature and blocked output, preserve inputs and approved artifacts, and stop that
target. `NOT_IMPLEMENTED` is a blocker, never a simulated result. Offer alternatives
only as proposals requiring revised binding/plan and changed-effect authorization.
An optional unavailable demonstration need not block independent written work.

Frozen evidence is invalidated for the affected dependency descendants when source,
assets, timing, brand, options, input bytes or binding/schema digests change. Reopen
current revisions, reconcile intent and compile a new plan; retain prior source and
bytes. Never relabel old review evidence as current. Rebinding may require native
source reauthoring, not lossless translation. Report actual output hashes, revisions,
job/plan references and inspected frame/sample coverage; missing output is pending,
not success. Only the shared candidate/review/promotion path can release a master.

## Operation and feature contract

Core timeline authoring; `scene.author@1`, `scene.frame@1`, `scene.render@1` with `timing.frame_seek`, `timing.frame_exact` and the selected scene feature. Live browser scroll is not an export dependency.

## Role procedure

1. Enumerate interaction states and the user-visible conditions that distinguish them. Record the intended three-section progression as explicit state names, not captured scroll offsets that depend on viewport or device.

2. Allocate state entry, transition and hold intervals at the project rational frame rate. Define a deterministic mapping from frame to progress and state, with exact boundary inclusion and progress clamp.

3. Freeze viewport, content lengths, fonts and layout measurements. Replace live scrolling, pointer events and wall-clock callbacks with frame-driven inputs; preserve interactive meaning without claiming the offline film is a functioning app.

4. Seek directly into each section and around every state boundary without first replaying earlier states. Compare those outputs to sequential evaluation at the same frames; investigate any mismatch as state leakage or unfrozen layout.

## Outputs and evidence

- State-to-frame cue map, seekable source and boundary samples.

Return a state-to-frame cue map, seekable native source and boundary samples with expected versus observed active state. Missing seek support blocks offline-choreography evidence, not the written cue proposal.

## Acceptance SK-S21-output

A three-section scroll story seeks directly to each section offline with no scroll event; replay and random seek agree at the same frame.

This is the acceptance fixture to execute, not an observed result. B14 authored
these instructions independently from the documented requirements; no old-pack
implementation or reuse license is asserted. Static checks do not establish skill
registration, adapter exercise, visual quality or release acceptance. Record real
fixture evidence only after the selected binding and authorized run are available.
