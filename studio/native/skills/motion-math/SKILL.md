---
name: motion-math
description: "Reason about bounded timing, mappings and repeatability."
---

# Motion Math

State units, exact rate, endpoint inclusion and clamp/wrap/extrapolation behavior. Expose a zero-width domain rather than silently divide by zero.
For linear mapping use output_min + (value - input_min) * output_range / input_range. Check endpoints, an interior value and out-of-range behavior. Separate mathematical easing from descriptive mood.
Keep any supplied seed and stable identity explicit, while disclosing that a generative model may not reproduce identical samples. Return calculations and assumptions; spacing arithmetic alone does not prove visual glyph clearance.

## App workflow

Use motion-studio:core for shared authority and GPU etiquette,
motion-studio:quick-create for one candidate and output collection,
motion-studio:refine-take for a new variation, and motion-studio:production
for saved briefs, asset plans, references and take links.
Only use their advertised operations and current returned identities/revisions.
Save requested direction through motion_studio_creation prepare; for Hermes
Image/Voice/Video use image_generate/text_to_speech/video_generate respectively,
then motion_studio_creation collect_output: prefer its returned local cache path;
otherwise pass the URL/data the tool returned to collect_output (url/data fields).
Use exactly one of path, url, data; data is base64 PNG/JPEG for images only.
HTTPS URLs must use an accepted provider CDN; existing import limits apply.
Music is import-only until qualified. Do not generate just to load this guidance.
Creative notes without a matching saved field remain proposals in the response;
never invent a persistence operation or claim unsupported editing was performed.
Inspect existing output in the panel, report actual coverage, and preserve originals.

## Source notices

Adapted from the existing Motion Studio skill role for the creation-first app.
Author: Hermes Agent (independent B14 authorship)
License: MIT (see LICENSE)

Cost rule: the method's cost class from methods.list decides. For paid or unknown,
state provider and cost basis and get explicit user OK before calling. For free
or subscription, proceed with one bounded candidate and say which method was used.
