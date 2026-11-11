---
name: brand-system
description: "Formalize approved identity into reusable creative rules."
---

# Brand System

Start from accepted identity facts. Define color roles, typography, spacing, logo clearance and aspect adaptations, distinguishing proposals from approved values. Disclose unavailable fonts rather than silently substituting.
Add movement or audio identity only if requested. Keep one authoritative set of rules in the Production brief, without divergent per-asset copies.
Use representative candidates to inspect glyphs, contrast and clearance where possible. Return rules, source/approval status, fallbacks and affected assets; written rules alone do not prove media compliance.

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
Author: Gregory Horn (Motion Studio project)
License: MIT (see LICENSE)

Cost rule: the method's cost class from methods.list decides. For paid or unknown,
state provider and cost basis and get explicit user OK before calling. For free
or subscription, proceed with one bounded candidate and say which method was used.
