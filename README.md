# Motion Studio

A native Hermes Agent plugin for editable media projects, visual storyboards,
timeline editing, bounded local rendering, captions, and checked delivery.

**Status: early public preview.** This is a source release, not a claim of
complete product acceptance or catalog approval. The Desktop backend currently
requires a specific verified Hermes host API. Read [compatibility](docs/compatibility.md)
before installing.

## What is included

- Eleven native tools and 67 namespaced workflow skills.
- Durable projects, assessed asset libraries and revisioned visual storyboards.
- Editable HTML/JavaScript scenes and a modular Kinetic engine.
- Owned rendering jobs, explicit cancellation, validated collection and provenance.
- Caption authoring, media finishing and source-package workflows.
- Desktop timeline and composition editing through the Hermes plugin SDK.

Registration does not start a render, download a model or call a paid provider.
Available routes depend on tools installed on the selected host. Capability
discovery is not permission to execute or spend.

## Install

Use a compatible Hermes Agent installation and an explicitly selected profile:

```sh
hermes plugins install gregoryhorn/motion-studio --no-enable
hermes plugins enable motion-studio
hermes plugins show motion-studio
```

For a reproducible install, pass `--ref <full-40-character-commit>` to the install
command. Review the host's scanner warnings. Do not disable the scanner globally.
Use a fresh Hermes session after installation to discover current tool schemas.

The plugin does not install FFmpeg, Chromium, Node, models or media providers.
Local filmmaking requires Node 22+, Chromium, FFmpeg and ffprobe, plus the
qualified route's resource/GPU admission. Other adapters have separate
dependencies. [Usage](docs/hermes.md) explains the normal workflow.

## Documentation

- [Usage and tool overview](docs/hermes.md)
- [Registered tool reference](docs/reference/tools.md)
- [Compatibility and known limitations](docs/compatibility.md)
- [Source tests and verification](docs/testing.md)
- [Security and effects](SECURITY.md)
- [Third-party attribution](THIRD_PARTY_NOTICES.md)

This repository contains a clean public source snapshot. Private operational
reports, local project media, host data, deployment helpers and private Git
history are not included. The complete runtime and refactored engine remain
included. There is no automatic self-updater in this public distribution.

## Licensing

The derived Kinetic engine includes Scenario's MIT licence and attribution.
Bundled fonts retain their SIL Open Font License notices. See
[third-party notices](THIRD_PARTY_NOTICES.md). No repository-wide licence has
been selected for independently authored Motion Studio code.
