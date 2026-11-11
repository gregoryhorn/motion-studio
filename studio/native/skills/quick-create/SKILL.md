---
name: quick-create
description: "Create media candidates from natural language and review them in Quick Create."
---

# Quick Create

Handle `Motion Studio - create <kind>: <request>` from the panel or a plain
request such as “make me a short metallic door slam with a long echo”.
Infer the media kind and turn the request into a concise creative direction.
Ask only when a missing or contradictory choice materially changes the result.
Do not require a form, tool settings, file paths or repeated confirmation within
an already admitted generation scope.

Sound effects uses the local producer below. Image, Voice and Video use Hermes's
built-in tools; Motion Studio saves the request and collects the result for review.
Music generation remains MUSIC_LIVE_UNQUALIFIED; explain this and offer WAV import.
Never silently reinterpret a kind or substitute a generator.

## Image, Voice, Video and Music

First call motion_studio_creation prepare with kind, direction, selected method_id
from methods.list (import for Music), and method hermes_tool.
This saves intent only, with no producer run. For deliberately new work after an
existing request, use its returned request ID as parent, preserving earlier takes.
```json
{"operation":"prepare","kind":"Image","method":"hermes_tool","method_id":"openai-codex","direction":"A blue paper bird on a cream background"}
```
Then use the matching built-in tool with the user's creative direction:
- Image: image_generate (the profile's openai-codex provider). Prefer its returned
  local PNG/JPEG cache path; otherwise collect the returned URL or base64 data.
- Voice: text_to_speech with the requested spoken text and voice direction. Collect
  its returned file_path, one file at a time. PCM16 WAV is accepted directly;
  MP3/OGG requires disclosed user OK and conversion_ok=true, then installed FFmpeg converts it to mono 44.1 kHz PCM16 WAV. The source
  is preserved. If the converter is unavailable, explain and offer WAV import.
- Video: video_generate; collect its returned local MP4 path or HTTPS provider URL.
- Music: prepare kind Music with method hermes_tool to save import-only intent.
  Explain the local ACE-Step engine is not qualified yet; offer the panel's WAV
  import. There is no built-in qualified Music generator or Music collect tool.

After successful image/voice/video output, call collect_output with the exact
saved request, submission and attempt IDs and matching tool name. Prefer the returned
local cache path; otherwise pass the URL/data the tool returned to collect_output.
Use exactly one of path, url, data (base64 PNG/JPEG images only):
```json
{"operation":"collect_output","request":"<returned request>","submission":"<returned submission>","attempt":"<returned attempt>","path":"<returned local output path>","tool":"image_generate"}
```
For a returned URL replace path with url; for base64 images replace path with data.
HTTPS provider domains: x.ai, oaiusercontent.com, openai.com, fal.media, fal.run,
deepinfra.com, krea.ai and their subdomains. Other hosts, IPs, credentials and
redirects to another host are refused. Local path collection accepts only
profile HERMES_HOME cache/generated/images, cache/images, image_cache (Image),
cache/audio or audio_cache (Voice), and cache/generated/videos, cache/videos,
video_cache (Video). Symlinks, secret files and arbitrary paths are refused.
Current import limits apply: 16 MB, images up to 4096×4096, WAV/MP4 up to 47 seconds;
MP4 must use H.264/MPEG4 video and supported optional AAC audio. Do not silently
resize, truncate or regenerate rejected output. Explain the returned limitation.
Collection reuses a take for identical bytes in the same request. After a lost
reply inspect status and reuse its submission/attempt: collect the same output, never regenerate.
Status records not_started, awaiting_output, collected or abandoned; a new parent intent
abandons an awaiting submission without claiming the external tool was cancelled.
Always tell the user to review in the Motion Studio panel → Quick Create →
Open saved creations, then choose/export there. Do not claim perceptual QA,
selection or successful delivery from technical validation alone.

## One bounded candidate

Use `motion_studio_creation`. The local producer operations are `prepare`, `start`,
`status`, `stop`; built-in output collection uses `collect_output`. Omit kind/schema_version for Sound effects. Prepare accepts
`direction` (1–2000 characters), `seconds` (0.1–10, default 3.0), `seed`
(integer 0–4294967295, default 42), and optional `parent` (saved request ID).
Reuse the fixed method: 100 steps, one local candidate. Mention consequential
inferred defaults briefly; honor supplied duration/seed within those bounds.
If the requested duration exceeds the route, explain and resolve that choice.

Example tool arguments for an already requested sound:
```json
{"operation":"prepare","direction":"Metallic door slam with a long echo","seconds":3.0,"seed":42}
```
Preparation saves the intent; it does not generate. Read the returned safe state
and effect review. Under admitted scope, start only the exact returned
`request`, `revision`, `command`, `run`:
```json
{"operation":"start","request":"<returned request>","revision":1,"command":"<returned command>","run":"<returned run>"}
```
Use the returned revision, not the illustrative 1. IDs are opaque 32-character
lowercase hexadecimal strings. Never invent IDs, permissions, host receipts,
paths, approval arguments, profile/session identity or provider options.
If access/effect review is required, explain the returned next step; do not
claim that preparing, loading this skill or opening the panel grants access.

## Observe and recover

Read `status` with `request` to observe saved work. After ANY lost reply, first
use `{"operation":"status"}` without an ID to reconcile the same saved intent.
Never blind-retry. Only `preparation_retryable=true` permits deliberately
repeating the IDENTICAL prepare for the saved no-effect preparation.
After RESOURCE_BUSY observe status; only `prelaunch_retryable=true` permits a
deliberate same-command start. Unknown, running or entered launches cannot be
rearmed. Do not start another candidate as recovery.
For a requested stop, use `stop` with the exact current request/revision/command/run;
report the returned state, since stop requested is not proof of cancellation.

Tell the user the safe result/status and ask them to review in the Motion Studio
panel → Quick Create → Open saved creations. Use returned request identity if
needed to find the result. Do not fabricate a deep link, listening, quality,
selection or successful delivery. Reopening, playback and retrieval never generate.

Before local GPU work observe free VRAM and process names/MB. On LOCAL_GPU_BUSY,
ask whether to wait or let the user free the GPU; never auto-retry or unload,
evict or stop another loaded model without asking. After success, failure or
cancel, terminate/reap only our owned model processes, observe their GPU release
and say when the local model was unloaded. Leave pre-existing servers alone;
if release is unverified, report that instead of claiming unload.

Cost rule: the method's cost class from methods.list decides. For paid or unknown,
state provider and cost basis and get explicit user OK before calling. For free
or subscription, proceed with one bounded candidate and say which method was used.

Duration in SECONDS: Pass numeric `seconds` explicitly to Studio prepare for timed media. Sound effects: 0.1–10 seconds, default 3; legacy ACE-Step Music: integer 10–30 seconds, default 30 (live generation remains unqualified). Import-only Music and Voice: 0.5–47 seconds, defaults 30 and 5 respectively; this is Studio's retention range, not a TTS provider duration guarantee. Image has no duration. xAI Video: whole seconds 1–15, default 5; reference-image video max 10. Pass the same seconds explicitly as `video_generate(duration=5)` (use the actual requested integer). Never pass milliseconds, fractions below 1, or omit duration. Hermes `text_to_speech` has NO duration parameter. Pass the timing target explicitly in instructions (e.g. "Target 5 SECONDS; measured pacing") with the spoken text; instructions are provider-dependent and may be ignored. Do not invent a duration argument or promise exact speech length. Preserve the text; resolve infeasible timing rather than silently cutting it. Collection probes actual bytes and rejects output below 0.5 seconds or video with zero decoded frames; no take is created.
