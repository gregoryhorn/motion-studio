# Focused-chat connection regression

From the repository root, point these variables at existing dependencies (no installs are performed by the harness):

```sh
export HERMES_SOURCE="${HERMES_SOURCE:-$HOME/.hermes/hermes-agent-official}"
export ESBUILD="${ESBUILD:-$HERMES_SOURCE/apps/desktop/node_modules/.bin/esbuild}"
export NATIVE_BUNDLE="$PWD/dist/native/fable-dev.zip"
export NODE_PATH="$HERMES_SOURCE/apps/desktop/node_modules${NODE_PATH:+:$NODE_PATH}"
mkdir -p scratch/connect-fix
export TMPDIR="$PWD/scratch"
python -m tools.build_native_package --esbuild "$ESBUILD" --host-source "$HERMES_SOURCE" --output dist/native/fable-dev.zip
node tests/agent-creation.mjs
node tests/agent-production.mjs
TEST_ROUTE_MODE=remote node tests/agent-creation.mjs
TEST_ROUTE_MODE=remote node tests/agent-production.mjs
CONNECT_EVIDENCE="$PWD/scratch/connect-fix/evidence" node tests/browser-chat-connect.mjs
node tests/browser-agent-creation.mjs
PRODUCTION_EVIDENCE="$PWD/scratch/connect-fix/production-regression" node tests/browser-production-reuse.mjs
```

Keep Chromium's temporary directory short enough for its Unix socket paths. The Connect browser test runs the packaged UI and real admission handlers against a disposable fixture store. It reads back Creation/Production root rows, verifies agent workflow denial before connection, current-focus admission, visible pending/success/error/CTA states, stale acknowledgements, separate Production authority and zero generation. It does not install the package or control Hermes Desktop. Node tests additionally defer route lookup and responses to check disposal, away-and-back invalidation, duplicate clicks, pending-mutation guards and obsolete composer targets. See the root README for Python, compile and structure checks.

## Two-session remote-primary Connect

`node tests/browser-connect-remote.mjs` uses the current `NATIVE_BUNDLE`, existing `ESBUILD`, `PLAYWRIGHT_PACKAGE`, `CHROME_EXECUTABLE`, `HERMES_SOURCE` and `NODE_PATH` (include the host Desktop and existing React dependencies). It bundles the actual host request adapter, focuses session-b after opening admitted session-a, clicks the Connections details button and asserts both persisted roots, the exact second-session/profile envelope, removal of agent workflow denial and zero generation. Results/screenshots are under `var/staging/connect-remote/`; use a repository-local `TMPDIR`.

For read-only regression diagnosis, `CONNECT_DESKTOP_BUNDLE=/absolute/path/to/desktop/plugin.js node tests/browser-connect-remote.mjs` substitutes only that Desktop artifact in the isolated fixture. The installed Linux old bundle fails with no admission RPC and no session-b row; the current source package passes. This option neither installs nor edits the supplied bundle or live store. Build a current package with `python -m tools.build_native_package --esbuild "$ESBUILD" --host-source "$HERMES_SOURCE" --output "$NATIVE_BUNDLE"`, where the output must be under `dist/native/`.

## Portable dependencies and historical fixtures

Python discovery: `python3 -m unittest discover -s tests`. Historical regression
cases explicitly skip when their pinned Git commit or local baseline ZIP under
`dist/native/` is absent (including in a `git archive` copy). With those inputs
present, all original identity, preservation and behavioral assertions still run;
corrupt or mismatched inputs are failures, not skips. Baseline ZIPs are internal
fixtures and are not required for the remaining public tests.

`HERMES_SOURCE` defaults to `$HOME/.hermes/hermes-agent-official`. Python host
fixtures also use that conventional location, so an isolated test HOME may expose
an existing source checkout there with a symlink. `NODE_PATH` must include existing
React, jsdom, esbuild and acorn dependencies. `ESBUILD_PACKAGE` optionally selects
an esbuild JavaScript package; otherwise Node resolves `esbuild`. `ESBUILD` selects
the compiler executable (media review defaults to the host Desktop `.bin/esbuild`).
`BOARD_NODE_MODULES` optionally selects the board fixture's Desktop dependencies;
its default is `$HERMES_SOURCE/apps/desktop/node_modules`.

`PLAYWRIGHT_PACKAGE` optionally selects an existing Playwright package directory;
otherwise the portable browser fixtures resolve `playwright` through Node.
`CHROME_EXECUTABLE` optionally selects an existing Chromium executable; otherwise
Playwright uses its configured browser. No browser download is performed. Keep
`TMPDIR` short and absolute, and inside the repository for guarded store fixtures.
For an archive run, override `HOME`, `HERMES_HOME`, `TMPDIR` and `NATIVE_BUNDLE`
to disposable locations and build the bundle there using the command above.

Developer evidence helpers accept `MOTION_STUDIO_DESIGN`, defaulting to
`$HOME/.hermes/profiles/app-design/workspace/design-documents/motion-studio`.
The existing live/backend helpers accept `MOTION_STUDIO_PROFILE`, defaulting to
`$HOME/.hermes/profiles/motion-studio`; the live reload helper accepts `HERMES_ROOT`
(default `$HOME/.hermes`). These variables only select paths; running discovery
does not invoke those maintenance operations. Windows repair receipts use the
portable `%LOCALAPPDATA%` Desktop path.
