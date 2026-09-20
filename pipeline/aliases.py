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

DATA = Path(__file__).resolve().parent.parent / "data"
ALIASES_PATH = DATA / "organisation-aliases.json"
DATASET_ALIASES_PATH = DATA / "dataset-aliases.json"


def _key(name: str) -> str:
    """A case/whitespace-insensitive lookup key.

    A reviewer copying a name out of `orgcheck` output should not have their
    entry silently fail to match over a stray space or a capitalisation
    difference that isn't a meaningful difference in the data — so matching
    ignores case and collapses whitespace, rather than requiring the variant
    string to be byte-identical to what's in the register.
    """
    return re.sub(r"\s+", " ", name).strip().casefold()


def _read(path: Path = None) -> dict:
    path = path or ALIASES_PATH
    if not path.exists():
        return {"aliases": [], "ignored": []}
    data = json.loads(path.read_text())
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


DATASET_COMMENT = (
    "Dataset name merges, for datasets the register has relabelled — see "
    "docs/organisation-names.md and `python -m pipeline.datasetcheck`. Each "
    "group: canonical (the name shown on the dataset page) and variants "
    "(every spelling that should map to it). An entry marked \"source\": "
    "\"auto\" was added by --auto on unambiguous evidence and nobody reviewed "
    "it. `ignored` records candidates a reviewer decided were different "
    "datasets."
)


def _default_comment(path: Path) -> str:
    return DATASET_COMMENT if path == DATASET_ALIASES_PATH else DEFAULT_COMMENT


def _write(data: dict, path: Path = None) -> None:
    path = path or ALIASES_PATH
    # Key order is cosmetic but stable, so diffs in the committed file stay
    # readable rather than reshuffling every time something is saved.
    ordered = {
        "_comment": data.get("_comment") or _default_comment(path),
        "aliases": data.get("aliases", []),
        "ignored": data.get("ignored", []),
    }
    path.write_text(json.dumps(ordered, indent=2, ensure_ascii=False, sort_keys=False) + "\n")


def load_groups(path: Path = None) -> list[dict]:
    return _read(path)["aliases"]


def load_ignored(path: Path = None) -> list[list[str]]:
    return _read(path)["ignored"]


def load_map(path: Path = None) -> dict[str, str]:
    """`{normalised variant key: canonical name}`.

    Look up with `resolve()`, not this dict directly, since its keys are
    normalised rather than exact register text.
    """
    mapping: dict[str, str] = {}
    for group in load_groups(path):
        canonical = group["canonical"]
        for variant in group.get("variants", []):
            if _key(variant) != _key(canonical):
                mapping[_key(variant)] = canonical
    return mapping


def resolve(name: str, alias_map: dict[str, str]) -> str:
    """The canonical name for `name`, or `name` unchanged if it has no alias."""
    return alias_map.get(_key(name), name)


def is_ignored(names: list[str], ignored: list[list[str]] | None = None, path: Path = None) -> bool:
    """Whether this exact candidate (as a set of names) was already dismissed."""
    ignored = load_ignored(path) if ignored is None else ignored
    key = frozenset(_key(n) for n in names)
    return any(key == frozenset(_key(n) for n in entry) for entry in ignored)


def add_ignored(names: list[str], path: Path = None) -> None:
    data = _read(path)
    if not is_ignored(names, data["ignored"]):
        data["ignored"].append(sorted(names))
    _write(data, path)


def add_alias(
    canonical: str,
    variants: list[str],
    reason: str = "",
    path: Path = None,
    source: str = "",
) -> None:
    """Add `variants` to the alias group for `canonical`, creating it if new.

    If `canonical` already has a group (matched by its own normalised name,
    so re-running this for the same organisation extends rather than
    duplicates it), the new variants are merged in and the reason is kept
    only if the group didn't already have one.
    """
    data = _read(path)
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
        group = {"canonical": canonical, "variants": sorted(set(variants)), "reason": reason}
        if source:
            # Marks an entry nobody looked at, so it can be found, audited or
            # undone as a group later.
            group["source"] = source
        groups.append(group)
    _write(data, path)


# --- Merges safe to make without a person -----------------------------------

# Legal-form suffixes that are written inconsistently and never distinguish two
# organisations from each other.
FORM_SUFFIX = r"(?:LIMITED|LTD|PLC|LLP|LLC|INC|INCORPORATED|CORP|CORPORATION)"
_TRAILING_FORM = re.compile(rf"[\s,.]*\b{FORM_SUFFIX}\.?$", re.IGNORECASE)
_TRAILING_BRACKET = re.compile(r"\s*[\(\[][^()\[\]]*[\)\]]\s*$")


def _bare(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def auto_reason(first: str, second: str) -> str | None:
    """Why these two names may be merged unreviewed, or `None` to ask a person.

    Deliberately narrow. Each rule below describes a way of writing the *same*
    name differently — punctuation, a bracketed acronym, a legal form — and
    none of them can turn one organisation into another. Anything that adds or
    removes a word of substance falls through to a human, because that is
    where "NHS Sussex" and "NHS Surrey and Sussex" live, and merging those
    would attribute one body's data sharing to another.
    """
    a, b = _bare(first), _bare(second)
    if not a or not b:
        return None
    if a == b:
        return "same name, differing only in punctuation, spacing or case"

    # "Adult Psychiatric Morbidity Survey" / "... (APMS)"
    short, long_ = sorted((first, second), key=len)
    stripped = _bare(_TRAILING_BRACKET.sub("", long_))
    if stripped == _bare(short) and stripped:
        bracket = _TRAILING_BRACKET.search(long_)
        return f"same name with {bracket.group().strip()} appended"

    # "NEC Software Solutions" / "NEC Software Solutions UK Limited" differ by
    # a legal form only.
    if _bare(_TRAILING_FORM.sub("", first)) == _bare(_TRAILING_FORM.sub("", second)):
        return "same name, differing only in legal form"

    return None


def auto_merge(
    groups, path: Path = None, source: str = "auto"
) -> list[dict]:
    """Apply every pair that is safe to merge unreviewed.

    Each entry is `(first, second)`, or `(first, second, reason)` to supply
    evidence of your own. The second form is for renames found by comparing
    editions, where a name vanished and another appeared on exactly the same
    agreements: that is direct evidence of one dataset under two labels, and a
    stronger reason than anything the spelling could show.

    Returns what was written, so a caller can print it. These entries are
    added without anyone seeing them, and an unexplained change to a reviewed
    file would be worse than the manual review it saves.
    """
    applied = []
    for group in groups:
        first, second = group[0], group[1]
        reason = group[2] if len(group) > 2 and group[2] else auto_reason(first, second)
        if not reason:
            continue
        # The longer spelling is the canonical one: it is the one carrying the
        # acronym or the legal form, and so the less ambiguous of the two.
        canonical, variant = sorted((first, second), key=len, reverse=True)
        add_alias(canonical, [canonical, variant], reason, path=path, source=source)
        applied.append({"canonical": canonical, "variant": variant, "reason": reason})
    return applied
