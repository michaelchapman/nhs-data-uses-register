"""Find the ODS code for each organisation name in the register.

    python -m pipeline.odscheck            # say what would change
    python -m pipeline.odscheck --apply    # write data/organisation-codes.json

A code is assigned only on evidence, strongest first:

1. the code is in the name ("NHS KENT AND MEDWAY ICB - 91Q"), and ODS knows it;
2. the name is exactly one ODS organisation's current name, or written
   another way ("&" for "and", "NHS Trust" for "NHS Foundation Trust")
   that is exactly one organisation's current name;
3. the name is a CCG's, and on the register it was replaced by a coded name
   whose ODS record was a CCG and is now a sub-ICB location: the same record,
   renamed on 1 July 2022, which ODS no longer holds under its old name.

Anything else needs a person: an entry whose evidence starts "reviewed:" is
kept on every run, and names that look like NHS organisations but match
nothing are listed for review. Then run `python -m pipeline.ods` to refresh
the records the codes point at. See docs/organisation-names.md,
"NHS reorganisations (ODS)".
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict

from . import aliases, exclusions, facts, lineage, ods

CODE_IN_NAME = re.compile(r"\s[-–]\s*([A-Z0-9]*[0-9][A-Z0-9]*)$")
CCG_NAME = re.compile(r"\bCCG\b|CLINICAL COMMISSIONING GROUP", re.IGNORECASE)
NHS_NAME = re.compile(r"\bNHS\b|\bTRUST\b|\bCCG\b|\bICB\b|INTEGRATED CARE BOARD|COMMISSIONING SUPPORT", re.IGNORECASE)


def register_names(register_slug: str) -> tuple[Counter, Counter]:
    """Every organisation name the register has used, and each one-for-one replacement.

    Returns `(names, swaps)`: how many versions use each name, and how many
    times one name replaced another on a version between one stored state and
    the next, as applicant or as the only data controller to change.
    """
    names: Counter[str] = Counter()
    swaps: Counter[tuple[str, str]] = Counter()
    excluded = exclusions.bases()
    for path in facts.agreements_dir(register_slug).glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("base_reference", "").upper() in excluded:
            continue
        for version in record["versions"]:
            states = version["states"]
            used = set()
            for state in states:
                used |= {n for n in [state.get("organisation", "")] + list(state.get("controllers") or []) if n}
            names.update(used)
            for before, after in zip(states, states[1:]):
                pairs = [(before.get("organisation", ""), after.get("organisation", ""))]
                old = {aliases.name_key(n): n for n in before.get("controllers") or []}
                new = {aliases.name_key(n): n for n in after.get("controllers") or []}
                gone, came = set(old) - set(new), set(new) - set(old)
                if len(gone) == 1 and len(came) == 1:
                    pairs.append((old[gone.pop()], new[came.pop()]))
                for was, now in pairs:
                    if was and now and aliases.name_key(was) != aliases.name_key(now):
                        swaps[(was, now)] += 1
    return names, swaps


def earlier_names() -> Counter:
    """Organisation names in the release registers published before July 2021 (see `pipeline.earlier`).

    Most are CCGs that merged before the Data Uses Register began, which ODS
    still holds, as inactive records, under exactly these names. With a code,
    each is followed through ODS to the organisation that took it over.
    """
    from . import earlier

    store = earlier.load(excluded=exclusions.bases())
    names: Counter[str] = Counter()
    for record in (store or {}).get("agreements", {}).values():
        for version in record["versions"]:
            if version.get("organisation"):
                names[version["organisation"]] += 1
    return names


def propose(names, swaps, kept: list[dict], fetch=ods.fetch, search=ods.search, report=print) -> tuple[list[dict], list[str]]:
    """`(entries, for_review)`: a code for every name the evidence supports."""
    entries = {aliases.name_key(e["name"]): e for e in kept}
    records: dict[str, dict | None] = {}

    def record(code):
        if code not in records:
            records[code] = fetch(code)
        return records[code]

    unique: dict[str, str] = {}
    for name in sorted(names, key=lambda n: (n != n.upper(), n)):
        unique.setdefault(aliases.name_key(name), name)

    for count, (key, name) in enumerate(sorted(unique.items()), 1):
        if count % 100 == 0:
            report(f"  {count} of {len(unique)} names")
        if key in entries:
            continue
        match = CODE_IN_NAME.search(name)
        if match and record(match[1]):
            entries[key] = {"name": name, "code": match[1], "evidence": "the code is in the name"}
            continue
        found = exact(name, search)
        evidence = "the name is this organisation's current ODS name"
        if found is None:
            # ODS searches current names only, so a trust that has since
            # become a foundation trust, or a name written with "&" for
            # "and", matches nothing as written. A spelling variant counts
            # only when every variant that matches points at one record.
            matches = {}
            for variant in spelling_variants(name):
                hit = exact(variant, search)
                if hit:
                    matches[hit[0]] = hit
            if len(matches) == 1:
                (found,) = matches.values()
                evidence = f"another spelling of this organisation's current ODS name, {found[1]['name']}"
        if found is None:
            continue
        code, match_ = found
        if CCG_NAME.search(name) and match_["role"] != ods.CCG:
            # Some prescribing and service records carry an old CCG's
            # name. A CCG name belongs to a CCG record or to none.
            continue
        entry = {"name": name, "code": code, "evidence": evidence}
        if match_["role"] == ods.CCG:
            entry["as"] = "CCG"
        entries[key] = entry

    bridge_ccgs(entries, unique, swaps, record)
    for_review = sorted(
        name for key, name in unique.items() if key not in entries and NHS_NAME.search(name)
    )
    return list(entries.values()), for_review


def exact(name: str, search) -> tuple[str, dict] | None:
    """`(code, record)` for the one ODS organisation whose current name is `name`, preferring the one active record."""
    found = {o["code"]: o for o in search(name)}
    if len(found) > 1:
        active = {c: o for c, o in found.items() if o["status"] == "Active"}
        found = active if len(active) == 1 else found
    if len(found) != 1:
        return None
    ((code, record),) = found.items()
    return code, record


def spelling_variants(name: str) -> list[str]:
    """Other ways of writing `name` that ODS may hold: "and" for "&" (and the
    reverse), "NHS Foundation Trust" for "NHS Trust", "Hospitals" for
    "Hospital" (and the reverse), and the name without a closing bracket
    such as "(WHHT)"."""
    bases = {name, re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()}
    out: set[str] = set()
    for base in bases:
        for form in {base, re.sub(r"\s*&\s*", " and ", base), re.sub(r"\s+and\s+", " & ", base, flags=re.IGNORECASE)}:
            out.add(form)
            if re.search(r"\bNHS TRUST$", form, re.IGNORECASE):
                out.add(re.sub(r"\bTRUST$", "Foundation Trust", form, flags=re.IGNORECASE))
            out.add(re.sub(r"\bHOSPITAL\b", "Hospitals", form, flags=re.IGNORECASE))
            out.add(re.sub(r"\bHOSPITALS\b", "Hospital", form, flags=re.IGNORECASE))
    return sorted(v for v in out if v and " ".join(v.split()).casefold() != " ".join(name.split()).casefold())


def bridge_ccgs(entries: dict, unique: dict, swaps, record) -> None:
    """The CCG bridge: ODS kept the record and changed its name, so the code
    comes from the name that replaced it on the register."""
    replaced_by: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for (was, now), count in swaps.items():
        if CCG_NAME.search(was) and CODE_IN_NAME.search(now):
            replaced_by[aliases.name_key(was)][now] += count
    for key, targets in replaced_by.items():
        if key in entries or len(targets) != 1:
            continue
        (now, count), = targets.items()
        match = CODE_IN_NAME.search(now)
        if match is None:  # every name kept above has a code; this is for the type checker
            continue
        code = match[1]
        roles = {r["id"] for r in (record(code) or {}).get("roles", [])}
        if {ods.CCG, ods.SUB_ICB_LOCATION} <= roles:
            entries[key] = {
                "name": unique[key], "code": code, "as": "CCG",
                "evidence": f"replaced by {now} on {count} version{'s' if count != 1 else ''}; "
                            f"ODS records {code} as a CCG that became a sub-ICB location",
            }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write data/organisation-codes.json")
    parser.add_argument("--register", default="data-uses-register", help="register slug to read")
    args = parser.parse_args()

    names, swaps = register_names(args.register)
    names.update(earlier_names())
    kept = [e for e in lineage.load_codes() if e["evidence"].startswith("reviewed:")]
    print(f"{len(names)} names in the register; looking each up in ODS")
    entries, for_review = propose(names, swaps, kept)
    by_evidence = Counter(e["evidence"].split(";")[0] if not e["evidence"].startswith("replaced by") else "CCG bridge"
                          for e in entries)
    print(f"{len(entries)} names with a code:")
    for evidence, count in by_evidence.most_common():
        print(f"  {count:5}  {evidence}")
    if for_review:
        print(f"{len(for_review)} NHS-looking names with no code, for review:")
        for name in for_review:
            print(f"         {name}")
    if args.apply:
        lineage.write_codes(entries)
        print(f"wrote {lineage.CODES_PATH.relative_to(lineage.ROOT)}; now run python -m pipeline.ods")
    else:
        print("nothing written; run with --apply to write it", file=sys.stderr)


if __name__ == "__main__":
    main()
