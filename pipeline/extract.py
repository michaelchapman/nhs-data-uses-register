"""Turn a published register workbook into the site's data model.

The workbook has three related sheets keyed on `Reference Number`:

  Agreements    one row per *version* of a data sharing agreement
  Datasets      one row per dataset named on an agreement version
  DataReleases  one row per file actually released against an agreement version

Reference numbers carry a version suffix (``DARS-NIC-00574-V2H1F-v4.2``). The
published register therefore repeats the same agreement once per renewal, which
is the single biggest reason it is hard to read. We group versions under their
base reference so the site can show one page per agreement with its history.
"""

from __future__ import annotations

import datetime as dt
import io
import re
import unicodedata
from collections import defaultdict

import openpyxl

from . import aliases

VERSION_SUFFIX = re.compile(r"-v([0-9]+(?:\.[0-9]+)?)$", re.IGNORECASE)
MONTH_ABBR = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}


# "Smart" punctuation the register uses inconsistently for the same name —
# ST GEORGE'S vs ST GEORGE’S. NFKD + ascii-encode drops these silently rather
# than folding them to their plain-ASCII equivalent, which used to give the
# same organisation two different slugs (and so two different pages) purely
# because one row used a curly apostrophe and another a straight one.
SMART_PUNCTUATION = str.maketrans("’‘“”–—", "''\"\"--")


def slugify(value: str, max_length: int = 80) -> str:
    value = (value or "").translate(SMART_PUNCTUATION)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:max_length].strip("-") or "unknown"


def clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).replace("\r\n", "\n").strip()
    # The register uses "~" as a bullet marker in free text.
    return re.sub(r"\n{3,}", "\n\n", text)


def parse_date(value) -> str:
    if isinstance(value, (dt.datetime, dt.date)):
        return (value.date() if isinstance(value, dt.datetime) else value).isoformat()
    text = clean(value)
    return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else ""


def parse_release_month(value) -> str:
    """``Jul-19`` -> ``2019-07``. Returns '' if unparseable."""
    text = clean(value)
    match = re.match(r"([A-Za-z]{3})[A-Za-z]*[-/ ](\d{2}|\d{4})$", text)
    if not match:
        return ""
    month = MONTH_ABBR.get(match.group(1).lower())
    if not month:
        return ""
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return f"{year:04d}-{month:02d}"


# Multiple controllers are usually separated by ";" or a newline, but the
# register often uses a plain comma instead — "HULL UNIVERSITY TEACHING
# HOSPITALS NHS TRUST, UNIVERSITY OF YORK" is two joint controllers, not one
# organisation with a comma in its name. Split on those commas too, except one
# inside unclosed parentheses or square brackets, so an abbreviation like
# "HEALTHCARE QUALITY IMPROVEMENT PARTNERSHIP (HQIP), NHS ENGLAND - X26" still
# splits after the ")" rather than inside it, and a name that spells its parts
# out in brackets — "BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE]" — stays
# whole instead of becoming two organisations, one of them called
# "CHRISTCHURCH AND POOLE]".
# Corporate suffixes that follow a comma inside one organisation's name
# rather than starting the next one: "MCKINSEY & COMPANY, INC. UNITED KINGDOM"
# is one company, and splitting it invented an organisation called "INC.".
# Deliberately excludes the ambiguous short ones — "CO" would break "CO
# DURHAM", and AB/AS/SA are as often words or places as company forms.
CORPORATE_SUFFIX = (
    "INC", "INCORPORATED", "LTD", "LIMITED", "LLC", "LLP", "PLC",
    "GMBH", "CORP", "CORPORATION", "PTY", "PTE", "SARL", "SRL", "BV", "NV",
)
# Every guard sits immediately after the comma, before any whitespace is
# consumed: with `,\s*` in front of them the engine simply backtracks `\s*`
# to empty, the lookahead then sees a leading space instead of the word it
# was checking for, and the guard silently passes.
LIST_SEPARATOR = re.compile(
    r"\s*;\s*|\n+|"
    r",(?![^(]*\))(?![^\[]*\])"
    r"(?!\s*(?i:" + "|".join(CORPORATE_SUFFIX) + r")\b)"
    r"\s*"
)


def protected_spans(text: str, known: tuple[str, ...]) -> list[tuple[int, int]]:
    """Where in `text` a known organisation name sits, longest match first.

    Longest first so that "NHS Bedfordshire, Luton and Milton Keynes ICB -
    M1J4Y" wins over a shorter name that happens to be a prefix of it.
    """
    spans: list[tuple[int, int]] = []
    lowered = text.lower()
    for name in known:
        start = lowered.find(name.lower())
        while start != -1:
            end = start + len(name)
            if not any(s <= start < e or s < end <= e for s, e in spans):
                spans.append((start, end))
            start = lowered.find(name.lower(), start + 1)
    return spans


