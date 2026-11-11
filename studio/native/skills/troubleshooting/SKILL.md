---
name: troubleshooting
description: "Recover Motion Studio panel connections and saved state without generating media."
---

# Troubleshooting and saved-state recovery

Recovery never generates. Start from the intended existing Hermes chat/profile
and Motion Studio panel. Do not press Create, prepare a replacement, reconnect
under a guessed identity, change security settings or start another service to
repair a panel problem.

## What the panel means

- **Open saved creations / open a chat / context required**: select the intended
  existing Motion Studio chat in Hermes, then choose Open saved creations in
  Quick Create. `CREATION_CONTEXT_REQUIRED` needs supported chat context.
- **Connect this chat / workflow review required**:
  `CREATION_WORKFLOW_REVIEW_REQUIRED` or `PRODUCTION_WORKFLOW_REVIEW_REQUIRED`
  means this chat is not connected to the configured workflow. Review the
  existing Connections workflow; its authorized operator can connect this chat.
  Opening a panel or loading a skill grants no permission and generates nothing.
- **Primary unavailable / disconnected**: `CREATION_PRIMARY_UNAVAILABLE` or
  `PRODUCTION_PRIMARY_UNAVAILABLE` means the action was not sent. Select the
  supported already-open primary chat/profile/connection, then reopen saved work.
- **Access unavailable**: `CREATION_ACCESS_UNAVAILABLE` or
  `PRODUCTION_ACCESS_UNAVAILABLE` means that feature is not configured/enabled
  for this installed plugin/profile. Review existing setup with its operator.
  Production denial does not erase Quick Create work. Reopen is not a grant.
- **Scope denied**: this chat cannot access that creation/project/action. Open
  authorized work belonging to the intended chat. Do not switch identity to
  bypass `CREATION_SCOPE_DENIED` or `PRODUCTION_SCOPE_DENIED`.
- **Store busy**: another service owns the store. Wait, then explicitly reopen.
  Do not start a replacement service. **Store review required** needs operator
  review of identity/ownership; never adopt, delete or recreate saved state.
- **Retired / operation unavailable / invalid input**: reopen through the
  supported active service and reconcile saved state before another deliberate
  action. A failed reply is not proof that an earlier action had no effect.
- **Production unavailable (-32601)**: installed backend lacks the operation.
  Use Quick Create for saved creations and report the backend upgrade need;
  do not install or change permissions as part of recovery.
- **Out of date / stale revision / stale selection**: reopen the Production,
  inspect the latest brief/assets/references and retained selection. Old media
  and pins are preserved. Review the selected take; intentionally select it at
  the current revision only if still suitable. Never auto-clear, replace or generate.
- **Not reviewed / Needs work**: these are review outcomes, not an instruction
  to create another candidate. Ask for the desired change only if refinement
  is requested. **Matches request** records review, not proof of delivery.

## Read the saved state

`motion_studio_creation` agent operations are `status`, `prepare`, `start`,
`stop`; recovery here uses only `status`. With a known saved request use
`{"operation":"status","request":"<saved request>"}`. After ANY lost reply,
first use `{"operation":"status"}` without an ID to recover the same intent.
Report returned state/certainty/failure, not assumptions. Unknown or entered
launches cannot be rearmed. RESOURCE_BUSY is not authority to retry. Retry flags
may support a separate deliberately requested action; recovery itself does not start.
An empty current result is not proof that another chat's work was lost.

`motion_studio_production` recovery uses `list` with no extra fields and `open`
with a returned `production` ID. Reconcile the current revision and retained
asset/take state after an uncertain mutation; do not automatically repeat it.
Use the panel for saved creation listing, media retrieval and reopening. Never
invent an agent `list` operation for motion_studio_creation or pass panel RPC
operations as agent tool arguments. Do not claim playback, successful export or
cancellation from a status message alone. If the route remains unavailable,
report the safe code and unresolved step without private paths, media or raw errors.

Cost rule: the method's cost class from methods.list decides. For paid or unknown,
state provider and cost basis and get explicit user OK before calling. For free
or subscription, proceed with one bounded candidate and say which method was used.
