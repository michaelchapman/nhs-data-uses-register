"""NHS Digital's release registers, published before the Data Uses Register.

Before July 2021, NHS Digital published a *release register*: quarterly from
2014, then monthly from January 2019. Its data model is not the Data Uses
Register's. Each row is a release of data in the period (one row per file, or
one per dataset for system access and frequent flows), keyed on the agreement's
reference and version. From April 2016 a second sheet gives each agreement's
purpose text; from May 2018 that includes the benefits it reported. There are no
titles, no agreement start or end dates and no controllers, and an agreement
appears only in periods when data was released to it. So these files are kept
apart from the monthly editions, and the site shows them as what they are: an
earlier register's record of releases, not more editions.

    python -m pipeline.earlier ingest data/raw/earlier/   # parse every file listed
    python -m pipeline.earlier verify data/raw/earlier/   # check the files, writing nothing

The files are listed, with the period each covers, in
`data/earlier-registers.json`. The set is closed: no more will be published.
The workbooks themselves are never committed (they live in `data/raw/`, which
is gitignored); what they say is written to `data/facts/earlier-registers/`,
one file per agreement, and the site reads only that.

The files from 2014 to June 2015 carry no agreement references, only the
organisation and the dataset, so they are listed with a reason and skipped.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

import openpyxl

from . import aliases, sources
from .records import clean, clean_line
from .references import slugify, version_key

ROOT = Path(__file__).resolve().parent.parent
FILES = ROOT / "data" / "earlier-registers.json"
STORE = ROOT / "data" / "facts" / "earlier-registers"

# NIC-123456-ABCDE, with or without the DARS- prefix NHS Digital added in 2016,
# and with a version suffix from then on. One cell can hold more than one.
REFERENCE = re.compile(r"\b(?:DARS-)?(NIC-\d+-[A-Z0-9]{5})(?:-v\s?(\d+(?:\.\d+)?))?", re.IGNORECASE)

TEXT_FIELDS = ("objective", "activities", "expected_output", "expected_benefits", "yielded_benefits")


class EarlierError(ValueError):
    pass


def listed_files(path: Path | None = None) -> list[dict]:
    """The files `data/earlier-registers.json` lists, oldest first."""
    rows = json.loads((path or FILES).read_text(encoding="utf-8"))["files"]
    return sorted(rows, key=lambda r: r["period_start"])


def references(text) -> list[tuple[str, str]]:
    """`[(base reference, version)]` in a cell, with the DARS- prefix every later register uses."""
    found = []
    for match in REFERENCE.finditer(clean_line(text)):
        found.append((f"DARS-{match.group(1).upper()}", match.group(2) or ""))
    return found


def _normal(header) -> str:
    return " ".join(clean(header).lower().split())


def _header_row(rows: list[tuple]) -> int | None:
    for n, row in enumerate(rows[:10]):
        names = [_normal(c) for c in row]
        if any(name in ("nic number", "reference number") for name in names):
            return n
    return None


def _columns(header: list[str]) -> dict[str, int]:
    """Where each field is, by header. The headers drift between files, so each is matched loosely."""
    wanted = {
        "reference": lambda h: h in ("nic number", "reference number"),
        "organisation": lambda h: h in ("organisation name", "organisation"),
        "dataset": lambda h: h.startswith("type of data provided"),
        "form": lambda h: h.startswith("data provided to customer"),
        "sensitivity": lambda h: h.startswith("sensitive or non"),
        "legal_basis": lambda h: h.startswith("legal basis"),
        "purpose": lambda h: h == "purpose",
        "frequency": lambda h: h == "frequency" or h.startswith("one off"),
        "objective": lambda h: h.startswith("objective for processing"),
        "activities": lambda h: h.startswith("processing activities"),
        "expected_output": lambda h: h.startswith("expected output"),
        "expected_benefits": lambda h: h.startswith("expected measurable benefits"),
        "yielded_benefits": lambda h: h.startswith("yielded benefits"),
        "organisation_type": lambda h: h.startswith("organisation type"),
    }
    found: dict[str, int] = {}
    for n, h in enumerate(header):
        for key, test in wanted.items():
            if key not in found and test(h):
                found[key] = n
    # The September to November 2017 file lost the third header to a stray
    # edit ("us"); the column is still the dataset, as in every other file.
    if "dataset" not in found and found.get("organisation") == 1 and len(header) > 2:
        found["dataset"] = 2
    return found


def _kind(sheet_name: str) -> str:
    name = sheet_name.strip().lower()
    if name.startswith("datareleases") or name == "disseminations":
        return "releases"
    if name in ("purposestatements", "purposes"):
        return "purposes"
    return ""


def read_workbook(workbook_bytes: bytes) -> dict[tuple[str, str], dict]:
    """`{(base, version): {organisation, organisation_type, texts, releases}}` for one file."""
    workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)
    found: dict[tuple[str, str], dict] = {}

    def entry(key):
        return found.setdefault(key, {"organisation": "", "organisation_type": "", "texts": {}, "releases": {}})

    kinds = {_kind(name) for name in workbook.sheetnames}
    if "releases" not in kinds:
        raise EarlierError(f"no release sheet among {workbook.sheetnames}")
    for name in workbook.sheetnames:
        kind = _kind(name)
        if not kind:
            continue
        rows = list(workbook[name].iter_rows(values_only=True))
        start = _header_row(rows)
        if start is None:
            raise EarlierError(f"sheet {name!r} has no reference column")
        columns = _columns([_normal(c) for c in rows[start]])

        def cell(row, key, columns=columns):
            n = columns.get(key)
            return row[n] if n is not None and n < len(row) else None

        for row in rows[start + 1:]:
            for key in references(cell(row, "reference")):
                item = entry(key)
                organisation = clean_line(cell(row, "organisation"))
                if organisation and (kind == "releases" or not item["organisation"]):
                    item["organisation"] = organisation
                if kind == "purposes":
                    item["organisation_type"] = clean_line(cell(row, "organisation_type")) or item["organisation_type"]
                    for field in TEXT_FIELDS:
                        text = clean(cell(row, field))
                        if text:
                            item["texts"][field] = text
                    continue
                # Until April 2016 the purpose was a column of the release sheet.
                purpose = clean(cell(row, "purpose"))
                if purpose and "objective" not in item["texts"]:
                    item["texts"]["objective"] = purpose
                release = (
                    clean_line(cell(row, "dataset")),
                    clean_line(cell(row, "form")),
                    clean_line(cell(row, "sensitivity")),
                    clean_line(cell(row, "legal_basis")),
                    clean_line(cell(row, "frequency")),
                )
                item["releases"][release] = item["releases"].get(release, 0) + 1
    return found


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _workbooks(folder: Path, files: list[dict]) -> list[tuple[dict, bytes]]:
    """The listed files found in `folder`, each checked against its recorded SHA-256."""
    out, problems = [], []
    for row in files:
        path = folder / row["file"]
        if not path.exists():
            problems.append(f"MISSING {row['file']}")
            continue
        data = path.read_bytes()
        if _sha256(data) != row["sha256"]:
            problems.append(f"BAD     {row['file']}: not the file recorded in {FILES.name}")
            continue
        out.append((row, data))
    if problems:
        raise SystemExit("\n".join(problems))
    return out


def ingest(folder: Path, store: Path | None = None, files_path: Path | None = None) -> dict:
    """Parse every listed file in `folder` and rewrite the store from scratch.

    The set of files is closed, so the store is rebuilt whole rather than
    appended to: a parsing fix is a re-run, with nothing to reconcile.
    """
    store = store or STORE
    files = listed_files(files_path)
    used = [row for row in files if not row.get("skip")]
    agreements: dict[str, dict[str, dict]] = defaultdict(dict)
    texts: dict[str, dict[str, str]] = defaultdict(dict)
    manifest = []
    for row, data in _workbooks(folder, used):
        period = row["period_start"]
        try:
            found = read_workbook(data)
        except EarlierError as error:
            raise SystemExit(f"{row['file']}: {error}") from error
        for (base, version), item in found.items():
            reference = f"{base}-v{version}" if version else base
            record: dict = agreements[base].setdefault(reference, {
                "reference": reference, "version": version, "organisation": "", "organisation_type": "",
                "listed": [], "states": [], "releases": {},
            })
            if item["releases"]:
                record["listed"].append(period)
            # The latest spelling of the applicant, and its type where given.
            record["organisation"] = item["organisation"] or record.get("organisation", "")
            record["organisation_type"] = item["organisation_type"] or record.get("organisation_type", "")
            # A version's text is restated in every file it appears in, and
            # often by the next version too. Each text is kept once per
            # agreement, under a short hash, and each distinct state of a
            # version once, with the periods that published it.
            state = {}
            for field in TEXT_FIELDS:
                text = item["texts"].get(field, "")
                if text:
                    key = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
                    texts[base][key] = text
                    state[field] = key
            for held in record["states"]:
                if {k: v for k, v in held.items() if k != "periods"} == state:
                    held["periods"].append(period)
                    break
            else:
                record["states"].append({"periods": [period], **state})
            for (dataset, form, sensitivity, legal_basis, frequency), count in item["releases"].items():
                key = "\x1f".join((dataset, form, sensitivity, legal_basis, frequency))
                release = record["releases"].setdefault(key, {
                    "dataset": dataset, "form": form, "sensitivity": sensitivity,
                    "legal_basis": legal_basis, "frequency": frequency, "periods": [], "rows": 0,
                })
                if period not in release["periods"]:
                    release["periods"].append(period)
                release["rows"] += count
        manifest.append({
            "file": row["file"], "period_start": period, "period_end": row["period_end"],
            "sha256": row["sha256"], "agreements": len({base for base, _ in found}), "versions": len(found),
        })
        print(f"{row['file']}: {len({base for base, _ in found}):,} agreements, {len(found):,} versions")

    if store.exists():
        shutil.rmtree(store)
    (store / "agreements").mkdir(parents=True)
    for base, versions in agreements.items():
        rows: list[dict] = sorted(versions.values(), key=lambda v: version_key(v["version"]))
        for entry in rows:
            entry["releases"] = sorted(entry["releases"].values(), key=lambda r: (r["periods"][0], r["dataset"]))
        (store / "agreements" / f"{slugify(base)}.json").write_text(
            json.dumps({"base_reference": base, "versions": rows, "texts": dict(sorted(texts[base].items()))},
                       indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    skipped = [{"file": r["file"], "period_start": r["period_start"], "reason": r["skip"]} for r in files if r.get("skip")]
    summary = {"files": manifest, "skipped": skipped, "agreements": len(agreements)}
    (store / "manifest.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(agreements):,} agreements from {len(manifest)} files to {store}")
    return summary


# --- Reading the store for the site -------------------------------------------------------------


def period_label(start: str, end: str) -> str:
    """``2017-03-01``, ``2017-05-31`` -> ``March to May 2017``; one month -> ``March 2017``."""
    if not start:
        return ""
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = (int(end[:4]), int(end[5:7])) if end else (sy, sm)
    first, last = sources.MONTH_NAMES[sm - 1], sources.MONTH_NAMES[em - 1]
    if (sy, sm) == (ey, em):
        return f"{first} {sy}"
    if sy == ey:
        return f"{first} to {last} {sy}"
    return f"{first} {sy} to {last} {ey}"


def load(store: Path | None = None, excluded: frozenset[str] = frozenset()) -> dict | None:
    """`{"periods": {start: end}, "files": [...], "agreements": {base: record}}`, or None with no store."""
    store = store or STORE
    if not (store / "manifest.json").exists():
        return None
    manifest = json.loads((store / "manifest.json").read_text(encoding="utf-8"))
    periods = {row["period_start"]: row["period_end"] for row in manifest["files"]}
    agreements = {}
    for path in sorted((store / "agreements").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["base_reference"].upper() in excluded:
            continue
        agreements[record["base_reference"]] = record
    return {"periods": periods, "files": manifest["files"], "skipped": manifest.get("skipped", []),
            "agreements": agreements}


def _version_view(version: dict, periods: dict[str, str], texts: dict[str, str]) -> dict:
    """One version as a page shows it: when it was listed, its latest text, and what was released."""
    listed = sorted(version["listed"])
    texted = [s for s in version["states"] if any(s.get(f) for f in TEXT_FIELDS)]
    latest_text = max(texted, key=lambda s: max(s["periods"])) if texted else {}
    datasets: dict[str, dict] = {}
    for release in version["releases"]:
        row = datasets.setdefault(release["dataset"] or "Not stated", {
            "dataset": release["dataset"] or "Not stated", "periods": set(), "forms": set(), "frequencies": set(),
        })
        row["periods"].update(release["periods"])
        if release["form"]:
            row["forms"].add(release["form"])
        if release["frequency"]:
            row["frequencies"].add(release["frequency"])
    dataset_rows = []
    for row in datasets.values():
        held = sorted(row["periods"])
        dataset_rows.append({
            "dataset": row["dataset"],
            "first": period_label(held[0], periods.get(held[0], "")),
            "last": period_label(held[-1], periods.get(held[-1], "")),
            "periods": len(held),
            "form": "; ".join(sorted(row["forms"])),
            "frequency": "; ".join(sorted(row["frequencies"])),
            "first_start": held[0],
            "last_start": held[-1],
        })
    dataset_rows.sort(key=lambda r: (r["first_start"], r["dataset"].lower()))
    return {
        "reference": version["reference"],
        "version": version["version"],
        "organisation": version["organisation"],
        "organisation_type": version["organisation_type"],
        "first_listed": listed[0] if listed else "",
        "first_label": period_label(listed[0], periods.get(listed[0], "")) if listed else "",
        "last_label": period_label(listed[-1], periods.get(listed[-1], "")) if listed else "",
        "periods_listed": len(listed),
        "texts": {field: texts.get(latest_text.get(field, ""), "") for field in TEXT_FIELDS},
        "text_period": period_label(max(latest_text["periods"]), periods.get(max(latest_text["periods"]), ""))
        if latest_text else "",
        "datasets": dataset_rows,
    }


def view(record: dict, periods: dict[str, str], held: set[str] | None = None) -> dict:
    """What an agreement page shows from the earlier registers.

    `held` is the set of version references the Data Uses Register editions
    already show; those versions are not repeated, but still count towards the
    first period the agreement was listed.
    """
    held = {r.upper() for r in (held or set())}
    versions = [_version_view(v, periods, record["texts"]) for v in record["versions"]]
    listed = sorted(p for v in record["versions"] for p in v["listed"])
    first = listed[0] if listed else ""
    earlier_only = [v for v in versions if v["reference"].upper() not in held]
    latest = versions[-1] if versions else {}
    organisation = next((v["organisation"] for v in reversed(versions) if v["organisation"]), "")
    return {
        "base_reference": record["base_reference"],
        "slug": slugify(record["base_reference"]),
        "organisation": organisation,
        "organisation_type": next((v["organisation_type"] for v in reversed(versions) if v["organisation_type"]), ""),
        "first_listed": first,
        "first_label": period_label(first, periods.get(first, "")),
        "last_listed": listed[-1] if listed else "",
        "last_label": period_label(listed[-1], periods.get(listed[-1], "")) if listed else "",
        "periods_listed": len(set(listed)),
        "versions": versions,
        # Newest first, as the page's version history is.
        "earlier_only": list(reversed(earlier_only)),
        "latest": latest,
        "dataset_names": sorted({d["dataset"] for v in versions for d in v["datasets"]}, key=str.lower),
    }


# --- Dataset names ------------------------------------------------------------------------------
#
# The earlier registers name datasets their own way: "Standard Monthly Extract :
# HES Inpatient", "Local Provider Data - Acute". A name is linked to one of the
# site's dataset pages only on its spelling, never on which datasets happened to
# be released alongside it (that evidence is swamped by HES, which goes to almost
# everyone). In order:
#
#   1. the name is one the Data Uses Register itself uses, so the site's own
#      aliases already place it;
#   2. it is the same name apart from case, punctuation, "&" for "and",
#      "Dataset" for "Data Set", or an acronym in brackets;
#   3. one of the rewrites below turns it into such a name.
#
# A name that matches more than one page, or none, is shown as written and
# linked nowhere. `python -m pipeline.earlier datasets` lists both.

DATASET_REWRITES: list[tuple[re.Pattern, str]] = [
    # How an extract was produced, not what it holds.
    (re.compile(r"^(standard monthly extract|bespoke extract(/linkage)?)\s*:\s*", re.IGNORECASE), ""),
    (re.compile(r"^HES Inpatients?$", re.IGNORECASE), "Hospital Episode Statistics Admitted Patient Care"),
    (re.compile(r"^HES A&E$", re.IGNORECASE), "Hospital Episode Statistics Accident and Emergency"),
    (re.compile(r"^HES Outpatients?$", re.IGNORECASE), "Hospital Episode Statistics Outpatients"),
    (re.compile(r"^HES Critical Care$", re.IGNORECASE), "Hospital Episode Statistics Critical Care"),
    (re.compile(r"^SUS PbR APC Episodes$", re.IGNORECASE), "Secondary Uses Service Payment By Results Episodes"),
    (re.compile(r"^SUS PbR APC Spells$", re.IGNORECASE), "Secondary Uses Service Payment By Results Spells"),
    (re.compile(r"^SUS PbR A&E$", re.IGNORECASE), "Secondary Uses Service Payment By Results Accident & Emergency"),
    (re.compile(r"^SUS PbR OP$", re.IGNORECASE), "Secondary Uses Service Payment By Results Outpatients"),
    (re.compile(r"^PROMS$", re.IGNORECASE), "Patient Reported Outcome Measures"),
    # The commissioning flows were "Local Provider Data - Acute" before they
    # were "Acute-Local Provider Flows". A name listing several flows at once
    # has no single page, and keeps its comma, so matches nothing.
    (re.compile(r"^Local Provider Data - ([^,]+)$", re.IGNORECASE), r"\1-Local Provider Flows"),
    (re.compile(r"^Primary Care-Local Provider Flows$", re.IGNORECASE), "Primary Care Services-Local Provider Flows"),
    (re.compile(r"^Primary Care Mortality Database$", re.IGNORECASE), "Primary Care Mortality Data"),
]


def dataset_key(name: str) -> str:
    """`name` with case, punctuation, bracketed acronyms and spelling variants that don't matter removed."""
    text = re.sub(r"\([^)]*\)", " ", name.lower())
    text = text.replace("&", " and ").replace("dataset", "data set")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def match_datasets(names, spellings: dict[str, str], alias_map: dict[str, str] | None = None) -> dict[str, dict]:
    """`{earlier name: {"slug", "how"}}` for each name that maps to one dataset page.

    `spellings` is `{every name the Data Uses Register uses: the slug of its page}`;
    `alias_map` is the site's dataset aliases, which know names no current
    version uses.
    """
    alias_map = alias_map or {}
    pages = set(spellings.values())
    by_key: dict[str, set[str]] = defaultdict(set)
    for spelling, slug in spellings.items():
        by_key[dataset_key(spelling)].add(slug)

    def find(name):
        if name in spellings:
            return spellings[name], "the register's own name"
        if slugify(aliases.resolve(name, alias_map)) in pages:
            return slugify(aliases.resolve(name, alias_map)), "the register's own name"
        slugs = by_key.get(dataset_key(name), set())
        if len(slugs) == 1:
            return next(iter(slugs)), "the same name, spelled differently"
        return None, ""

    matched = {}
    for name in names:
        slug, how = find(name)
        if not slug:
            rewritten = name
            for pattern, replacement in DATASET_REWRITES:
                rewritten = pattern.sub(replacement, rewritten).strip()
            if rewritten != name:
                slug, _ = find(rewritten)
                how = f"read as {rewritten!r}"
        if slug:
            matched[name] = {"slug": slug, "how": how}
    return matched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("ingest", "verify", "datasets"))
    parser.add_argument("folder", type=Path, nargs="?", help="the folder holding the workbooks")
    args = parser.parse_args()
    if args.command == "datasets":
        report_datasets()
        return
    if args.folder is None:
        parser.error(f"{args.command} needs the folder holding the workbooks")
    files = [row for row in listed_files() if not row.get("skip")]
    if args.command == "verify":
        _workbooks(args.folder, files)
        print(f"ok: all {len(files)} files match {FILES.name}")
        return
    ingest(args.folder)


