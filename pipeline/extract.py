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

VERSION_SUFFIX = re.compile(r"-v([0-9]+(?:\.[0-9]+)?)$", re.IGNORECASE)
MONTH_ABBR = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}


def slugify(value: str, max_length: int = 80) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
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


def split_list(value) -> list[str]:
    text = clean(value)
    if not text:
        return []
    parts = re.split(r"\s*;\s*|\n+", text)
    return [p.strip() for p in parts if p.strip()]


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

    versions_by_base: dict[str, list[dict]] = defaultdict(list)
    for row in _read_sheet(workbook, "Agreements"):
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
                "controllers": split_list(row.get("Data Controller(s)")),
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
        agreements.append(
            {
                "base_reference": base,
                "slug": slugify(base),
                "title": latest["title"] or base,
                "organisation": latest["organisation"],
                "organisation_slug": slugify(latest["organisation"]),
                "organisation_type": latest["organisation_type"],
                "commercial": latest["commercial"],
                "sublicensing": latest["sublicensing"],
                "controller_basis": latest["controller_basis"],
                "controllers": latest["controllers"],
                "controller_slugs": [slugify(c) for c in latest["controllers"]],
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
    grouped: dict[str, dict] = {}
    for agreement in agreements:
        name = agreement["organisation"] or "Unnamed organisation"
        entry = grouped.setdefault(
            name,
            {
                "name": name,
                "slug": slugify(name),
                "type": agreement["organisation_type"],
                "agreements": [],
                "controller_agreements": [],
            },
        )
        entry["agreements"].append(agreement)

    # An organisation can also appear only as a data controller on someone else's
    # agreement, never as the applicant — this matches controller free text
    # against organisation names by slug, so it's approximate: a controller
    # recorded under a different spelling won't be matched. Track membership by
    # base_reference rather than comparing agreement dicts, which is both faster
    # and correct regardless of dict identity.
    by_slug = {entry["slug"]: entry for entry in grouped.values()}
    seen_refs = {slug: {a["base_reference"] for a in entry["agreements"]} for slug, entry in by_slug.items()}
    for agreement in agreements:
        applicant_slug = agreement["organisation_slug"]
        for controller, controller_slug in zip(agreement["controllers"], agreement["controller_slugs"]):
            if not controller_slug or controller_slug == applicant_slug:
                continue
            entry = by_slug.get(controller_slug)
            if entry is None:
                entry = {
                    "name": controller,
                    "slug": controller_slug,
                    "type": "",
                    "agreements": [],
                    "controller_agreements": [],
                }
                grouped[controller] = entry
                by_slug[controller_slug] = entry
                seen_refs[controller_slug] = set()
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
        entry["organisations"] = sorted({a["organisation"] for a in entry["agreements"]})
        entry["files_released"] = sum(
            r["files"]
            for a in entry["agreements"]
            for v in a["versions"]
            for r in v["releases"]
            if r["dataset"] == entry["name"]
        )
        entry["attributes"] = {k: sorted(v) for k, v in entry["attributes"].items()}
    return sorted(grouped.values(), key=lambda d: (-d["agreement_count"], d["name"].lower()))
