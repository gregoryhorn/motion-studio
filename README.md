# Motion Studio

A creation-first media studio for Hermes Desktop.

- **Quick Create:** ask for a sound effect, image, voice line or video in chat. Then play, compare, keep and download the takes in the Motion Studio panel.
- **Production:** collect chosen takes and your own imported files into a project, then export the assets.

Demo: https://youtu.be/xcm4cA7S9dM

## Roadmap: use the apps you already have

Motion Studio's goal is to let users create with the media apps and tools already installed on their own machines, including different Stable Audio setups. The current author-specific sound-effects binding is an initial implementation limitation, not the intended product boundary.

Planned work:

- **Bring your own Stable Audio setup:** let users select their existing compatible wrapper in the panel, review and approve that binding, and pin their selected executable rather than require the author's paths and hashes.
- **Broader installed-app support:** connect additional apps through their supported CLI, API or file-handoff interfaces, reusing Studio's request, run, review and export workflow. Different interfaces may need their own integration; arbitrary installed apps are not automatically compatible today.
- **One workflow across media:** extend usable integrations for Sound effects, Music, Voice, Image and Video, with clear availability and limitations for the user's actual setup.

These are roadmap goals, not shipped capabilities or delivery dates. The requirements and known limits below describe this release. Importing existing media remains available while generation integrations are developed.

## Requirements

- Hermes Agent **0.23.1 or newer**, with Hermes Desktop.
- **Image, voice and video** use Hermes' own `image_gen`, `tts` and `video_gen` tools. Enable the ones you want and configure their provider in Hermes. Paid or unknown-cost methods ask before running.
- **Sound effects generation is unavailable outside the author's existing Stable Audio setup.** Its wrapper, Python runtime and `audio.py` script are pinned to that installation's paths and SHA256 digests; this release cannot configure another user's producer. Imported sound effects can still be reviewed and exported. This package doesn't ship models or install engines.
- **FFmpeg / ffprobe** on `PATH`, used to check imported and generated media.
- Tested on Linux and Windows Hermes Desktop. macOS has not been tested.

## Install

```
hermes plugins install motion-studio
```

Then reload Hermes Desktop. Open a chat in the profile you use for Motion Studio, open the **Motion Studio** panel and click **Connect** if it asks. The panel works with the focused chat.

## How it works

The plugin registers two agent tools, `motion_studio_creation` and `motion_studio_production`, and 45 read-only skills. It registers no hooks. The agent prepares a request and calls the Hermes generator. Motion Studio then collects the result and saves it as a take you can review.

## Security and privacy

- **Method listing** reads generator settings from the active Hermes profile. API-key presence is checked through Hermes' scoped `get_secret()` API; OAuth entries report configuration only. Studio never reads Hermes' `auth.json` or token store.
- **Child processes** (ffmpeg/ffprobe, `nvidia-smi`, local audio engines) get a minimal fixed environment from `studio/child_env.py`, with a small allowlist per adapter. They never inherit provider keys, proxy settings or other credentials.
- **Imports** take uploaded bytes, not file paths. Output collection reads only Hermes' generator output folders. It refuses hidden or secret files (`.env`, `auth.json`, `~/.ssh`, …) and symlinks.
- **Downloads** fetch only from the provider URLs that Hermes' tools return (x.ai, openai.com, oaiusercontent.com, fal.media, fal.run, deepinfra.com, krea.ai). They use same-host redirects only, with no proxies, cookies or credentials.
- **Storage:** projects and takes are stored in the profile's plugin data directory. Generation stays off until a chat is connected.
- **No telemetry.**

Hermes' install-time security scan rates this package *caution*: it runs media tools on file descriptors and includes subprocess and setup helpers. Hermes asks you to confirm before installing.

## Known limits

- Music generation is not available yet.
- Saved takes and projects can't be deleted from the app yet.
- Some legacy craft skills from the earlier editor-first version are not ported yet.

## Development

Run `python3 -m unittest discover -s tests` to run the Python tests. For the Node and browser suites, see `tests/README.md`. Some historical regression tests skip when their baseline archives aren't present.

## License

MIT. See `LICENSE`. Hermes, provider services, optional engines and models keep their own licences and terms.
