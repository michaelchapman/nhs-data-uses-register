"""The data file the site publishes beside its pages: `downloads/agreements.csv`.

One row per agreement in the edition, with what this site works out and the
register's workbook does not hold: the organisation page each applicant and
data controller is listed under, after merged spellings and NHS
reorganisations; its sector; whether the agreement is in term; the bases on
which confidential data may flow, and whether patient opt-outs were applied,
across every version; and each dataset under the one name its page uses.

The purpose text is left out. It is most of the register's size, and the
workbook holds it. So are agreements no longer in the register, which no count
on the site includes either.
"""

from __future__ import annotations

import csv
import io

from . import aliases, privacy

# (column, what it holds), in order. The downloads page lists them.
COLUMNS = (
    ("reference", "The agreement's base reference, without a version suffix"),
    ("title", "Title of the latest version"),
    ("organisation", "Applicant, as the register writes it"),
    ("organisation_page", "The organisation page the applicant is listed under on this site"),
    ("organisation_type", "Applicant organisation type, as the register gives it"),
    ("sector", "This site's sector for the applicant"),
    ("status", "In term, Expired or End not stated, as of the edition"),
    ("latest_version", "Version number of the latest version"),
    ("latest_start", "Start date of the latest version"),
    ("latest_end", "End date of the agreement's term"),
    ("first_start", "Earliest start date of any version held"),
    ("first_start_known", "yes if the first version is held, no if earlier versions came before this site's records"),
    ("commercial", "For commercial purposes, from the latest version"),
    ("sublicensing", "Sublicensing applies, from the latest version"),
    ("controller_basis", "Sole or joint data controller"),
    ("data_controllers", "Data controllers by organisation page, separated by semicolons"),
    ("datasets", "Datasets named on any version, by dataset page, separated by semicolons"),
    ("dataset_count", "Number of datasets"),
    ("files_released", "Files released under every version"),
    ("confidential_data", "Bases on which confidential patient information may flow, from the latest version"),
    ("opt_outs", "Whether patient opt-outs were applied to the files released"),
    ("opt_out_files", "Files released with patient opt-outs applied"),
    ("url", "This agreement's page on this site"),
)

CONFIDENTIALITY_LABELS = dict(privacy.CONFIDENTIALITY_OPTIONS)
OPT_OUT_LABELS = dict(privacy.OPT_OUT_OPTIONS)


def _status(agreement: dict, as_of: str) -> str:
    """As the status tag on the site words it (templates/_status.html)."""
    if agreement["coverage_end"] >= as_of:
        return "In term"
    return "Expired" if agreement["coverage_end"] else "End not stated"


def agreement_row(agreement: dict, meta: dict, org_names: dict[str, str], dataset_aliases: dict[str, str]) -> dict:
    latest = agreement["latest"]
    # A dataset the register renamed between versions is one dataset.
    datasets = sorted({aliases.resolve(name, dataset_aliases) for name in agreement["dataset_names"]})
    return {
        "reference": agreement["base_reference"],
        "title": agreement["title"],
        "organisation": agreement["organisation"],
        "organisation_page": org_names.get(agreement["organisation_slug"], agreement["organisation"]),
        "organisation_type": agreement["organisation_type"],
        "sector": agreement.get("sector", ""),
        "status": _status(agreement, meta["as_of"]),
        "latest_version": latest["version"],
        "latest_start": agreement["latest_start"],
        "latest_end": agreement["coverage_end"],
        "first_start": agreement["first_start"],
        "first_start_known": "yes" if agreement["first_start_known"] else "no",
        "commercial": agreement["commercial"],
        "sublicensing": agreement["sublicensing"],
        "controller_basis": agreement["controller_basis"],
        "data_controllers": "; ".join(org_names.get(row["slug"], row["name"]) for row in agreement["controller_rows"]),
        "datasets": "; ".join(datasets),
        "dataset_count": len(datasets),
        "files_released": agreement["files_released"],
        "confidential_data": "; ".join(CONFIDENTIALITY_LABELS[key] for key in agreement["confidentiality"]),
        "opt_outs": OPT_OUT_LABELS[agreement["opt_outs"]["state"]],
        "opt_out_files": agreement["opt_outs"]["applied"],
        "url": f"{meta['site_url']}{meta['base_path']}/agreements/{agreement['slug']}/",
    }


def agreements_csv(agreements: list[dict], meta: dict, org_names: dict[str, str], dataset_aliases: dict[str, str]) -> str:
    """The file's text: a header row, then one row per agreement, in the site's order."""
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=[name for name, _ in COLUMNS])
    writer.writeheader()
    for agreement in agreements:
        writer.writerow(agreement_row(agreement, meta, org_names, dataset_aliases))
    return out.getvalue()
