# Testing the public source

This clean source release includes a focused, self-contained regression suite.
Historical tests that require private production recordings or operational
evidence, and tests of private deployment helpers, are not included. This is not
a claim that the original project's complete test suite is green.

Use a Hermes-compatible development Python environment with PyYAML, Pillow and
the test-only dependencies in requirements-test.txt, plus Node 22+ for JavaScript
tests. Host-boundary tests require the corresponding Hermes modules. Keep TMPDIR writable.
Do not modify a live Hermes runtime just to create a test environment.

```sh
TMPDIR=/tmp python -m pytest -q tests
node --test tests/*.mjs
python scripts/skill_registration.py --check
python scripts/docs.py reference --check
python scripts/docs.py check
python tools/build_studio_manifest.py --check
```

Catalog submission separately requires the official
`hermes plugins validate /path/to/checkout --install-deps` command at the
exact public commit. Run it in an isolated Hermes validation environment,
because host dependency synchronization may write to that environment.
Read warnings as well as the exit status.

Source checks do not launch production, authorize provider spending or establish
complete installed-client acceptance. The release verification record names
what actually passed and what remains unqualified.

## CI scope

The public source-checks workflow verifies generated references, documentation,
the runtime manifest, and the Kinetic/capture JavaScript contracts. It does not
run a live renderer, install Hermes, perform complete Python integration tests,
or certify installed-client acceptance.
