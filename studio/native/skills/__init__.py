"""Read-only, package-owned workflow skills; no user skill installation."""
from pathlib import Path
import hashlib
from ...domain import Fault


SKILLS = {
    'core': 'Use Motion Studio run and asset contracts, truthful receipts and local-model etiquette.',
    'quick-create': 'Create media candidates from natural language and review them in Quick Create.',
    'refine-take': 'Make a deliberately new Motion Studio take while preserving earlier takes.',
    'production': 'Manage Motion Studio production briefs, asset plans, references and selected takes.',
    'troubleshooting': 'Recover Motion Studio panel connections and saved state without generating media.',
    'achievement-story': 'Present a verified milestone with restrained emphasis.',
    'art-direction': 'Define visual hierarchy, palette and material direction.',
    'asset-source': 'Choose and retain source assets for a named creative role.',
    'beat-plan': 'Plan timed narrative beats and readable holds.',
    'brand-discover': 'Extract supported brand facts and critical conflicts.',
    'brand-system': 'Formalize approved identity into reusable creative rules.',
    'brief-author': 'Turn a request into a brief without unnecessary interviews.',
    'chart-story': 'Explain supplied numbers with honest visual encodings.',
    'continuity-guide': 'Keep approved identity and creative continuity coherent.',
    'cut-paper-treatment': 'Direct original layered paper shapes and depth cues.',
    'design-reference': 'Translate still references into actionable design principles.',
    'edit-rhythm': 'Plan purposeful pacing from message and actual cues.',
    'editorial-promo': 'Write a source-faithful hook, context and action.',
    'evidence-explainer': 'Build an original question, evidence and conclusion narrative.',
    'feature-focus': 'Explain one verified input, action and result.',
    'frame-safety': 'Review candidate framing, clipping and overlay risks.',
    'generated-media': 'Direct one authorized media candidate and retain its output.',
    'glass-depth': 'Direct layered glass, depth and readable translucent surfaces.',
    'industrial-treatment': 'Apply requested industrial visual language without false data.',
    'interaction-timing': 'Describe clear interface state changes and readable timing.',
    'interface-art': 'Create truthful interface hierarchy and focal framing.',
    'interface-art-audit': 'Audit existing interface imagery without an unsolicited redesign.',
    'launch-story': 'Build an original launch story from verified product facts.',
    'media-plan': 'Choose useful media roles and acquisition paths.',
    'minimal-treatment': 'Reduce decoration while preserving essential meaning.',
    'motion-language': 'Define purposeful movement and coherent temporal direction.',
    'motion-math': 'Reason about bounded timing, mappings and repeatability.',
    'motion-vocabulary': 'Select a small movement vocabulary for attention tasks.',
    'premium-product-film': 'Direct an original product reveal with truthful detail.',
    'procedural-audio': 'Design a deterministic cue score without inventing an engine.',
    'production-direct': 'Coordinate an asset production without replacing accepted work.',
    'reference-analysis': 'Analyze observed motion principles for an original treatment.',
    'reference-rebuild': 'Reinterpret a supplied layout with truthful replacement content.',
    'revision-review': 'Track observed defects through new takes and evidence.',
    'route-comparison': 'Compare actual candidates on declared criteria and cost evidence.',
    'seamless-loop': 'Plan periodic motion or audio and inspect the join.',
    'sound-cues': 'Direct sound attacks, emphasis and natural decays.',
    'studio-produce': 'Reconcile and coordinate creation-first production work.',
    'visual-critique': 'Critique actual pixels against the brief and treatment.',
    'voice-produce': 'Direct narration and review actual pronunciation and delivery.',
}


def register(ctx):
    """Older hosts may lack the optional content registrar."""
    verify_integrity()
    registrar = getattr(ctx, 'register_skill', None)
    if not callable(registrar):
        return
    root = Path(__file__).resolve().parent
    for name, description in SKILLS.items():
        registrar(name, root / name / 'SKILL.md', description,
                  frontmatter=dict(name=name, description=description))


# Controlled updates review the instruction diff and focused tests, then update this
# release pin in source. Runtime drift never rewrites or accepts this pin.
RELEASE_DIGEST = '041c150d0a5fee9023c1a36da06b7d0d383a604bb4fad4ce212fbb0e4f140a7b'


def instruction_digest(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in sorted(SKILLS):
        data = (root / name / 'SKILL.md').read_bytes()
        digest.update(name.encode() + b'\0' + len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()


def verify_integrity():
    try:
        intact = instruction_digest() == RELEASE_DIGEST
    except OSError:
        intact = False
    if not intact:
        raise Fault('SHIPPED_INSTRUCTION_CHANGED', 409)