def split_list(value, known: tuple[str, ...] = ()) -> list[str]:
    """Split a list-shaped register field, keeping known names whole.

    Some organisations have a comma in their name — "NHS Bristol, North
    Somerset and South Gloucestershire ICB - 15C", "Cumbria, Northumberland,
    Tyne and Wear NHS Foundation Trust" — and no rule about the text around
    the comma tells those apart from two organisations listed together. What
    does tell them apart is that the register names them in full elsewhere:
    Applicant Organisation holds one organisation per row and is never split,
    so the names appearing there are authoritative. Pass them as `known` and
    the commas inside them stop being separators.
    """
    text = clean(value)
    if not text:
        return []
    spans = protected_spans(text, known) if known else []
    if not spans:
        return [p.strip() for p in LIST_SEPARATOR.split(text) if p.strip()]
    parts, start = [], 0
    for match in LIST_SEPARATOR.finditer(text):
        if any(s <= match.start() < e for s, e in spans):
            continue
        parts.append(text[start : match.start()])
        start = match.end()
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


def known_organisation_names(names) -> tuple[str, ...]:
    """The comma-bearing names to protect, longest first.

    Only names with a comma matter: everything else splits the same either
    way, and checking them all for every controller string would be waste.
    """
    return tuple(sorted({n for n in names if n and "," in n}, key=len, reverse=True))


def resplit_list(items: list[str], known: tuple[str, ...] = ()) -> list[str]:
    """Re-apply `split_list`'s rules to an already-split list.

    For a committed extract written before this file's splitting rules
    changed: its controller lists are split by the *old* rules already, so
    re-joining and re-splitting the whole string isn't needed — splitting
    each existing item again is equivalent and cheaper.
    """
    return [part for item in items for part in split_list(item, known)]


def _read_sheet(workbook, name: str) -> list[dict]:
    if name not in workbook.sheetnames:
        return []
    rows = workbook[name].iter_rows(values_only=True)
    header = [clean(h) for h in next(rows)]
    return [dict(zip(header, row)) for row in rows if any(c is not None for c in row)]


def _base_and_version(reference: str) -> tuple[str, str]:
    match = VERSION_SUFFIX.search(reference)
    if not match:
        return reference, ""
    return reference[: match.start()], match.group(1)


def _version_key(version: str) -> tuple:
    return tuple(int(p) for p in version.split(".")) if version else (0,)


