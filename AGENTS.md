# Agent instructions for Motion Studio

## Scope and ownership

This is the assembled public plugin repository, not the private development
source or the installed runtime. Read README.md, CONTRIBUTING.md, RELEASING.md
and tests/README.md before changes. Keep routine documentation and the Keep a
Changelog CHANGELOG.md consistent with the actual candidate. Public main and
the catalog-reviewed exact pin are separate delivery states.

app-design owns application designs, contracts and acceptance plans.
app-developer owns application code, tests and factual as-built documentation.
Implementation requires applicable app-design input and its revision first;
request missing coverage instead of inventing requirements. Maintenance owns
routine documentation and authorized hygiene, not code fixes or specialist
records. Consult relevant current as-built evidence, not stale completion claims.

## Git and assembly

Work only on main in the primary checkout. Inspect status/index and coordinate
per-path writers before editing. Preserve WIP and stage explicit paths only;
never absorb unrelated staged changes. No branches, worktrees, force pushes or
history rewriting. Verify the intended origin and authorized GitHub identity
before publication.

The private source and public package have different layouts and histories.
Never copy the private tree wholesale or merge those histories. Source promotion
requires the current assembly command and reviewed source-to-package receipt
from app-developer, as specified in RELEASING.md. Missing assembly evidence is a
blocker, not permission to improvise a build. Public docs-only edits do not need
a private-source rebuild.

Preserve private-to-public exclusions: var/, scratch/, graft/, HANDOFF*,
evidence/ and tools/check_live_production_backend.py. Do not publish credentials,
private operational records, caches, generated media, model weights, bytecode or
unreviewable executable payloads.

## Verification

Use a separately authorized development environment and approved temporary
storage. Set TMPDIR, TMP and TEMP there and PYTHONDONTWRITEBYTECODE=1. Never
install dependencies into live Hermes or use --install-deps against its venv.

The documented Python regression command is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Read tests/README.md for current public-layout checkpoints, existing Hermes
source, Node/browser prerequisites and fixture commands. Historical raw-source
commands are not a verified public assembly route. Missing source-only inputs
must be reported to app-developer, not replaced silently or bypassed with weaker
tests. Record exact candidate, commands, dependency versions, failures and skips.
Docs-only work requires explicit diff, whitespace, privacy and link checks;
do not claim an application suite ran when only documentation was checked.

Component tests, package validation and CI do not establish native host/UI
qualification. Maintenance does not generate media, install/enable or run the
production plugin, or automate browser/desktop flows. Authorized specialist
host qualification is a separate lane. Preserve user projects, originals and
history; technical PASS is not creative approval.

## Dependencies, catalog and publication

Foresight may be pinned only after completion and working native Windows AND
Linux qualification, including required host/UI acceptance. Use an immutable
release URL plus SHA256; a local-path wheel is not a distributable dependency.

Keep current Nous catalog requirements: no self-update, matching declared
capabilities and disclosures, truthful requires_hermes, bounded dependencies,
no committed bytecode/binaries and public SDK/registration surfaces only.
Preserve Hermes-scoped secret access and shared OAuth routing; never inspect,
copy or write OAuth tokens or use another tool's credential store. Obtain
maintenance secrets only through configured authorized Bitwarden routes.

Review the exact candidate and applicable checks before pushing. Follow
RELEASING.md for immutable tags/assets and read back every external write,
including the remote commit and published file blobs. Own-repository publication
does not update the catalog. Any NousResearch PR, issue or comment, including a
catalog SHA bump, requires the owner's explicit approval of the exact payload;
prepare a draft and never route through a delegate to bypass that gate.
