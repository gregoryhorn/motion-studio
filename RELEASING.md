# Maintainer release procedure

This checklist does not authorize deployment or announce a new release.
README.md distinguishes public main from the catalog-reviewed pin.

## Candidate and assembly

Confirm `gh api user --jq .login` matches the authorized repository owner and
origin is the intended public repository. Fetch main, inspect status/index and
coordinate writers. Work on main in primary checkouts only; no side branches,
worktrees, force pushes, history rewriting or staging unrelated WIP.

Private development source and the assembled public plugin have distinct
histories and layouts. Do not merge those histories or copy the private tree
wholesale. The established assembly rewrites imports and moves frontend sources
to desktop/source. Before any source refresh, obtain the current assembly
command and a reviewed source-to-package receipt from app-developer; if these
are missing, STOP source promotion. Historical temporary-clone/replacement
recipes do not override the current main-only rule.

Preserve publication exclusions: var/, scratch/, graft/, HANDOFF*, evidence/
and tools/check_live_production_backend.py. Also exclude credentials, private
operational records, caches, bytecode, generated media and committed binaries.
A documentation-only update in the public primary checkout need not rebuild or
import private WIP. Never ship a local-path wheel as a distributable dependency.

app-design owns design and acceptance; app-developer owns application code,
tests and factual as-built records. Obtain applicable design input before code
changes and coordinate exact per-path WIP ownership. Maintenance owns routine
documentation and hygiene, not specialist records.

## Verification

Freeze and record the reviewed committed candidate and source/assembly inputs.
Follow CONTRIBUTING.md and tests/README.md in separately authorized development
environments. Run applicable Python/Node checks, verify archive contents and
record failures, skips and limitations. Require test-running CI at the exact
candidate SHA, not an old successful run or Pages deployment. Missing test
inputs or an assembled-layout failure go to app-developer, not weakened tests.

Validate the candidate with current Hermes plugin and matching upstream catalog
validators without --install-deps in the live environment. Check actual tools,
hooks, disclosures, scoped secrets, bounded dependencies, no self-update, no
bytecode/binaries and truthful requires_hermes. Do not claim compatibility or
host/UI acceptance from validation alone. Real-host qualification is separate;
maintenance never installs/enables the production plugin or automates its UI.

Foresight promotion is HELD until complete, working and tested on BOTH native
Windows and Linux, including required host/UI acceptance and owner completion
signoff. Only an immutable release asset URL plus SHA256 is a distributable pin.
The private local wheel and historical component tests do not satisfy this.

## Publish and read back

Review git diff --check and the explicit staged diff. Push only intended changes
to main after applicable tests pass. Read back the remote branch, exact commit
and published file blobs. Inspect exact-head CI and delegate code failures.
For a qualified release, use a new annotated vVERSION tag at the verified SHA;
never move tags or replace existing release assets. Create the GitHub release
with explicit tag, target SHA and reviewed notes. Upload only inspected assets,
record SHA256 of their bytes, then read back metadata, download and hash them
again before announcing a release. Do not upload private evidence/build logs.

Every NousResearch PR, issue or comment (including catalog SHA bumps) needs the
owner's explicit approval of the exact payload before posting. Prepare a draft;
do not publish through another profile. Catalog updates are separately reviewed
exact-SHA changes, not a side effect of an own-repository push.

## Rollback

Stop promotion of a defective candidate and document an explicit known-good
version. Request a new corrective version from app-developer. Do not rewrite
history, move tags, replace assets, self-update installed plugins or remove
user media/history. Read back any authorized external corrective action.
