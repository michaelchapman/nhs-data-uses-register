"""Group organisations into sectors, for the Sector filter.

The register's organisation type is granular (29 types) and not always what an
organisation is: it files companies alike with universities and charities as
"Research". "Which companies hold agreements?" needs neither, so each
organisation gets one of six sectors. The sector comes from its type through
the mapping in data/organisation-sectors.json, unless the same file corrects
it; a correction names the organisation's page, so it covers every spelling
merged onto that page, and says why.

An organisation's agreements all take its sector, so filtering agreements by
sector and filtering organisations by sector agree.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "data" / "organisation-sectors.json"
NOT_STATED = "Not stated"
# A type the mapping doesn't know yet: a new edition can introduce one.
OTHER = "Other"


def load(path: Path = PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def names(config: dict) -> list[str]:
    """The sectors in the order the filter lists them."""
    return [sector["name"] for sector in config["sectors"]]


def assign(organisations: list[dict], config: dict | None = None) -> list[str]:
    """Set `sector` on each organisation and on each agreement it holds.

    An organisation's sector is its correction if it has one, and otherwise the
    sector most of its agreements' types map to: the register can file one
    organisation under two types ("ICB" and "Sub ICB Location"). A corrected
    organisation also gets `sector_reason`.

    Returns warnings for the build to print: types with no sector, which would
    otherwise show as "Other" without anyone noticing. Corrections that name no
    organisation are `unused_corrections`, checked by running this module.
    """
    config = config or load()
    by_type = {t: sector["name"] for sector in config["sectors"] for t in sector["types"]}
    corrections = {c["organisation"]: c for c in config["corrections"]}
    unmapped: Counter = Counter()

    def sector_of(organisation_type: str) -> str:
        if not organisation_type:
            return NOT_STATED
        if organisation_type not in by_type:
            unmapped[organisation_type] += 1
            return OTHER
        return by_type[organisation_type]

    for organisation in organisations:
        correction = corrections.get(organisation["slug"])
        if correction:
            sector = correction["sector"]
            organisation["sector_reason"] = correction["reason"]
        else:
            types = [a["organisation_type"] for a in organisation["agreements"]] or [organisation["type"]]
            tally = Counter(sector_of(t) for t in types)
            # Most agreements win; a tie goes to the sector listed first.
            order = names(config) + [OTHER, NOT_STATED]
            sector = max(tally, key=lambda s: (tally[s], -order.index(s)))
        organisation["sector"] = sector
        for agreement in organisation["agreements"]:
            agreement["sector"] = sector

    return [
        f'organisation type "{t}" ({n} agreements) has no sector: add it to {PATH.name}'
        for t, n in sorted(unmapped.items())
    ]


def unused_corrections(organisations: list[dict], config: dict | None = None) -> list[str]:
    """Corrections naming no organisation page, as after a page's slug changes."""
    config = config or load()
    slugs = {o["slug"] for o in organisations}
    return [
        f'{PATH.name} corrects "{c["name"]}" ({c["organisation"]}), which no organisation page has'
        for c in config["corrections"]
        if c["organisation"] not in slugs
    ]


def main() -> None:
    """Check the sectors against the newest edition held, and summarise them.

        python -m pipeline.sectors

    Run after ingesting an edition: it lists types with no sector and
    corrections that no longer name an organisation, then the sectors' totals.
    """
    from . import run, sources
    from .extract import archive_views

    data, edition, _ = run.from_store(sources.registers()[0], None)
    archive = archive_views(data.get("archived", []), data["organisations"], data["datasets"])
    organisations = data["organisations"] + archive["organisations"]
    problems = assign(organisations) + unused_corrections(organisations)
    for problem in problems:
        print(problem)
    print(f"{edition}: {len(data['agreements']):,} agreements")
    tally = Counter(a["sector"] for a in data["agreements"])
    held = Counter(o["sector"] for o in data["organisations"] if o["agreements"])
    for name in names(load()) + [OTHER, NOT_STATED]:
        if tally[name]:
            print(f"  {name:38s} {tally[name]:5,} agreements  {held[name]:4,} organisations")
    raise SystemExit(1 if problems else 0)


if __name__ == "__main__":
    main()
