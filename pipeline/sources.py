"""Register definitions and the naming rules for published workbooks.

NHS England republishes the DARS registers every month at a new URL whose
filename carries the edition (e.g. ``datausesregister_july2026.xlsx``), and
keeps previous editions on a release archive page.

This module used to scrape the landing page and download the current workbook.
It no longer does. ``digital.nhs.uk`` sits behind a WAF that refuses requests
from datacentre address space: every scheduled build failed with HTTP 403, and
so did the asset URLs, a browser-shaped User-Agent and a backoff-retry. The
workbooks are now downloaded by hand and ingested with ``pipeline.ingest``;
see docs/manual-updates.md. Please don't re-add a fetch path here without
checking that the 403 has actually gone away.

What remains is the vocabulary: which registers exist, and how to recognise a
downloaded file and order the editions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

LANDING_PAGE = (
    "https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register"
)
ARCHIVE_PAGE = f"{LANDING_PAGE}/release-register-archive"
# Published workbooks live under a stable asset prefix; the edition filename is
# appended. Used to reconstruct a citation URL for a file downloaded by hand.
ASSET_PREFIX = (
    "https://digital.nhs.uk/binaries/content/assets/website-assets/services/dars"
    "/data-uses-register"
)

MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
MONTH_NUMBER = {name: i for i, name in enumerate(MONTHS, start=1)}
MONTH_NUMBER.update({name[:3]: i for i, name in enumerate(MONTHS, start=1)})

EDITION_RE = re.compile(r"_([a-z]+)(\d{4})$", re.IGNORECASE)


@dataclass(frozen=True)
class Register:
    """One publication we mirror."""

    slug: str
    name: str
    description: str
    # Matches the stem of a downloaded workbook, e.g. datausesregister_july2026.
    filename_pattern: str
    # Sheets we expect, in the order they should be extracted.
    sheets: tuple[str, ...] = ("Agreements", "Datasets", "DataReleases")
    enabled: bool = True
    notes: str = ""
    extra: dict = field(default_factory=dict)


REGISTERS: list[Register] = [
    Register(
        slug="data-uses-register",
        name="Data Uses Register",
        description=(
            "Data sharing agreements under which NHS England has released data to "
            "organisations outside NHS England, the datasets covered by each "
            "agreement, and the individual files released against them."
        ),
        filename_pattern=r"^datausesregister_[a-z]+\d{4}$",
    ),
    # Not yet extracted — the sheet layouts differ. Left here so the shape of the
    # extension is obvious: set enabled=True once extract.py handles the layout.
    Register(
        slug="internal-data-uses-register",
        name="Internal Data Uses Register",
        description="NHS England's own internal uses of the data it holds.",
        filename_pattern=r"^internaldatausesregister_[a-z]+\d{4}$",
        enabled=False,
    ),
    Register(
        slug="data-sharing-framework-contracts",
        name="Data Sharing Framework Contracts",
        description="Framework contracts that sit above individual data sharing agreements.",
        filename_pattern=r"^datasharingframeworkcontracts_[a-z]+\d{4}$",
        enabled=False,
    ),
]


def registers(only: str | None = None) -> list[Register]:
    """Enabled registers, or the single register named by `only`."""
    if only:
        matches = [r for r in REGISTERS if r.slug == only]
        if not matches:
            raise SystemExit(f"unknown register: {only}")
        return matches
    return [r for r in REGISTERS if r.enabled]


def register_for_filename(stem: str) -> Register | None:
    """The register a downloaded workbook belongs to, by filename stem."""
    for register in REGISTERS:
        if re.match(register.filename_pattern, stem, re.IGNORECASE):
            return register
    return None


def parse_edition(stem: str) -> str:
    """``datausesregister_july2026`` -> ``july2026``. Raises if unrecognisable."""
    match = EDITION_RE.search(stem)
    if not match or match.group(1).lower() not in MONTH_NUMBER:
        raise ValueError(
            f"cannot read an edition from {stem!r}; expected a name ending "
            "'_<month><year>', e.g. datausesregister_july2026"
        )
    return f"{match.group(1)}{match.group(2)}".lower()


def edition_sort_key(edition: str) -> tuple[int, int]:
    """``july2026`` -> ``(2026, 7)``, so editions sort by when they were published.

    Ordering has to come from the edition label, not from when we happened to
    ingest the file: backfilling an archive gives every edition near-identical
    ingest timestamps.
    """
    match = re.match(r"^([a-z]+)(\d{4})$", edition, re.IGNORECASE)
    if not match:
        return (0, 0)
    return (int(match.group(2)), MONTH_NUMBER.get(match.group(1).lower(), 0))


def edition_published(edition: str) -> str:
    """``july2026`` -> ``2026-07``."""
    year, month = edition_sort_key(edition)
    return f"{year:04d}-{month:02d}" if year and month else ""


def asset_url(filename: str) -> str:
    """The canonical published URL for a workbook, from its filename."""
    return f"{ASSET_PREFIX}/{filename}"
