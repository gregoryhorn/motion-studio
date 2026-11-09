---
name: studio-produce
description: "Use when starting or resuming a bounded media production."
version: 0.1.0
author: "Hermes Agent (independent B02 authorship)"
license: "Unspecified; project owner decision pending"
platforms: [linux]
---

# Studio produce

## Source facts, not rights clearance

Use/redistribution-rights clearance is not a production, release, promotion or
package prerequisite. Unknown/restricted rights and absent licenses must not
block these operations or prompt demands for a license or permission statement.
Retain truthful source provenance, supplied attribution/license facts and unknowns;
never relabel them as cleared or invent grants. Historical license/frontmatter
metadata is unchanged. Execution, data transfer, spend, privacy/identity consent
and host approvals still apply, as do all creative, technical, art, audio and
delivery-profile quality gates. This policy grants no external legal rights.


## Trigger and exclusions

Coordinate production or resume delivery. Corrections preserve approved direction
without restarting concepts. Exclude critique, installation, posting and
filesystem administration.

Use only actions and argument schemas actually advertised by the host. Source
implementation and activated installed behavior are separate evidence. If a
required action returns `NOT_IMPLEMENTED`, stop at that boundary, preserve the
project and report it. Do not simulate its result or bypass it with private code.

Read the [shared production contract](references/production-contract.md).
Catalog states distinguish planned, authored, reviewed, loadable and exercised
specialists; listing alone establishes no callable skill. Linux is the authoring
host, not cross-platform qualification.

## Inputs and outputs

Resolve the current project ID and revision, exact user outcome, requested
variants/sidecars/editable package, execution authority and any supplied source facts, selected
capabilities and existing artifacts. Ask only for missing decisions that change
the route. Never invent IDs, approval receipts, source timing or output handles.

Return the updated project/plan references and revisions, actual jobs and review
receipts, verified deliverable handles per variant, preserved artifacts, and a
specific blocker or remaining acceptance decision. A plan, candidate, master and
reconstructable package are different outputs, not interchangeable success.

## Procedure

1. **Recover before changing.** Resolve the project using `motion_project` list
   if needed; open and status read durable state without starting work. Page
   relevant scenes, assets, jobs and variants. Read existing job status before
   proposing another submission. On interrupted/uncertain work, use `motion_run`
   reconcile with the current job revision; reconciliation observes existing
   effects, never submits a retry. Preserve unknown remote effects for lookup or
   an explicit user decision, not speculative resubmission.

2. **Bound the change.** Compare the request with authoritative brief, brand,
   timeline and document revisions. Identify unchanged inputs and only affected
   dependency descendants. For a caption-only correction, retain narration and
   scene renders; use `motion_caption` get/correct/style as applicable. Spelling
   corrections and wording/timing changes are not equivalent: changed wording
   needs supported alignment or actual timing review before rendering. A silent
   production needs no invented narration or transcript. Apply permitted content
   changes with current `expected_revision`; on a stale conflict, reread and
   reconcile intent rather than overwriting a newer revision.

3. **Agree the creative plan before production.** Ask once for the requested
   involvement level (automatic, guided or granular), unless already supplied.
   Retain per-area delegation for script, direction, storyboard, audio and timing.
   Explicitly discuss the storyboard/visual direction unless delegated or declined.
   Save an editable timed script and practical dependency-linked tasks through
   `motion_plan creative_update`; use `creative_get` to present copy, frame timing,
   assumptions, missing inputs and affected beats. For automatic planning, settle
   routine choices independently under the actual delegation. A changed involvement
   level must not restart accepted work. Record exact user agreement/delegation
   with `creative_accept` using real current-session message evidence; never use an
   agent-authored ready flag. This is creative scope, not spend or execution consent.
   Revise linked panel copy/timing and the creative plan together via one
   `motion_project update` when either changes. Preserve unaffected beat IDs,
   artifacts and tasks rather than rebuilding the whole project.

   **Know assets before visual planning.** Use `motion_asset_library get` to
   inspect registered inventory. Inspect supplied material, import/reference exact
   selected bytes through `motion_asset`, and save requirements, assessments and
   explicit acquisition approaches with `motion_asset_library update`. Resolve
   required gaps before setting `assessed: true`. Then use `motion_storyboard`
   to save ordered visual panels bound to the current asset-library document hash.
   Each panel needs a registered raster image/frame, frame duration, linked asset
   requirements, narration/text, motion and transition. Present its `view` for
   discussion; edits/reorders/feedback are saved with `update`, not browser
   controls. Reconcile stale boards after asset changes. `ready` is agent readiness,
   never user acceptance. Track newly introduced asset needs back in the library;
   do not invent search, acquisition, image generation or rendering capabilities.

