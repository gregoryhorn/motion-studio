# Security and execution effects

Motion Studio runs inside Hermes and is not a sandbox for arbitrary authored code.
Scene source and local executable bindings must be trusted before execution.

Registration is passive. Explicit jobs can read authorized assets, create project
and job records, launch bounded local media subprocesses, render through Chromium,
and write validated artifacts and deliveries. Optional provider routes can send
approved inputs or incur costs only through the selected authorized binding.
No provider credentials or model files are included.

The plugin preserves host admission, owner/session validation, path containment,
revision checks and exact-candidate approval. Do not weaken those checks to make
an unsupported host appear compatible.

Catalog validation can report subprocess/resource-access cautions and imports
from non-public Hermes modules. These are disclosed compatibility risks, not a
catalog approval. See [compatibility](docs/compatibility.md).

For a security report, do not post credentials, private media, authentication
tokens or personal records in a public issue. A sanitized reproducer, affected
commit and observed behavior are enough to start investigation.
