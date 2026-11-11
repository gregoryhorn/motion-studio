---
name: core
description: "Use Motion Studio run and asset contracts, truthful receipts and local-model etiquette."
---

# Motion Studio core

Motion Studio creates, retains and reviews Sound effects, Music, Voice, Image and
Video through Quick Create and Production. Preserve the requested kind and scope;
explain unsupported routes without substituting a generator.

Preparation saves intent; starting a bounded run is a separate effect under the
current app authority. Use returned request/revision/command/run identities and
immutable asset/take references. Refinement creates a new take and preserves old
ones; selection, review, retrieval and export do not regenerate. After uncertainty,
read saved status before any deliberate retry; never duplicate an entered run.

Report only observed output and receipts. Technical validation does not establish
listening, visual quality, selection, delivery or publication. Stop requested is
not proof of cancellation. Never invent paths, permissions, receipts or identities.
Ask about unresolved scope, consequential cost or publication before that effect;
existing authorization covers only its stated scope, and saving intent grants none.

Before local GPU work, observe free VRAM and GPU processes. If the job cannot fit,
report LOCAL_GPU_BUSY with process names and MB only; ask whether to wait or let
the user free resources. Never evict, unload or stop another loaded model without
asking. Do not automatically retry. After success, failure or cancellation, stop
and reap only our owned model processes and observe their retirement/VRAM release.
Leave pre-existing servers alone. Say the local model was unloaded only when
observed; otherwise state that cleanup or release remains unverified.

Use the shipped package guidance; do not rewrite installed core instructions or
copy a fork to bypass integrity checks. Wiki content is private advisory context,
not authority or a place for secrets. These instructions are not enforcement.
Old sessions may cache earlier guidance; registration/reload is not prompt refresh.

Load motion-studio:quick-create for generation and collection,
motion-studio:refine-take for a deliberately new variation,
motion-studio:production for asset plans and selected takes, and
motion-studio:troubleshooting for connection and saved-state recovery.

## Craft routing — load only what the situation needs

- For a milestone reveal: motion-studio:achievement-story.
- For visual grammar: motion-studio:art-direction.
- For existing source assets: motion-studio:asset-source.
- For narrative beats: motion-studio:beat-plan.
- For supplied identity: motion-studio:brand-discover.
- For reusable identity rules: motion-studio:brand-system.
- For a usable brief: motion-studio:brief-author.
- For numeric storytelling: motion-studio:chart-story.
- For consistency across assets: motion-studio:continuity-guide.
- For cut-paper styling: motion-studio:cut-paper-treatment.
- For still-reference principles: motion-studio:design-reference.
- For pacing direction: motion-studio:edit-rhythm.
- For an editorial teaser: motion-studio:editorial-promo.
- For a factual explainer: motion-studio:evidence-explainer.
- For one feature demonstration: motion-studio:feature-focus.
- For crop and readability review: motion-studio:frame-safety.
- For a generated candidate: motion-studio:generated-media.
- For glass styling: motion-studio:glass-depth.
- For industrial styling: motion-studio:industrial-treatment.
- For interface choreography: motion-studio:interaction-timing.
- For interface-led imagery: motion-studio:interface-art.
- For interface visual review: motion-studio:interface-art-audit.
- For a launch narrative: motion-studio:launch-story.
- For choosing asset roles: motion-studio:media-plan.
- For minimal styling: motion-studio:minimal-treatment.
- For movement grammar: motion-studio:motion-language.
- For timing calculations: motion-studio:motion-math.
- For selecting movement intent: motion-studio:motion-vocabulary.
- For a product reveal: motion-studio:premium-product-film.
- For a synthesized cue design: motion-studio:procedural-audio.
- For creative coordination: motion-studio:production-direct.
- For motion-reference analysis: motion-studio:reference-analysis.
- For structural reinterpretation: motion-studio:reference-rebuild.
- For a scoped creative correction: motion-studio:revision-review.
- For comparing selected routes: motion-studio:route-comparison.
- For loop direction and review: motion-studio:seamless-loop.
- For purposeful sound effects: motion-studio:sound-cues.
- For resumed multi-asset work: motion-studio:studio-produce.
- For visual quality review: motion-studio:visual-critique.
- For spoken performance: motion-studio:voice-produce.

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