def extract(workbook_bytes: bytes) -> dict:
    """Parse workbook bytes into `{agreements, organisations, datasets, stats}`."""
    workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)

    datasets_by_ref: dict[str, list[dict]] = defaultdict(list)
    for row in _read_sheet(workbook, "Datasets"):
        reference = clean(row.get("Reference Number"))
        datasets_by_ref[reference].append(
            {
                "name": clean(row.get("Dataset")),
                "type_of_data": clean(row.get("Type of Data")),
                "sensitivity": clean(row.get("Sensitive or Non-Sensitive")),
                "frequency": clean(row.get("Frequency")),
                "legal_basis": clean(row.get("Legal Basis for Provision of Data")),
                "confidentiality": clean(row.get("Common Law Duty of Confidentiality")),
            }
        )

    # 100k+ release rows: keep a per-dataset summary rather than every file row.
    releases_by_ref: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in _read_sheet(workbook, "DataReleases"):
        reference = clean(row.get("Reference Number"))
        dataset = clean(row.get("Dataset"))
        month = parse_release_month(row.get("Month File Released"))
        summary = releases_by_ref[reference].setdefault(
            dataset,
            {
                "dataset": dataset,
                "files": 0,
                "first_month": "",
                "last_month": "",
                "opt_outs_applied": clean(row.get("Patient Opt-Outs Applied")),
            },
        )
        summary["files"] += 1
        if month:
            if not summary["first_month"] or month < summary["first_month"]:
                summary["first_month"] = month
            if month > summary["last_month"]:
                summary["last_month"] = month

    agreement_rows = _read_sheet(workbook, "Agreements")
    # Applicant Organisation holds one organisation per row and is never
    # split, so it is the register telling us which names contain a comma.
    # Read them first, then use them to keep those names whole in the
    # controller lists, where the same organisations appear comma-joined.
    known = known_organisation_names(clean(r.get("Applicant Organisation")) for r in agreement_rows)

    versions_by_base: dict[str, list[dict]] = defaultdict(list)
    for row in agreement_rows:
        reference = clean(row.get("Reference Number"))
        if not reference:
            continue
        base, version = _base_and_version(reference)
        datasets = datasets_by_ref.get(reference, [])
        releases = sorted(
            releases_by_ref.get(reference, {}).values(),
            key=lambda r: (-r["files"], r["dataset"]),
        )
        versions_by_base[base].append(
            {
                "reference": reference,
                "version": version,
                "title": clean(row.get("Application Title")),
                "organisation": clean(row.get("Applicant Organisation")),
                "organisation_type": clean(row.get("Applicant Organisation Type")),
                "controllers": split_list(row.get("Data Controller(s)"), known),
                "controller_basis": clean(row.get("Sole/Joint Data Controller")),
                "start_date": parse_date(row.get("DSA Start Date")),
                "end_date": parse_date(row.get("DSA End Date")),
                "sublicensing": clean(row.get("Does Sublicensing Apply")),
                "commercial": clean(row.get("For Commercial Purposes")),
                "objective": clean(row.get("Objective for Processing")),
                "activities": clean(row.get("Processing Activities")),
                "expected_output": clean(row.get("Expected Output")),
                "expected_benefits": clean(row.get("Expected Measurable Benefits")),
                "yielded_benefits": clean(row.get("Yielded Benefits")),
                "datasets": datasets,
                "releases": releases,
                "files_released": sum(r["files"] for r in releases),
            }
        )

    alias_map = aliases.load_map()

    agreements = []
    for base, versions in versions_by_base.items():
        versions.sort(key=lambda v: (_version_key(v["version"]), v["start_date"]))
        latest = versions[-1]
        earliest = versions[0]
        dataset_names = sorted({d["name"] for v in versions for d in v["datasets"] if d["name"]})
        starts = [v["start_date"] for v in versions if v["start_date"]]
        ends = [v["end_date"] for v in versions if v["end_date"]]
        # An unversioned reference (no "-vN" suffix) has exactly one version, which
        # is trivially the first. Otherwise the earliest version we hold is only
        # really "the first" if its own number says so — a backfill that starts
        # partway through an agreement's history has an earliest version that
        # isn't v1, and the page needs to say "before", not "from".
        first_known = earliest["version"] in ("", "1", "1.0")
        legal_bases = sorted({d["legal_basis"] for v in versions for d in v["datasets"] if d["legal_basis"]})
        # `organisation`/`controllers` stay exactly as the register recorded them —
        # what an agreement page shows is always the literal source text. Only the
        # slugs used for grouping and links go through the alias map, so a
        # human-reviewed merge (see aliases.py) changes which page something links
        # to, never what it displays.
        organisation_canonical = aliases.resolve(latest["organisation"], alias_map)
        agreements.append(
            {
                "base_reference": base,
                "slug": slugify(base),
                "title": latest["title"] or base,
                "organisation": latest["organisation"],
                "organisation_slug": slugify(organisation_canonical),
                "organisation_type": latest["organisation_type"],
                "commercial": latest["commercial"],
                "sublicensing": latest["sublicensing"],
                "controller_basis": latest["controller_basis"],
                "controllers": latest["controllers"],
                "controller_slugs": [slugify(aliases.resolve(c, alias_map)) for c in latest["controllers"]],
                "first_start": min(starts) if starts else "",
                "first_start_known": first_known,
                "latest_start": latest["start_date"],
                "latest_end": latest["end_date"],
                "coverage_end": max(ends) if ends else "",
                "dataset_names": dataset_names,
                "dataset_slugs": [slugify(n) for n in dataset_names],
                "legal_bases": legal_bases,
                "files_released": sum(v["files_released"] for v in versions),
                "versions": versions,
                "latest": latest,
            }
        )

    agreements.sort(key=lambda a: (a["organisation"].lower(), a["base_reference"]))
    return {
        "agreements": agreements,
        "organisations": _group_organisations(agreements),
        "datasets": _group_datasets(agreements),
    }


