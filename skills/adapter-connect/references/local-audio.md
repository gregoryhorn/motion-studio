# Existing local music and SFX connections

These are bindings of the shared `LocalAudioConnector` in
`studio/adapters/local_audio.py`, not new model runtimes or services.

| Adapter ID | Existing engine | Native output rate |
| --- | --- | --- |
| `local.ace-step-music` | ACE-Step 1.5 CLI, `acestep-v15-turbo` | 48000 Hz |
| `local.stable-audio-open` | Stable Audio Open CLI | 44100 Hz |

Discovery checks executable, runtime, decoder and selected model-file presence
without loading models. Presence is not proof of successful generation. Use the
current profile's actual `motion_capabilities` results; do not infer another
profile's readiness from a working command in the shell.

## Normal job path

1. Discover `audio.generate@1` and inspect the selected adapter read-only.
2. Import a UTF-8 `.txt` artifact containing the exact structured controls below.
   The `.txt` extension supplies the existing prompt port's `text/plain` MIME;
   its contents are validated JSON. Import with asset kind `json` and retain
   the actual returned artifact pin.
3. Select the adapter through the project's existing bindings document.
4. Compile `audio.generate@1`, with `inputs.prompt` referencing that artifact.
   Parameters are `kind`, `duration_samples`, `sample_rate` and `seed`.
   Music supports whole requested seconds from 1 through 75; SFX supports
   requested durations from 0.1 through 47 seconds. Use the binding's native
   sample rate. Seed may be null or an integer from 0 through 4294967295.
5. Submit through `motion_run`, observe status, then collect using the current
   job revision. Generation runs in the ordinary owned worker; never replace
   this path with direct private-handler calls or invented host receipts.

Music controls:

```json
{"schema":"motion/v1/local-audio-prompt","kind":"music","prompt":"Gentle instrumental piano and warm pads","steps":8,"instrumental":true,"lyrics":""}
```

SFX controls:

```json
{"schema":"motion/v1/local-audio-prompt","kind":"sfx","prompt":"One soft wooden door closing in a quiet room","steps":100,"negative_prompt":"Low quality, distorted, music, speech, voices"}
```

Generated audio is validated and explicitly quantized to PCM16 without trimming
or resampling. Retain measured output duration rather than claiming requested
sample-exact duration, determinism or perceptual approval.

## Feedback and extension

The owned attempt retains engine logs and `generation-receipt.json`, including
binding identity, requested controls, actual engine receipt, exit status, elapsed
time, source/output hashes and measured audio. Progress is currently unsupported;
process-group cancellation is supported, but engine resume is not. Feedback is
project-local, not an external analytics upload.

Noninteractive `--oneshot` CLI turns can deny human approval even when discovery
and compilation succeed. Use an interactive approved host turn to finish
generation; do not change approval policy, inject grants or invoke engines
directly to report the Studio route as verified.

Another compatible audio CLI supplies a trusted `CliAudioBinding` descriptor:
passive dependency paths, exact control schema, timing bounds, argv builder and
real receipt/output extractor. Add it to `BINDINGS`; shared runtime registration,
owned execution and collection do not need another engine-specific branch.
Prompt artifacts cannot supply commands, Python imports or output paths.

Other media operations and Hermes/MCP/API integrations use the existing Adapter
ABI and supported host bridges. This audio connector alone does not implement
all transports or automatically connect arbitrary tools. For unsupported
functionality, follow the support-gap/GitHub procedure in the main adapter-connect
instructions, retaining the actual diagnostics instead of fabricating success.
