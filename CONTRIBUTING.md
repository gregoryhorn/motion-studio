# Contributing

Keep public interfaces, safety boundaries and documentation consistent.
Do not commit credentials, project media, model caches, host transcripts or
machine-specific operational reports.

Run the checks in [testing](docs/testing.md). Tests exercise their stated scope;
passing unit tests does not establish installed-host or creative acceptance.
Preserve exact identifiers, revisions, output hashes and approval boundaries.
Do not replace an authentication or ownership check merely to remove a warning.

Regenerate native tool help with `python scripts/docs.py reference`.
Refresh the payload manifest after runtime edits with
`python tools/build_studio_manifest.py --write-development`, then run
`python tools/build_studio_manifest.py --check`. The manifest remains an
unqualified development inventory; it does not certify release compatibility.

Public changes should include focused regression tests and a short documentation
update. Preserve bundled third-party copyright and licence notices.

When skill frontmatter changes, regenerate and check the source-hash-bound index
with `python scripts/skill_registration.py` and
`python scripts/skill_registration.py --check`. PyYAML is a development-only
dependency; native registration uses the verified packaged metadata.
