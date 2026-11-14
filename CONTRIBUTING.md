# Contributing

Read README.md for distribution status and limitations, tests/README.md for
fixture prerequisites, and RELEASING.md before publication. Keep changes focused.
Use synthetic fixtures only; never contribute user footage, private evidence,
credentials, generated media, model weights, bytecode or dependency binaries.

Application designs and acceptance plans belong to app-design. Application code,
tests and factual as-built records belong to app-developer, with applicable
app-design input required before implementation. Routine maintenance may update
documentation and repository hygiene, not take over specialist code or records.

Work on main in the primary checkout. Inspect Git status/index and coordinate
writers before editing. Preserve WIP; stage explicit files only. No side
branches, worktrees, history rewriting or force pushes. Preserve third-party
notices, bounded dependencies, scoped secret access and declared capabilities.
Do not implement plugin self-update or read OAuth token stores.

## Checks

Use a dedicated development environment and approved temporary storage; set
TMPDIR, TMP and TEMP there. Do not install dependencies in the live Hermes
environment or install/enable the production plugin during maintenance.

The documented Python suite is `python3 -m unittest discover -s tests` with
`PYTHONDONTWRITEBYTECODE=1`. See tests/README.md for existing Hermes source,
Node dependencies and optional fixture requirements. The public package is an
assembled layout, not the raw private source: missing source-only test inputs
must be reported, not silently replaced or assertions removed. Record exact
candidate, interpreter/dependency versions, failures and skips. Do not treat
historical fixture skips or component results as native host/UI qualification.

Browser fixtures and real host checks are separate acceptance lanes requiring
authorized test hosts. This maintenance role does not perform browser/desktop
automation, generate media or use the production plugin. Delegate test harness
or source defects to app-developer with the applicable design reference.

Before proposing a catalog update, require successful candidate tests and the
current upstream catalog validation/security checks without live dependency
installation. Nous publication requires the owner's exact payload approval.
