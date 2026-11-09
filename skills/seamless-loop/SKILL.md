---
name: "seamless-loop"
description: "Use when making a verified seamless motion or audio loop."
version: "0.1.0"
author: "Hermes Agent (independent B14 authorship)"
license: "Unspecified; project owner decision pending"
platforms: ["linux"]
---

# Seamless Loop

## Trigger and exclusions

Produce a seamless motion or audio loop. Exclude a simple duplicated clip without checking the join.

## Required inputs

- Loop duration, scene/source, audio policy and boundary intent.

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

`scene.render@1`, `edit.assemble@1`, `media.extract_frame@1`, `inspection.visual@1`, `inspection.playback@1`; use `scene.frame@1` for state checks. With audio, require supported sample/phase evidence and `inspection.audio@1`; `audio.mix@1`/`audio.measure@1` apply only within their declared checks.

## Role procedure

1. Fix the period in frames and, if present, samples at authoritative rates. Define whether motion wraps continuously or has an intentional reset; an intentional discontinuity must not be advertised as seamless.

2. Close object position, orientation, visibility and velocity across the wrap. Sample [0,period) rather than duplicating the endpoint and introducing a held beat; first/last images need not be identical for continuous motion.

3. If audio is included, inspect actual sample/phase and envelope continuity at the join. A loudness/clipping report does not prove phase alignment or absence of a click; unsupported waveform analysis is an explicit evidence gap.

4. Assemble enough adjacent periods to inspect two wraps. Examine join-neighbor frames, playback speed and optional audio audition around both joins; do not claim success from a duplicated clip or matching stills alone.

## Outputs and evidence

- Loop source/master, endpoint state and join playback evidence.

Return editable loop source and retained candidate/master status, endpoint state/velocity records and actual join playback/audition coverage. Calling bytes a master requires the shared release path, not this role alone.

## Acceptance SK-S33-output

A rotating motif and optional tone join twice without a visible jump or audible click; compare join-neighbor frames and audition, not just identical first/last stills.

This is the acceptance fixture to execute, not an observed result. B14 authored
these instructions independently from the documented requirements; no old-pack
implementation or reuse license is asserted. Static checks do not establish skill
registration, adapter exercise, visual quality or release acceptance. Record real
fixture evidence only after the selected binding and authorized run are available.