4. **Choose the minimum route.** Discover cached capability declarations through
   `motion_capabilities`, inspect exact operations/features and honor selected
   bindings. No startup, install or provider request occurs during discovery.
   Load only a relevant authored and available namespaced specialist: for example
   `motion-studio:caption-author` for caption work or
   `motion-studio:revision-review` for finding closure. If absent, report that
   role as unavailable; never load a bare old-pack substitute. Do not force
   specialists when the current authoritative inputs already satisfy their role.

5. **Freeze before running.** Compile the smallest `motion_plan` graph with
   current `expected_revision`, requested targets and `reuse_outputs: true`.
   Inspect its nodes, gaps and effects. Selection and compilation do not run
   production. Disclose the actual binding, local/remote data movement, charging
   basis or unknown cost, and new permissions. Missing required features or
   execution authority block the affected target; unsupported optional operations do not block
   unrelated valid work. A different engine/source format is a proposed revised
   plan, not an automatic conversion or fallback.

   For local filmmaking, import a `motion/v1/source-bundle` manifest containing
   hashed HTML/JS/assets; pin it as `authored_source`. Retain assessed
   storyboard/library and panel bindings. `source_runtime.entry_member` is the
   full relative HTML path. Trusted JavaScript runs in Chromium, not an OS
   sandbox. Author orientations separately; freeze/collect before switching the
   timeline. Assemble only explicitly collected scene artifacts. Changed source,
   engine, assets, timing or layout invalidate affected consumers, not unrelated
   approved assets or soundtrack.

6. **Execute only authorized effects.** Submit the frozen ready plan through
   `motion_run` using the advertised request/authority fields. Reuse its request
   identity for an exact retry; never change payload under that identity. Status
   is observational. A typed native-tool handoff requires `handoff_claim` before
   the exact normal host-tool call, respecting approval/vault boundaries. Record
   its real receipt with collect; never call a private handler or generic hidden
   dispatcher. Claim-without-result is uncertain work to reconcile, not retry.
   Cancellation is complete only when the returned state proves it.

7. **Collect and review actual outputs.** Collect retained bytes and validated
   receipts. Partial success names missing ports and variants. Newly rendered
   previews are jobs, not passive viewing. Encode a candidate before final
   checks; inspect decoded frames, audio when present, playback and required
   sidecars against those exact candidate bytes. Record findings with frame or
   sample coverage and hashes via `motion_review`; deterministic checks do not
   substitute for required visual/audio judgement or user acceptance. Repair only
   affected descendants, then recheck the changed candidate.

8. **Promote and hand back honestly.** Use `motion_review` gates and
   `motion_deliver` status to establish current evidence; promote only the
   authorized checked candidate set
   with current content/master revisions. Never replace approved masters on a
   failed gate. Package requested sources and matching sidecars; distinguish
   archive creation from successful reconstruction. Read files/status and return
   only real verified handles. If a requested portrait render is unavailable,
   report it blocked even when the landscape master exists; do not call the
   whole request complete. Summarize what exists, what was preserved, what is
   missing and the smallest next authorized action. No upload or public posting.
