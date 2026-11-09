# Using Motion Studio with Hermes

## Begin with read-only discovery

In a compatible Hermes session with Motion Studio enabled, list projects with
`motion_project` and inspect available routes with `motion_capabilities`.
Tools are native Hermes calls, not a standalone unauthenticated HTTP API.

## Production sequence

1. Establish the brief, authorized assets, delivery targets and any spending limit.
2. Create or open the durable project.
3. Import or reference exact assets, assess the asset library and resolve gaps.
4. Save a visual storyboard with timing, motion, text and narration intent.
5. Author editable source and compile a capability-bound plan.
6. Review effects and obtain any required execution/data/spend approval.
7. Submit an owned job, monitor it and collect its actual outputs.
8. Review the exact candidate and produce the requested delivery or source package.

Keep returned IDs, revisions and hashes exactly. Reuse a request ID only when
retrying the identical request. An advertised capability is not proof that its
dependencies work on the selected host. Missing or unsupported routes should
report their specific blocker rather than simulate success.

## Tool families

- Projects and assets: `motion_project`, `motion_asset`, `motion_asset_library`.
- Preparation: `motion_storyboard`, `motion_plan`, `motion_capabilities`.
- Execution: `motion_run`, `motion_ui_handoff`.
- Finish and deliver: `motion_caption`, `motion_review`, `motion_deliver`.

All eleven tools and their action alternatives are documented in the
[registered reference](reference/tools.md). The package also registers 67
namespaced skills. Skills guide work; they do not prove a route was executed.

## Desktop and rendering boundaries

The Desktop plugin provides composition/timeline editing through the host SDK.
The backend requires the host compatibility checks in
[compatibility](compatibility.md). Local authored scenes use an explicit
frame/time contract; authored JavaScript is trusted code, not sandboxed content.
Kinetic packaging retains the engine's MIT notice and the font OFL notices.

A checked source release does not establish complete Desktop render/export
acceptance on every client. Native execution is currently Linux-focused.
