---
name: refine-take
description: "Make a deliberately new Motion Studio take while preserving earlier takes."
---

# Refine a take

Handle `Refine Motion Studio creation <id> as a deliberately new take
(parent=<id>): <change>` or an explicit request to change a saved creation.
Treat this as a new take in the same creation lineage; preserve earlier takes,
reviews and selections. Never overwrite media or silently replace a selection.

Use `motion_studio_creation` operations `status`, `prepare`, `start`, `stop`.
First read `status` with `request` set to the supplied parent ID. Confirm it is
accessible in this chat and use its saved kind/defaults. A parent ID is a
32-character lowercase hexadecimal saved request ID, not a take or run ID.
If the panel's IDs disagree or the target is ambiguous, ask which saved creation
is intended. Never guess identity or switch chats to bypass scope.

For Image, Voice and Video follow quick-create's built-in tool flow: prepare
with saved kind, method hermes_tool, selected method_id, parent ID and revised direction;
use image_generate/text_to_speech/video_generate respectively, then collect_output
with the saved submission and attempt IDs. Prefer the returned local cache path;
otherwise pass the URL/data the tool returned to collect_output using exactly one
of path, url, data. Base64 data is PNG/JPEG images only; URLs require HTTPS provider CDN hosts. Follow the methods.list cost rule below.
Always review in the Motion Studio panel. For Music explain
MUSIC_LIVE_UNQUALIFIED and offer WAV import; never substitute a generator.
The status tool does not return the saved creative direction: use direction
already supplied in the current request/context, or ask for the material missing
description. Do not claim to have heard the take or reconstruct private history.

For Sound effects, prepare a concise complete direction preserving the original intent with the
requested change. Use `parent` equal to the supplied request ID; `prepare`
creates a distinct child request/command rather than appending to the old run:
```json
{"operation":"prepare","parent":"<saved request>","direction":"<original intent with requested change>","seconds":3.0,"seed":42}
```
Use known saved seconds/seed unless the user changes them; otherwise disclose
Sound effects defaults of 3 seconds/seed 42 (one candidate, fixed 100 steps).
Supported bounds are 0.1–10 seconds and seed 0–4294967295.
Start only with the newly returned `request`, `revision`, `command`, `run`, under
admitted scope. Do not reuse the parent's start command or auto-select the new take.
If the service rejects a parent/lineage conflict, explain it; do not drop `parent`
to force a new unrelated creation.

After a lost reply, `status` without an ID recovers the saved intent. Never
blind-retry or create another child to resolve uncertainty. Only an explicit
`preparation_retryable=true` permits deliberate identical preparation recovery;
only `prelaunch_retryable=true` permits a deliberate same-command start after
RESOURCE_BUSY. Running/entered/unknown launches cannot be rearmed. For requested
cancellation use `stop` with exact current request/revision/command/run.

Report the safe status and direct the user to Motion Studio → Quick Create to
review/compare the new and earlier takes and deliberately choose a selection.
Reopen, status and comparison never generate. A new take is not a claim that the
requested improvement succeeded; user review establishes that.

Cost rule: the method's cost class from methods.list decides. For paid or unknown,
state provider and cost basis and get explicit user OK before calling. For free
or subscription, proceed with one bounded candidate and say which method was used.

## Duration in SECONDS

Pass numeric `seconds` explicitly to Studio prepare for timed media.
Sound effects: 0.1–10 seconds, default 3; legacy ACE-Step Music: integer
10–30 seconds, default 30 (live generation remains unqualified). Import-only
Music and Voice: 0.5–47 seconds, defaults 30 and 5 respectively; this is Studio's
retention range, not a TTS provider duration guarantee. Image has no duration.
xAI Video: whole seconds 1–15, default 5; reference-image video max 10.
Pass the same seconds explicitly as `video_generate(duration=5)` (use the actual
requested integer). Never pass milliseconds, fractions below 1, or omit duration.
Hermes `text_to_speech` has NO duration parameter. Pass the timing target explicitly
in instructions (e.g. "Target 5 SECONDS; measured pacing") with the spoken text;
instructions are provider-dependent and may be ignored. Do not invent a duration
argument or promise exact speech length. Preserve the text; resolve infeasible
timing rather than silently cutting it. Collection probes actual bytes and rejects
output below 0.5 seconds or video with zero decoded frames; no take is created.
