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

`python -m pipeline.orgcheck` finds candidates worth reviewing.
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


def load_groups() -> list[dict]:
    if not ALIASES_PATH.exists():
        return []
    return json.loads(ALIASES_PATH.read_text()).get("aliases", [])


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
