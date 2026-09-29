"""Read a published register workbook into agreement versions.

The workbook has three related sheets keyed on `Reference Number`:

  Agreements    one row per *version* of a data sharing agreement
  Datasets      one row per dataset named on an agreement version
  DataReleases  one row per file actually released against an agreement version

Each row becomes part of one version record (see `records`), grouped under its
agreement's base reference (see `references`); `model.assemble` derives the
site's pages from them, as it does for an edition read back from the facts
store.
"""

from __future__ import annotations

import datetime as dt
import io
import re
from collections import defaultdict

import openpyxl

from . import sources
from .model import assemble
from .records import FILE_RELEASE, clean, clean_line, known_organisation_names, split_list, summarise_releases, tidy_version
from .references import base_and_version
from .rules import Rules


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
    month = sources.MONTH_NUMBER.get(match.group(1).lower())
    if not month:
        return ""
    year = int(match.group(2))
    if year < 100:
        year += 2000
    return f"{year:04d}-{month:02d}"


def read_sheet(workbook, name: str) -> list[dict]:
    if name not in workbook.sheetnames:
        return []
    rows = workbook[name].iter_rows(values_only=True)
    header = [clean(h) for h in next(rows)]
    return [dict(zip(header, row)) for row in rows if any(c is not None for c in row)]


def extract(workbook_bytes: bytes, rules: Rules | None = None) -> dict:
    """Parse workbook bytes into `{agreements, organisations, datasets}`."""
    workbook = openpyxl.load_workbook(io.BytesIO(workbook_bytes), read_only=True, data_only=True)

    datasets_by_ref: dict[str, list[dict]] = defaultdict(list)
    for row in read_sheet(workbook, "Datasets"):
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

    # 100k+ release rows, so they are summarised per dataset rather than kept
    # one by one. `months` holds the count per month — the smallest form that
    # still says *when*, about 41k entries against 104k rows. The register only
    # ever appends to it, which is what lets `facts` keep one copy of a
    # release history for every edition that reports it.
    files_by_ref: dict[str, list[dict]] = defaultdict(list)
    for row in read_sheet(workbook, "DataReleases"):
        reference = clean(row.get("Reference Number"))
        dataset = clean_line(row.get("Dataset"))
        attributes = {
            "type_of_data": clean_line(row.get("Type of Data")),
            "sensitivity": clean_line(row.get("Sensitive or Non-Sensitive")),
            "legal_basis": clean_line(row.get("Legal Basis for Provision of Data")),
            "frequency": clean_line(row.get("Frequency")),
        }
        files_by_ref[reference].append({
            "file": clean(row.get("File Reference")),
            "dataset": dataset,
            "month": parse_release_month(row.get("Month File Released")),
            "channel": FILE_RELEASE,
            "opt_outs_applied": clean(row.get("Patient Opt-Outs Applied")),
            "attributes": attributes,
        })
    releases_by_ref = {
        reference: summarise_releases(released, datasets_by_ref.get(reference, []))
        for reference, released in files_by_ref.items()
    }

    agreement_rows = read_sheet(workbook, "Agreements")
    # Applicant Organisation holds one organisation per row and is never
    # split, so it is the register telling us which names contain a comma.
    # Read them first, then use them to keep those names whole in the
    # controller lists, where the same organisations appear comma-joined.
    known = known_organisation_names(clean_line(r.get("Applicant Organisation")) for r in agreement_rows)

    versions_by_base: dict[str, list[dict]] = defaultdict(list)
    for row in agreement_rows:
        reference = clean(row.get("Reference Number"))
        # A reference always holds a number. The March 2022 workbook carried
        # a spreadsheet note, "No filters applied", in this column.
        if not reference or not any(c.isdigit() for c in reference):
            continue
        base, version = base_and_version(reference)
        datasets = datasets_by_ref.get(reference, [])
        releases = releases_by_ref.get(reference, [])
        versions_by_base[base].append(
            tidy_version({
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
                # The rows behind the summaries, which `facts` stores one by
                # one and the site never reads directly. Ordered by the
                # reference the register issues rather than by sheet row, so a
                # stored edition and a parsed workbook agree.
                "released_files": sorted(files_by_ref.get(reference, []), key=lambda f: f["file"]),
                "files_released": sum(r["files"] for r in releases),
            })
        )

    return assemble(versions_by_base, rules)
