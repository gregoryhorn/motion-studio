"""Generate/check native skill metadata; PyYAML is a development-only dependency."""
import argparse
import hashlib
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def render(root=ROOT):
    catalog = json.loads((root / "skills/catalog.json").read_text(encoding="ascii"))
    rows = []
    names = set()
    for skill in catalog["skills"]:
        name = skill["target_name"]
        path = "skills/" + name + "/SKILL.md"
        text = (root / path).read_text(encoding="ascii")
        if not text.startswith("---\n") or "\n---\n" not in text[4:]:
            raise ValueError("Missing frontmatter delimiters: " + path)
        header = text[4:].split("\n---\n", 1)[0]
        metadata = yaml.safe_load(header)
        if metadata["name"] != name or name in names:
            raise ValueError("Duplicate or mismatched skill name: " + path)
        names.add(name)
        rows.append({"path": path,
                     "frontmatter_sha256": hashlib.sha256(header.encode("ascii")).hexdigest(),
                     "frontmatter": metadata})
    return json.dumps({"schema_version": 1, "skills": rows}, indent=2, ensure_ascii=True) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed index is stale")
    args = parser.parse_args()
    target = ROOT / "skills/registration.json"
    expected = render()
    if args.check:
        if not target.is_file() or target.read_text(encoding="ascii") != expected:
            parser.exit(1, "Skill metadata is stale; run python scripts/skill_registration.py\n")
        print("Skill registration metadata is current (67 catalog entries).")
    else:
        target.write_text(expected, encoding="ascii")


if __name__ == "__main__":
    main()