def _group_organisations(agreements: list[dict]) -> list[dict]:
    alias_map = aliases.load_map()
    # The exact text a reviewer wrote as `canonical` in the alias file, keyed
    # by its own slug. Falling back to `aliases.resolve()` per agreement isn't
    # enough on its own: whichever raw name happens to be processed first
    # becomes the display name, which is only the reviewer's chosen spelling
    # by coincidence if the register's own text already matches it.
    canonical_by_slug = {slugify(g["canonical"]): g["canonical"] for g in aliases.load_groups()}

    # Group by the already-canonical `organisation_slug`, not by the raw
    # `organisation` text: a human-reviewed alias means two different strings
    # in the register belong on one page. `known_as` collects every raw
    # spelling actually seen, so the merge is always visible on the page
    # rather than silently applied.
    grouped: dict[str, dict] = {}
    for agreement in agreements:
        raw_name = agreement["organisation"] or "Unnamed organisation"
        slug = agreement["organisation_slug"]
        canonical_name = canonical_by_slug.get(slug) or aliases.resolve(raw_name, alias_map)
        entry = grouped.setdefault(
            slug,
            {
                "name": canonical_name,
                "slug": slug,
                "type": agreement["organisation_type"],
                "agreements": [],
                "controller_agreements": [],
                "known_as": set(),
                # Distinguishes a human-reviewed merge (data/organisation-aliases.json)
                # from two spellings that were never really different — a curly vs
                # straight apostrophe — which slugify() already treats as one
                # organisation without anyone having to review anything.
                "reviewed_merge": slug in canonical_by_slug,
            },
        )
        if raw_name != entry["name"]:
            entry["known_as"].add(raw_name)
        entry["agreements"].append(agreement)

    # An organisation can also appear only as a data controller on someone else's
    # agreement, never as the applicant — this matches controller free text
    # against organisation names by slug, so it's approximate: a controller
    # recorded under a different spelling won't be matched unless that spelling
    # is in the alias file. Track membership by base_reference rather than
    # comparing agreement dicts, which is both faster and correct regardless of
    # dict identity.
    by_slug = {entry["slug"]: entry for entry in grouped.values()}
    seen_refs = {slug: {a["base_reference"] for a in entry["agreements"]} for slug, entry in by_slug.items()}
    for agreement in agreements:
        applicant_slug = agreement["organisation_slug"]
        for controller, controller_slug in zip(agreement["controllers"], agreement["controller_slugs"]):
            if not controller_slug or controller_slug == applicant_slug:
                continue
            entry = by_slug.get(controller_slug)
            if entry is None:
                canonical_controller = canonical_by_slug.get(controller_slug) or aliases.resolve(controller, alias_map)
                entry = {
                    "name": canonical_controller,
                    "slug": controller_slug,
                    "type": "",
                    "agreements": [],
                    "controller_agreements": [],
                    "known_as": set(),
                    "reviewed_merge": controller_slug in canonical_by_slug,
                }
                grouped[controller_slug] = entry
                by_slug[controller_slug] = entry
                seen_refs[controller_slug] = set()
            if controller != entry["name"]:
                entry["known_as"].add(controller)
            if agreement["base_reference"] not in seen_refs[controller_slug]:
                entry["controller_agreements"].append(agreement)
                seen_refs[controller_slug].add(agreement["base_reference"])

    for entry in grouped.values():
        entry["agreement_count"] = len(entry["agreements"])
        entry["controller_agreement_count"] = len(entry["controller_agreements"])
        all_agreements = entry["agreements"] + entry["controller_agreements"]
        entry["files_released"] = sum(a["files_released"] for a in entry["agreements"])
        entry["dataset_names"] = sorted(
            {n for a in all_agreements for n in a["dataset_names"]}
        )
        entry["latest_end"] = max((a["coverage_end"] for a in entry["agreements"]), default="")
        entry["commercial"] = any(a["commercial"] == "Yes" for a in entry["agreements"])
        entry["known_as"] = sorted(entry["known_as"])
    return sorted(grouped.values(), key=lambda o: o["name"].lower())


def _group_datasets(agreements: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for agreement in agreements:
        for name in agreement["dataset_names"]:
            entry = grouped.setdefault(
                name,
                {"name": name, "slug": slugify(name), "agreements": [], "attributes": {}},
            )
            entry["agreements"].append(agreement)
            for version in agreement["versions"]:
                for dataset in version["datasets"]:
                    if dataset["name"] != name:
                        continue
                    for key in ("type_of_data", "sensitivity", "legal_basis", "frequency"):
                        if dataset[key]:
                            # Values differ across agreements only by stray whitespace
                            # more often than they differ in substance.
                            value = re.sub(r"\s+", " ", dataset[key]).strip()
                            entry["attributes"].setdefault(key, set()).add(value)
    for entry in grouped.values():
        entry["agreement_count"] = len(entry["agreements"])
        # Counted by canonical slug, not raw name, so two aliased spellings of
        # the same organisation count once rather than twice.
        entry["organisations"] = sorted({a["organisation_slug"] for a in entry["agreements"]})
        entry["files_released"] = sum(
            r["files"]
            for a in entry["agreements"]
            for v in a["versions"]
            for r in v["releases"]
            if r["dataset"] == entry["name"]
        )
        entry["attributes"] = {k: sorted(v) for k, v in entry["attributes"].items()}
    return sorted(grouped.values(), key=lambda d: (-d["agreement_count"], d["name"].lower()))
