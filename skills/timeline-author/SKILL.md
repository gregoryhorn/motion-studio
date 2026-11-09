---
name: "timeline-author"
description: "Use when authoring frame-accurate motion sequences."
version: "0.1.0"
author: "Hermes Agent (independent B14 authorship)"
license: "Unspecified; project owner decision pending"
platforms: ["linux"]
---

# Timeline Author

## Trigger and exclusions

Author frame-accurate motion sequences. Exclude transcript timing invention and brand direction.

## Required inputs

- Scene durations, dependencies, cues, rational rate and transition rules.

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

Core integer/rational frame arithmetic; `scene.author@1`, `scene.frame@1`, `scene.render@1` or `edit.assemble@1` as the source requires. Render evidence needs `timing.frame_seek`/`timing.frame_exact` where exact seeking is required.

## Role procedure

1. Collect scene durations, cue dependencies and transition intent at the unchanged project rational rate. Keep source audio/sample timing distinct; never fabricate narration or transcript cue timing to fill a sequence.

2. Represent placements as integer half-open intervals [start,end). Compute starts and durations with tools, and encode intended overlaps as explicit transitions rather than treating every overlap as an error.

3. For the two 60-frame scenes and 12-frame overlap fixture, calculate the second start, shared interval and union duration. Assert dependency order, no unintended gap, positive durations and no transition longer than its available handles.

4. Publish the timeline through its authoritative project update with current expected_revision. Render before/at/after both overlap boundaries and compare coverage with assertions, retaining original source timing and scene relationships.

## Outputs and evidence

- Timeline artifact, sequence source and gap/overlap assertions.

Return the timeline artifact, sequence source and computed interval assertions; include boundary frame evidence separately. Timing calculations can be valid before rendering, but do not establish an exercised sequence.

## Acceptance SK-S22-output

Two 60-frame scenes with a declared 12-frame overlap have the documented shared interval and no unintended gap; inspect frames before/at/after both transition boundaries.

This is the acceptance fixture to execute, not an observed result. B14 authored
these instructions independently from the documented requirements; no old-pack
implementation or reuse license is asserted. Static checks do not establish skill
registration, adapter exercise, visual quality or release acceptance. Record real
fixture evidence only after the selected binding and authorized run are available.
