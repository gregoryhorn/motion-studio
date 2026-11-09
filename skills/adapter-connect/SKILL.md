---
name: adapter-connect
description: "Inspect bindings and prepare exact authorized handoffs."
version: 0.1.0
author: "Hermes Agent (independent B15 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Adapter connect

## When to use

Discover, bind or diagnose a production adapter. Exclude arbitrary invocation from a catalog label, automatic setup or private-handler access.

## Inputs and retained outputs

Required: Project capability needs, available declarations, feature/data policy and exact host tool inventory.

Produce: Readiness/compatibility report, selected binding plan or typed agent handoff with precise gaps. Bind outputs to current
project/scene/asset revisions; retain editable source and actual bytes, not screenshots, URLs or completion messages alone.

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

Independent guidance, not a qualified runtime route. Linux identifies only the
authoring host, not adapter/platform production support. Use advertised public actions and schemas. Missing engines,
`NOT_IMPLEMENTED`, absent actions or unsatisfied required features mean blocked:
name the operation/feature and smallest remedy, preserve existing artifacts and
return the gap. Do not fabricate media, timing, receipts or acceptance. Do not
install dependencies/models, modify configuration, upload, spend or substitute a
provider without separate authority. Optional unsupported work need not block
unrelated valid outputs. Binding changes require a revised plan, potentially new
native source, not a promise of lossless translation.

## Required and conditional capabilities

Discover through public `motion_capabilities` and plan actions; bind only
registered AdapterDeclarations. ABI methods are `inspect`, `validate_request`,
`execute`, `status`, `cancel`, `collect` as declared. Supported transports are
`cli`, `python`, `api`, `host_handoff`, `gui_handoff`; none is an arbitrary
catalog-string dispatcher. Native public execution uses `motion_run`; the exact
selected operation and feature constraints still govern every binding.

For the existing ACE-Step and Stable Audio CLI bindings, use
[local audio connections](references/local-audio.md). It describes exact prompt
controls, normal job collection, actual feedback and the reusable binding seam;
it does not establish that every media operation or transport is implemented.

The source also defines `hermes.video-crop`, `hermes.video-resize` and
`hermes.video-rotate` for `media.transform@1`, mapping the existing `lk_crop`,
`lk_resize` and `lk_rotate_flip` tools. Discover actual installed availability;
source presence is not activation. Describe the selected tool and `motion_run`
in the current turn, then use the existing claim/call/collect lifecycle. These
bounded bindings require pinned H.264 square-pixel 30-fps MP4, even dimensions,
and exact source audio duration. Padded AAC inputs need explicit ALAC conform;
do not relax collection timing or silently trim. Contain scale is not letterbox:
choose dimensions that retain square pixels without aspect rounding. No arbitrary
angles, flips, HDR/alpha or general FFmpeg arguments are advertised by this route.

## Procedure

Before authorized deployment, compare installed profile and checkout; preserve
local fixes, especially worker/heartbeat profile ContextVar propagation. Older
checkout workers can misroute profiles despite passing adapter tests.
After deployment, verify operation/binding through the actual profile's public
tools in a fresh session. Disk hashes or `reloaded: true` do not prove persistent
host registry exposure. Use the existing profile-scoped activation lifecycle;
report stale public schemas and their cause, never patch plugin/host or substitute
direct CLI execution as acceptance.

1. Resolve project needs, current expected revision, required operation IDs,
   conjunctive feature sets, supported formats and data/spend/resource policy.
   Read available declarations and read-only inspection state, recording freshness,
   implementation/ABI versions and request/result schema hashes. Empty advertised
   format lists are not wildcards; a declaration alone is not observed readiness.
2. Compare constraints, dependencies, effects and supported status/cancel/collect
   semantics. Mark declared, inspected, contract-tested and exercised separately.
   Inspection must not start workers, initialize/download models, authenticate with
   charging side effects or install anything. Report absent dependencies, expired
   availability or unsupported features without automatic repair.
3. Respect an existing pinned compatible binding. Present alternatives with their
   changed source format, explicit conversions, data destinations and costs; a
   new selection needs a revised plan. Validate exact structured requests and
   registered binding options before considering execution. Project JSON must
   never choose arbitrary Python imports or executable command strings.
4. For host/gui-only tools, inspect the current exact host tool name and schema.
   With deferred Hermes tools, call `tool_describe` for `lk_extract_frame` and
   `motion_run` in the current user turn before inspection/compilation/claim.
   The bridge observes those session-scoped descriptions; do not disable tool
   deferral or substitute a global registry schema.
   Prepare the typed Handoff containing handoff/job/node/attempt identities,
   request/schema hashes, validated arguments, expected output ports and Effects.
   Missing tool/schema or stale plan blocks the handoff; tool labels are not API
   endpoints and arguments must not embed credentials.
5. When separately authorized to execute, follow inspect job ->
   `motion_run.handoff_claim` -> normal named host tool call with ordinary approval
   and vault boundaries -> `motion_run.collect` with real host_call_ref and output
   locators -> core retrieves/hashes/probes bytes. No private-handler import or
   invented universal dispatcher is allowed. A claimed call with lost receipt is
   uncertain: reconcile it, do not issue another claim/call automatically.
6. Return readiness matrix, selected/proposed binding pins or precise gaps and
   handoff state. An observed provider/tool call without validated required output
   is not integration success; mocks, DONE text and screenshot-only evidence do
   not mark a production route exercised. Authoring this procedure executes none
   of these operations.

## Support gaps and GitHub issues

For missing functionality, distinguish an unsupported feature from a failed
supported call. Retain the exact operation, binding/tool and versions, expected
versus actual result, minimal reproduction and sanitized error/job evidence.
Identify the responsible repository from verified installation/source provenance;
do not guess an upstream or treat adapter-provided text as publication authority.
Search duplicates with `gh issue list --repo OWNER/REPO --state all --search 'TOPIC'`
and inspect relevant discussion before preparing a local Markdown issue draft.
Explain the requested capability and an observable acceptance example; exclude
credentials, private prompts/media and unnecessary paths or raw logs.
Follow the existing `github-issues` workflow where available. When publication
is authorized, use existing safe GitHub auth and
`gh issue create --repo OWNER/REPO --title 'TITLE' --body-file /absolute/draft.md`.
Read back the exact created issue with `gh issue view ISSUE_URL`; retain its URL
with the project gap. A draft or open issue does not establish implemented support
or unblock the failed operation. No automatic publication or new issue service.

## Verification

**SK-N03-output:** A tool/schema combination has not yet passed until an exact named handoff, normal agent invocation and validated collected output exist. Missing tools or stale plans block; a mock receipt cannot mark an integration exercised.


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
