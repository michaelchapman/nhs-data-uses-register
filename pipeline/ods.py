"""NHS organisation records from the Organisation Data Service (ODS).

    python -m pipeline.ods              # refresh data/ods/organisations.json

ODS is NHS England's reference for NHS organisation codes, names, roles and how
organisations succeed one another. This module is the only part of the pipeline
that asks it anything. It reads the ORD API, which answers without a key, and
writes a committed snapshot that the build reads instead, so the site never
depends on ODS being reachable and a refresh shows up as a reviewable diff.

The snapshot holds the codes named in `data/organisation-codes.json`, and every
code their successor, predecessor and ICB links reach, trimmed to what the site
uses. See docs/organisation-names.md, "NHS reorganisations (ODS)".
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = ROOT / "data" / "ods" / "organisations.json"
API = "https://directory.spineservices.nhs.uk/ORD/2-0-0/organisations"
SOURCE = {
    "name": "NHS Organisation Data Service (ODS)",
    "publisher": "NHS England",
    "url": "https://digital.nhs.uk/services/organisation-data-service",
    "licence": "Open Government Licence v3.0",
    "licence_url": "https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/",
}

# The ODS roles the site reasons about.
CCG = "RO98"
SUB_ICB_LOCATION = "RO319"
ICB = "RO261"
# "Is located in the geography of": how a sub-ICB location names its ICB.
IN_GEOGRAPHY_OF = "RE5"

# How far successor and predecessor links are followed from a code the
# register uses. Real chains are short: a 2013 CCG, merged in 2020, became a
# sub-ICB location in 2022.
MAX_DEPTH = 4


def _get(url: str, attempts: int = 4) -> dict | None:
    """The JSON at `url`, or None for a code ODS does not know."""
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            if attempt == attempts - 1:
                raise
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == attempts - 1:
                raise
        time.sleep(2 ** attempt)
    return None


def _dates(dates: list[dict]) -> dict:
    """Start and end of a date list, preferring the legal dates to the operational ones."""
    by_type = {d.get("Type"): d for d in dates or []}
    chosen = by_type.get("Legal") or by_type.get("Operational") or {}
    return {"start": chosen.get("Start", ""), "end": chosen.get("End", "")}


def trim(record: dict) -> dict:
    """What the site keeps of one ORD record."""
    organisation = record["Organisation"]
    roles = [
        {"id": role["id"], "primary": bool(role.get("primaryRole")), **_dates(role.get("Date"))}
        for role in organisation.get("Roles", {}).get("Role", [])
    ]
    in_icb = [
        rel["Target"]["OrgId"]["extension"]
        for rel in organisation.get("Rels", {}).get("Rel", [])
        if rel.get("id") == IN_GEOGRAPHY_OF
        and rel["Target"]["PrimaryRoleId"]["id"] == ICB
        and rel.get("Status") == "Active"
    ]
    links = [
        {
            "type": succ["Type"].lower(),
            "code": succ["Target"]["OrgId"]["extension"],
            "date": _dates(succ.get("Date"))["start"],
        }
        for succ in (organisation.get("Succs") or {}).get("Succ", [])
    ]
    return {
        "name": organisation["Name"],
        "status": organisation.get("Status", ""),
        **_dates(organisation.get("Date")),
        "roles": sorted(roles, key=lambda r: (not r["primary"], r["id"])),
        "icb": in_icb[0] if in_icb else "",
        "successors": sorted((l for l in links if l["type"] == "successor"), key=lambda l: l["code"]),
        "predecessors": sorted((l for l in links if l["type"] == "predecessor"), key=lambda l: l["code"]),
    }


def fetch(code: str) -> dict | None:
    """One organisation, trimmed, or None if ODS has no such code."""
    record = _get(f"{API}/{urllib.parse.quote(code)}")
    return trim(record) if record else None


def search(name: str) -> list[dict]:
    """Organisations whose current ODS name is exactly `name`, ignoring case and spacing.

    ODS searches by substring and returns sites and departments alongside
    organisations; only organisation records (class RC1) with the exact name
    are kept.
    """
    wanted = " ".join(name.split()).casefold()
    try:
        found = _get(f"{API}?Name={urllib.parse.quote(' '.join(name.split()))}&Limit=100") or {}
    except urllib.error.HTTPError as error:
        # ODS refuses some characters in a search ("Not Acceptable"). A name it
        # cannot search for is a name with no match.
        if 400 <= error.code < 500:
            return []
        raise
    return [
        {"code": o["OrgId"], "name": o["Name"], "status": o.get("Status", ""), "role": o.get("PrimaryRoleId", "")}
        for o in found.get("Organisations", [])
        if o.get("OrgRecordClass") == "RC1" and " ".join(o["Name"].split()).casefold() == wanted
    ]


def load_snapshot(path: Path | None = None) -> dict:
    path = path or SNAPSHOT_PATH
    if not path.exists():
        return {"source": SOURCE, "fetched": "", "organisations": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_snapshot(organisations: dict[str, dict], path: Path | None = None) -> None:
    path = path or SNAPSHOT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "source": SOURCE,
        "fetched": dt.date.today().isoformat(),
        "organisations": dict(sorted(organisations.items())),
    }
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def gather(codes, fetcher=fetch, depth: int = MAX_DEPTH) -> dict[str, dict]:
    """`codes` and every code their links reach within `depth` steps, fetched once each."""
    held: dict[str, dict] = {}
    frontier = sorted(set(codes))
    for _ in range(depth + 1):
        following = set()
        for code in frontier:
            if code in held:
                continue
            record = fetcher(code)
            if record is None:
                continue
            held[code] = record
            following |= {l["code"] for l in record["successors"] + record["predecessors"]}
            if record["icb"]:
                following.add(record["icb"])
        frontier = sorted(following - set(held))
        if not frontier:
            break
    return held


def main() -> None:
    from . import lineage

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.parse_args()
    codes = {entry["code"] for entry in lineage.load_codes()}
    print(f"fetching {len(codes)} codes and their links from ODS")
    organisations = gather(codes)
    write_snapshot(organisations)
    print(f"wrote {len(organisations)} organisations to {SNAPSHOT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
