---
name: production
description: "Manage Motion Studio production briefs, asset plans, references and selected takes."
---

# Production

Handle `Motion Studio - create <kind> for production "<title>", asset <n>
"<intent>": <direction>` and general multi-asset planning requests.
Use `motion_studio_production` for saved briefs, ordered asset plans, references,
and retained take links. Production management availability is separate from
creation generation authority. Do not invent access when a tool reports denial.

## Find and plan

The agent operations are `create`, `list`, `open`, `update_brief`, `add_asset`,
`update_asset`, `add_reference`, `update_reference`, `link_take`, `select_take`.
Use `list` with no extra arguments, then `open` with the exact returned
`production` ID. Reopening never generates. Titles and displayed asset numbers
are labels, not IDs: inspect the saved ordered assets and match kind/intent.
Ask if multiple projects/assets match. Do not duplicate a project on each message.

For a requested new project use `create` with a fresh 32-character lowercase
hexadecimal `command`, `title`, `brief` and optional `kinds` list. Brief fields
are text, `purpose`, `audience`, `usage`; ask only material missing questions.
Kinds are Sound effects, Music, Voice, Image and Video. `kinds` creates ordered
asset slots; inspect them before adding more. A short brief is sufficient.
```json
{"operation":"create","command":"<fresh command>","title":"Launch film","brief":{"text":"Short launch film with opening impact and closing logo"},"kinds":["Sound effects","Image"]}
```
For later mutations send fresh `command`, saved `production`, and `expected`
equal to `current.revision` from the latest open/mutation response.
`update_brief` takes `title` and the complete `brief`.
`add_asset` takes `kind`, `intent`, optional zero-based `position`, `depends_on`
(asset IDs), and `references` (reference IDs). `update_asset` also takes `asset`;
preserve existing fields/lists unless intentionally changing them.
Use declared dependencies to express real user/project relationships, not guesses.

## Create, link and choose

For the panel's asset-directed request, resolve its exact production and asset
first. For Sound effects use `motion_studio_creation`
operations `prepare`, `start`, `status`, `stop` as described by quick-create.
Prepare uses `direction`, optional `seconds`/`seed` (defaults 3.0/42), optional
`parent` for a deliberately new take; start/stop use exact returned
`request`, `revision`, `command`, `run`; status accepts optional `request`.
Do not add production/asset/title fields to the creation tool. Generate one
bounded candidate only under admitted scope; never regenerate on open/reopen.
For Image, Voice and Video use the quick-create built-in flow: save a request
with kind/direction/method_id from methods.list/method hermes_tool, call image_generate/text_to_speech/
video_generate respectively, then motion_studio_creation collect_output with
request, submission, attempt and matching tool name. Prefer the returned local cache
path; otherwise pass the URL/data the tool returned to collect_output using exactly
one of path, url, data. Base64 data is PNG/JPEG images only; HTTPS URLs require provider CDN hosts. Image accepts PNG/JPEG;
Voice accepts WAV; MP3/OGG conversion requires disclosed user OK and conversion_ok=true;
source bytes are retained with derivative lineage; Video accepts MP4. Local paths require profile media-cache roots.
Limits remain 16 MB and 47 seconds for audio/video. Never truncate to fit.
For Music explain MUSIC_LIVE_UNQUALIFIED, save an import-only request with method
hermes_tool and offer WAV import. No Music generation or substitute tool.
Always tell the user to review the collected/imported take in Motion Studio's
Production panel before choosing/exporting. Technical validation is not listening.
After lost creation replies first use status with no ID; never blind-retry.

After the retained take is known, `link_take` needs the common mutation fields
plus `asset`, `request`, `take` (the returned take ID, not run ID). Linking keeps
immutable provenance without copying or generating media. Read the new revision.
`select_take` uses the same payload shape and explicitly chooses the linked
take against the latest revision. Link alone is not selection. Preserve existing
selection until the user intentionally chooses. Do not claim review/listening.

`add_reference` uses common mutation fields plus `request`, `take`, optional
`label`; `update_reference` also needs `reference`. References must already be
accessible retained media. Attach their returned IDs in asset `references`.
Do not scan private files or infer rights to import them.

## Review, export and recovery

Use the Production panel for import, playback/viewers, comparison and export of
selected outputs. Media RPCs exist behind the panel, but are NOT agent tool
operations: `media_import.begin`, `media_import.chunk`, `media_import.status`,
`media_import.commit`, `media_import.cancel`, `media_import.describe`,
`media_import.read_chunk`, `describe`, `export.prepare`, `export.descriptor`,
`export.chunk`, `export.close`. Never pass these to motion_studio_production.
Export retains original selected bytes; it does not generate, convert or prove
editor delivery. If the installed panel lacks the route, report that limitation.

Brief/reference/asset changes preserve old pins and can mark affected selections
and declared dependents out of date. Open current state, review, and explicitly
use current-revision select_take only when the chosen take is still suitable.
Never clear a stale marker by silently selecting, regenerating or replacing media.
After a lost mutation reply, list/open the same project and reconcile the saved
revision and intended change before any intentional next action. Never repeat
mutations automatically, mint replacement commands on uncertainty or bypass scope.

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