def report_datasets() -> None:
    """List how each dataset name in the earlier registers is linked, and which aren't."""
    from . import run
    from .rules import Rules

    rules = Rules.load()
    store = load(excluded=rules.excluded)
    if not store:
        raise SystemExit(f"nothing ingested into {STORE}")
    register = sources.registers("data-uses-register")[0]
    data, _, _ = run.from_store(register, None, rules)
    spellings = dataset_spellings(data["agreements"] + data["archived"], rules.dataset_aliases)
    names: dict[str, int] = defaultdict(int)
    for record in store["agreements"].values():
        for version in record["versions"]:
            for release in version["releases"]:
                names[release["dataset"]] += 1
    matched = match_datasets(names, spellings, rules.dataset_aliases)
    for name in sorted(names, key=lambda n: -names[n]):
        found = matched.get(name)
        print(f"{names[name]:5d}  {name}  ->  {found['slug'] + '  (' + found['how'] + ')' if found else 'NOT LINKED'}")
    print(f"\n{len(matched)} of {len(names)} names linked, covering "
          f"{sum(names[n] for n in matched):,} of {sum(names.values()):,} release rows")


def dataset_spellings(agreements: list[dict], alias_map: dict[str, str]) -> dict[str, str]:
    """`{name: dataset page slug}` for every dataset name the given agreements use."""
    spellings = {}
    for agreement in agreements:
        for version in agreement["versions"]:
            for name in [d["name"] for d in version["datasets"]] + [r["dataset"] for r in version["releases"]]:
                if name and name not in spellings:
                    spellings[name] = slugify(aliases.resolve(name, alias_map))
    return spellings


if __name__ == "__main__":
    main()
