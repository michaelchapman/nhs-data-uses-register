"""Where data goes after an agreement that permits sublicensing.

    python -m pipeline.onward    # check the file against the newest edition held

The register records only whether an agreement permits sublicensing, never
what is passed on. For the agreements held by cohorts, trusted research
environments and data services, the holder usually keeps a record of its own,
and data/onward-registers.json says where, collected by hand. Each holder's
entry names its agreements by base reference and lists its records, each of
one of three kinds that must not be run together:

- `sub-licensees`: the organisations the data itself was passed on to;
- `approved uses`: the projects approved to use the data, usually inside the
  holder's own trusted research environment, where it does not leave;
- `publications`: the holder's own list of papers.

Most of these lists cover everything the holder holds, not only what comes
from NHS England, so the page says that not every project or paper on them
used NHS England data. A list of NHS England data only says so with
`nhs_england_only: true`, and the page leaves the caveat out for it.

A holder with no list found has an empty list, and the page says this site
couldn't find one rather than saying nothing. Nothing here says a project or
paper used NHS England data, or that one didn't: these are the holders' lists.

The integrated care boards' sublicensing is a different arrangement: they pass
commissioning data to councils, trusts and other partners in their area, and
NHS England's terms ask them to publish a release register of who. Their
entries carry `commissioning: true`, and the page then speaks of organisations
the data is passed on to rather than projects and papers. An ICB not yet
checked has no entry, and its page shows nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "onward-registers.json"

KINDS = {
    "sub-licensees": "Organisations the data is passed on to",
    "approved uses": "Projects approved to use the data",
    "publications": "Papers the holder lists",
}

# Organisation types whose sublicensing is to providers for commissioning,
# which the file does not cover.
COMMISSIONER_TYPES = ("ICB - Integrated Care Board", "Sub ICB Location")


def load(path: Path | None = None) -> dict:
    path = path or PATH
    if not path.exists():
        return {"checked": "", "aggregators": [], "holders": []}
    return json.loads(path.read_text(encoding="utf-8"))


def by_agreement(config: dict) -> dict[str, dict]:
    """`{base reference: holder}`, upper-cased as the site keys references."""
    out: dict[str, dict] = {}
    for holder in config.get("holders", []):
        for reference in holder["agreements"]:
            out[reference.upper()] = holder
    return out


def by_organisation(config: dict) -> dict[str, list[dict]]:
    """`{organisation page slug: [holder, ...]}`, in the file's order."""
    out: dict[str, list[dict]] = {}
    for holder in config.get("holders", []):
        out.setdefault(holder["organisation"], []).append(holder)
    return out


def caveat(holder: dict) -> bool:
    """Whether any of the holder's lists covers more than NHS England data."""
    return any(not r.get("nhs_england_only") for r in holder["registers"])


def counts(config: dict) -> dict[str, int]:
    """Holders and agreements covered, and how many holders keep each kind of record.

    The research holders and the ICBs are counted apart.
    """
    everyone = config.get("holders", [])
    holders = [h for h in everyone if not h.get("commissioning")]
    icbs = [h for h in everyone if h.get("commissioning")]

    def keeping(kind: str) -> int:
        return sum(1 for h in holders if any(r["kind"] == kind for r in h["registers"]))

    return {
        "holders": len(holders),
        "agreements": sum(len(h["agreements"]) for h in holders),
        "icbs": len(icbs),
        "icb_agreements": sum(len(h["agreements"]) for h in icbs),
        "icbs_found": sum(1 for h in icbs if h["registers"]),
        "icbs_none": sum(1 for h in icbs if not h["registers"]),
        "sub_licensees": keeping("sub-licensees"),
        "approved_uses": keeping("approved uses"),
        "publications": keeping("publications"),
        "none": sum(1 for h in holders if not h["registers"]),
    }


def problems(config: dict, agreements: list[dict], org_slugs: set[str]) -> list[str]:
    """What the file says that the edition does not bear out, and what it misses.

    - a kind the site does not know;
    - a reference named twice, or not in the edition, or whose latest version
      no longer permits sublicensing;
    - an organisation with no page;
    - an agreement outside the ICBs that permits sublicensing and has no entry.
    """
    out = []
    listed = {a["base_reference"].upper(): a for a in agreements}
    seen: set[str] = set()
    for holder in config.get("holders", []):
        name = holder["holder"]
        for register in holder["registers"]:
            if register["kind"] not in KINDS:
                out.append(f"{name}: unknown kind {register['kind']!r}")
        if holder["organisation"] not in org_slugs:
            out.append(f"{name}: no organisation page {holder['organisation']}")
        for reference in holder["agreements"]:
            key = reference.upper()
            if key in seen:
                out.append(f"{name}: {reference} is named more than once")
            seen.add(key)
            agreement = listed.get(key)
            if agreement is None:
                out.append(f"{name}: {reference} is not in this edition")
            elif agreement["sublicensing"] != "Yes":
                out.append(f"{name}: {reference} no longer permits sublicensing")
    for key, agreement in sorted(listed.items()):
        if (
            agreement["sublicensing"] == "Yes"
            and agreement["organisation_type"] not in COMMISSIONER_TYPES
            and key not in seen
        ):
            out.append(f"no entry: {agreement['base_reference']} ({agreement['organisation']}, {agreement['title']})")
    return out


def main() -> None:
    """Check the file against the newest edition held. Run after ingesting."""
    from . import run, sources
    from .model import archive_views
    from .rules import Rules

    rules = Rules.load()
    data, edition, _ = run.from_store(sources.registers()[0], None, rules)
    archive = archive_views(data.get("archived", []), data["organisations"], data["datasets"], rules)
    slugs = {o["slug"] for o in data["organisations"] + archive["organisations"]}
    found = problems(load(), data["agreements"], slugs)
    for problem in found:
        print(problem)
    if not found:
        print(f"{edition}: every agreement in onward-registers.json permits sublicensing and has a page")
    raise SystemExit(1 if found else 0)


if __name__ == "__main__":
    main()
