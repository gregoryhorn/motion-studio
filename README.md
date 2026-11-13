# Motion Studio

A creation-first media studio for Hermes Desktop.

- **Quick Create:** ask for a sound effect, image, voice line or video in chat. Then play, compare, keep and download the takes in the Motion Studio panel.
- **Production:** collect chosen takes and your own imported files into a project, then export the assets.

Demo: https://youtu.be/xcm4cA7S9dM

## New in 0.2: Director basics

- **Every take is checked.** [Crystal Ball](https://gregoryhorn.github.io/crystal-ball/) 1.2 installs with Motion Studio and checks each take and each export. Images, audio and video each get the checks that apply to them; anything that doesn't apply shows *Not checked* with a reason, never a false FAIL. A PASS is a technical floor, not creative approval.
- **Works with the tools you have.** Motion Studio lists what your Hermes can reach and keeps a *tool card* for each one. For a tool it doesn't know yet, it can run one tiny, disclosed test (cost and wait shown first, you confirm once) and remembers what worked.
- **Remove, Undo and Restore.** Takes can be removed from the list and brought back. Originals and history are never deleted.

## Roadmap

1. **Plan the video:** pick a video type, type one sentence; Motion Studio drafts the script and scene plan, and an independent critic reviews both before anything is generated.
2. **Build it:** make each scene with your own tools, show time and cost first, then assemble one MP4 with captions in vertical, wide or square.
3. **Polish:** guided setup, provider list with copy-paste setup, and a full Windows pass.

These are goals, not shipped features or dates.

## Requirements

- Hermes Agent **0.23.1 or newer**, with Hermes Desktop.
- **Image, voice and video** use Hermes' own `image_gen`, `tts` and `video_gen` tools. Enable the ones you want and configure their provider in Hermes. Paid or unknown-cost methods ask before running.
- **Sound effects generation is unavailable outside the author's existing Stable Audio setup.** Its wrapper, Python runtime and `audio.py` script are pinned to that installation's paths and SHA256 digests; this release cannot configure another user's producer. Imported sound effects can still be reviewed and exported. This package doesn't ship models or install engines.
- **FFmpeg / ffprobe** on `PATH`, used to check imported and generated media.
- **Crystal Ball 1.2** (installed automatically as a pinned dependency). Optional Hear/See engines are offered separately; without them those checks show *Not checked*.
- Tested on Linux and Windows Hermes Desktop. macOS has not been tested.

## Install

```
hermes plugins install motion-studio
```

Then reload Hermes Desktop. Open a chat in the profile you use for Motion Studio, open the **Motion Studio** panel and click **Connect** if it asks. The panel works with the focused chat.

## How it works

The plugin registers three agent tools, `motion_studio_creation`, `motion_studio_production` and `motion_studio_tools`, and 45 read-only skills. It registers no hooks. The agent prepares a request and calls the Hermes generator. Motion Studio then collects the result and saves it as a take you can review.

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
- Removing a take hides it from the list (with Undo/Restore); saved media is never deleted.
- Some legacy craft skills from the earlier editor-first version are not ported yet.

## Development

Run `python3 -m unittest discover -s tests` to run the Python tests. For the Node and browser suites, see `tests/README.md`. Some historical regression tests skip when their baseline archives aren't present.

## License

MIT. See `LICENSE`. Hermes, provider services, optional engines and models keep their own licences and terms.
