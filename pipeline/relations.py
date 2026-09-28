"""Organisations that are related but not the same organisation.

    python -m pipeline.relations    # check every slug in the file has a page

Merging (data/organisation-aliases.json) is for one organisation the register
names in more than one way. Some organisations are distinct but belong
together: companies of one group, a body and the organisation that hosts it, a
school run jointly by two universities, an organisation that merged into
another. data/organisation-relations.json records those, by page slug, and
each page it names links to the others. Nothing here is found automatically:
organisations whose names share a word are more often neighbours than
relations (Birmingham City Council, Birmingham Women's and Children's).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "organisation-relations.json"


def load(path: Path | None = None) -> dict:
    return json.loads((path or PATH).read_text(encoding="utf-8"))


def lines(config: dict) -> dict[str, list[list[tuple[str, str]]]]:
    """`{slug: [line, ...]}`: what each page named in `config` says.

    A line is a list of parts, each `("text", words)` or `("org", slug)`, so
    the page can link each organisation it names by the name its page has.
    """
    out: dict[str, list[list[tuple[str, str]]]] = {}

    def say(slug: str, *parts: tuple[str, str]) -> None:
        out.setdefault(slug, []).append(list(parts))

    def listing(slugs: list[str]) -> list[tuple[str, str]]:
        parts: list[tuple[str, str]] = []
        for i, slug in enumerate(slugs):
            if i:
                parts.append(("text", " and " if i == len(slugs) - 1 else ", "))
            parts.append(("org", slug))
        return parts

    for group in config.get("groups", []):
        for member in group["members"]:
            others = [m for m in group["members"] if m != member]
            say(member, ("text", f"In the {group['name']} group of companies, with "), *listing(others), ("text", "."))
    for hosted in config.get("hosted", []):
        say(hosted["body"], ("text", "Hosted by "), ("org", hosted["host"]), ("text", "."))
        say(hosted["host"], ("text", "Hosts "), ("org", hosted["body"]), ("text", "."))
    for joint in config.get("joint", []):
        say(joint["body"], ("text", "Run jointly by "), *listing(joint["parents"]), ("text", "."))
        for parent in joint["parents"]:
            others = [p for p in joint["parents"] if p != parent]
            say(parent, ("text", "Runs "), ("org", joint["body"]), ("text", " jointly with "), *listing(others), ("text", "."))
    for merged in config.get("merged", []):
        say(merged["from"], ("text", "Merged into "), ("org", merged["into"]), ("text", f" in {merged['year']}."))
        say(merged["into"], ("text", "Formed in part from "), ("org", merged["from"]), ("text", f", which merged into it in {merged['year']}."))
    return out


def unknown(config: dict, slugs: set[str]) -> list[str]:
    """Slugs `config` names that have no organisation page, sorted."""
    named = set(lines(config))
    for parts in lines(config).values():
        named.update(value for kind, value in (p for line in parts for p in line) if kind == "org")
    return sorted(named - slugs)


def main() -> None:
    """Check the file against the newest edition held. Run after ingesting."""
    from . import run, sources
    from .extract import archive_views

    data, edition, _ = run.from_store(sources.registers()[0], None)
    archive = archive_views(data.get("archived", []), data["organisations"], data["datasets"])
    slugs = {o["slug"] for o in data["organisations"] + archive["organisations"]}
    missing = unknown(load(), slugs)
    for slug in missing:
        print(f"no organisation page: {slug}")
    if not missing:
        print(f"{edition}: every organisation in organisation-relations.json has a page")
    raise SystemExit(1 if missing else 0)


if __name__ == "__main__":
    main()
