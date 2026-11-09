---
name: code-job
description: "Run reviewed media source as an owned bounded job."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Code job

## When to use

Execute task-owned authored media source as a bounded job. Exclude arbitrary shell RPC, user-string command interpolation or private tool-handler calls.

## Inputs and retained outputs

Required: Reviewed source artifact/hash, explicit operation/binding, resource/time limits and allowed inputs/outputs.

Produce: Owned job/attempt receipt, logs reference and validated actual artifacts. Attach each output to its current
project and applicable scene/asset revision; retain editable source and actual
bytes, not only a screenshot, URL or completion message.

## Authority and execution boundary

Follow the shared production instructions in `motion-studio:studio-produce`
before this specialist procedure; load that qualified skill, not a relative
cross-skill file link. Resolve current project/scene/asset IDs, expected revision,
input hashes and selected binding from actual tools. Preserve supplied provenance/
attribution facts without demanding rights clearance. Unknown or restricted rights
and absent licenses do not block production, release or packaging. Work only on declared
task-owned candidates; preserve immutable sources and approved outputs. Changes
invalidate only affected descendants. Record binding/version, job/attempt, input
and output hashes and inspected frame/sample coverage in the project.

This is independently authored guidance, not a qualified runtime route. Linux
identifies the authoring host only; adapter/platform production support is not
established. Use only advertised public actions and schemas. Missing engines,
`NOT_IMPLEMENTED`, absent actions or unsatisfied required features mean blocked:
name the operation/feature and smallest remedy, preserve existing artifacts and
return the gap. Do not fabricate media, timing, receipts or acceptance. Do not
install dependencies/models, modify configuration, upload, spend or substitute a
provider without separate authority. Optional unsupported work need not block
unrelated valid outputs. Binding changes require a revised plan, potentially new
native source, not a promise of lossless translation.

## Required and conditional capabilities

Use a selected registered media operation, such as `scene.render@1`, through
its authorized adapter. There is no generic execute-code or shell operation.
Require adapter ABI `inspect`, `validate_request`, `execute`, and the supported
`status`, `cancel`, `collect` lifecycle plus output `media.probe@1` where relevant.
Unsupported lifecycle methods must be disclosed, never simulated.

## Procedure

1. Resolve reviewed source/hash, imports/assets, allowed reads/writes, selected
   operation/schema and explicit time/resource limits. Inspect source provenance
   and output ownership. Unreviewed arbitrary code, user-interpolated shell text
   and arbitrary filesystem output are out of scope; return the exact refusal.
2. Validate structured operation parameters and registered binding options against
   their pinned schema/hash. Keep source as an input artifact rather than executable
   text smuggled through an unrelated parameter. Validate output paths under the
   owned candidate directory, including traversal/symlink escape policy.
3. Compile the bounded node with frozen inputs, plan/revision and declared effects.
   Invoke only the public authorized route. For host-only execution, require an
   exact typed handoff and normal host call, not a private handler import. Path and
   deadline validation do not establish an OS security sandbox; disclose isolation
   limits and refuse work whose safety depends on absent isolation.
4. Observe the owned job/attempt. On deadline, request cancellation only for that
   verified identity and inspect its real state. A timeout or cancel request is
   not proof the worker/provider stopped; preserve uncertainty for reconciliation
   and never kill unrelated processes or resubmit uncertain work.
5. Collect only declared outputs, verify actual bytes/hash and media shape/full
   decode as appropriate. Retain bounded logs and partial artifacts with failure
   state. Return job/attempt receipts and per-port outcomes; process exit zero is
   insufficient when required media is missing or outside owned paths.

## Verification

**SK-S52-output (future empirical acceptance, not yet passed):** A title-render job writes only its owned candidate; an output escaping the project is refused and a timeout cancels only that job, without claiming a security sandbox that the host does not provide.


## Pitfalls and handback

Report actual artifacts separately from intended outputs and unresolved gaps.
Retain failed/partial jobs and any prior approved version. Compilation, selecting
a binding, source inspection and this authoring test are not production evidence;
a newly rendered preview is an execution job. Submit only a frozen authorized
plan, reconcile uncertain effects before any retry, and use normal host approval
for typed handoffs. Return the current revisions and real artifact handles to
`motion-studio:studio-produce`; candidate encode, decode/measurement, frame/audio/
playback review and exact-byte promotion remain required when applicable. Never
turn specialist judgement into user approval or mark a route exercised from mocks.
