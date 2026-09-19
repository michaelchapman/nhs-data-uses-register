"""Human-reviewed organisation name aliases, applied at build time.

The register records an organisation's name as free text on every row, and
the same real organisation sometimes appears under more than one spelling —
a shortened ICB name, a trailing "Limited" dropped, a comma moved. Two
organisations with genuinely similar names (two different NHS trusts, two
different councils) are not the same thing, so nothing here is inferred or
merged automatically: an alias exists only because a person looked at it and
added it to `data/organisation-aliases.json`, and the exact list of names an
organisation was recorded under is kept and shown on its page, so a merge is
always checkable against the register rather than hidden.

`python -m pipeline.orgcheck --review` is the guided way to build this file.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ALIASES_PATH = Path(__file__).resolve().parent.parent / "data" / "organisation-aliases.json"


def _key(name: str) -> str:
    """A case/whitespace-insensitive lookup key.

    A reviewer copying a name out of `orgcheck` output should not have their
    entry silently fail to match over a stray space or a capitalisation
    difference that isn't a meaningful difference in the data — so matching
    ignores case and collapses whitespace, rather than requiring the variant
    string to be byte-identical to what's in the register.
    """
    return re.sub(r"\s+", " ", name).strip().casefold()


def _read() -> dict:
    if not ALIASES_PATH.exists():
        return {"aliases": [], "ignored": []}
    data = json.loads(ALIASES_PATH.read_text())
    data.setdefault("aliases", [])
    data.setdefault("ignored", [])
    return data


DEFAULT_COMMENT = (
    "Reviewed by a person, not inferred — see docs/organisation-names.md and "
    "`python -m pipeline.orgcheck --review`. Each alias group: canonical (the "
    "name shown on the organisation page) and variants (every spelling in the "
    "register that should map to it). `ignored` records candidates a reviewer "
    "looked at and decided were not the same organisation, so orgcheck doesn't "
    "keep re-suggesting them — each entry is the sorted list of names in that "
    "candidate."
)


def _write(data: dict) -> None:
    # Key order is cosmetic but stable, so diffs in the committed file stay
    # readable rather than reshuffling every time something is saved.
    ordered = {
        "_comment": data.get("_comment") or DEFAULT_COMMENT,
        "aliases": data.get("aliases", []),
        "ignored": data.get("ignored", []),
    }
    ALIASES_PATH.write_text(json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def load_groups() -> list[dict]:
    return _read()["aliases"]


def load_ignored() -> list[list[str]]:
    return _read()["ignored"]


def load_map() -> dict[str, str]:
    """`{normalised variant key: canonical name}`.

    Look up with `resolve()`, not this dict directly, since its keys are
    normalised rather than exact register text.
    """
    mapping: dict[str, str] = {}
    for group in load_groups():
        canonical = group["canonical"]
        for variant in group.get("variants", []):
            if _key(variant) != _key(canonical):
                mapping[_key(variant)] = canonical
    return mapping


def resolve(name: str, alias_map: dict[str, str]) -> str:
    """The canonical name for `name`, or `name` unchanged if it has no alias."""
    return alias_map.get(_key(name), name)


def is_ignored(names: list[str], ignored: list[list[str]] | None = None) -> bool:
    """Whether this exact candidate (as a set of names) was already dismissed."""
    ignored = load_ignored() if ignored is None else ignored
    key = frozenset(_key(n) for n in names)
    return any(key == frozenset(_key(n) for n in entry) for entry in ignored)


def add_ignored(names: list[str]) -> None:
    data = _read()
    if not is_ignored(names, data["ignored"]):
        data["ignored"].append(sorted(names))
    _write(data)


def add_alias(canonical: str, variants: list[str], reason: str = "") -> None:
    """Add `variants` to the alias group for `canonical`, creating it if new.

    If `canonical` already has a group (matched by its own normalised name,
    so re-running this for the same organisation extends rather than
    duplicates it), the new variants are merged in and the reason is kept
    only if the group didn't already have one.
    """
    data = _read()
    groups = data["aliases"]
    existing = next((g for g in groups if _key(g["canonical"]) == _key(canonical)), None)
    if existing:
        have = {_key(v) for v in existing.get("variants", [])} | {_key(existing["canonical"])}
        for v in variants:
            if _key(v) not in have:
                existing.setdefault("variants", []).append(v)
                have.add(_key(v))
        if reason and not existing.get("reason"):
            existing["reason"] = reason
    else:
        groups.append({"canonical": canonical, "variants": sorted(set(variants)), "reason": reason})
    _write(data)
