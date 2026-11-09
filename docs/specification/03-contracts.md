# Interface and workflow contracts

The registered native schemas are the executable input contract. See
[tool reference](../reference/tools.md) and the complete
[JSON schemas](../reference/tool-schemas.json). Internal Python functions are not
a separately promised stable public API.

Mutating operations use explicit request identities and optimistic revisions.
Keep returned project, document, artifact, job and candidate references literal.
Approval is scoped to the actual effects, inputs and selected target. Reading
metadata or discovering a capability never grants execution or spending authority.

Asset assessments precede visual storyboards. Plans bind exact sources and
capabilities. Jobs own their subprocesses and collected outputs. Review applies
to exact candidate bytes; edits or re-encoding invalidate earlier byte-bound
results. Delivery does not turn an unavailable route into a supported one.

Errors and blocked responses are outcomes to report, not permission to bypass
path, ownership, resource, host-compatibility or approval checks.
