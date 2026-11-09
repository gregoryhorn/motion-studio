"""Motion Studio native plugin entry point; registration never starts work."""


def _skill_registrations(root):
    """Validate generated metadata against its authored sources before registration."""
    import hashlib
    import json
    import re

    catalog = json.loads((root / "skills/catalog.json").read_text(encoding="ascii"))
    index = json.loads((root / "skills/registration.json").read_text(encoding="ascii"))
    names = [row["target_name"] for row in catalog["skills"]]
    rows = index["skills"]
    indexed_names = [row["frontmatter"]["name"] for row in rows]
    if (index["schema_version"] != 1 or len(names) != len(set(names))
            or any(not re.fullmatch(r"[a-zA-Z0-9_-]+", name) for name in names)
            or indexed_names != names):
        raise ValueError("Packaged skill registration inventory differs from catalog")
    registrations = []
    paths = set()
    for name, row in zip(names, rows):
        relative = "skills/" + name + "/SKILL.md"
        if row["path"] != relative:
            raise ValueError("Packaged skill path differs from its catalog target")
        path = root / relative
        resolved = path.resolve()
        if not resolved.is_relative_to(root.resolve()) or resolved in paths:
            raise ValueError("Packaged skill path escapes or duplicates another source")
        paths.add(resolved)
        text = path.read_text(encoding="ascii")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError("Packaged skill is missing frontmatter delimiters")
        header = text[4:].split("\n---\n", 1)[0]
        if hashlib.sha256(header.encode("ascii")).hexdigest() != row["frontmatter_sha256"]:
            raise ValueError("Packaged skill frontmatter changed; regenerate skills/registration.json")
        metadata = row["frontmatter"]
        if not isinstance(metadata.get("description"), str) or not metadata["description"]:
            raise ValueError("Packaged skill description must be a nonempty string")
        registrations.append((name, path, metadata))
    return registrations


def register(ctx):
    """Register exact packaged tools and independently authored skill resources."""
    from pathlib import Path
    from .studio.tools import register_tools
    from .studio.host_bridge import register_hooks

    registrations = _skill_registrations(Path(__file__).resolve().parent)
    register_hooks(ctx)
    register_tools(ctx)
    for name, path, metadata in registrations:
        ctx.register_skill(name, path, description=metadata["description"], frontmatter=metadata)
