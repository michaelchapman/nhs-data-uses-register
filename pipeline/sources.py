"""Register definitions and discovery of the current published files.

NHS England republishes the DARS registers every month at a new URL whose
filename carries the edition (e.g. ``datausesregister_july2026.xlsx``). Rather
than hard-code a URL that goes stale, we scrape the register landing page and
pick the link matching each register's filename pattern.

Adding another register (the internal register, the DSFC register, the COVID-19
archive) is a matter of appending a `Register` here and teaching
`extract.py` about its sheet layout.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field

LANDING_PAGE = (
    "https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register"
)

# digital.nhs.uk serves 403s to some default agents; identify ourselves clearly.
USER_AGENT = (
    "nhs-data-uses-register-mirror/1.0 "
    "(+https://github.com/michaelchapman/nhs-data-uses-register)"
)


@dataclass(frozen=True)
class Register:
    """One publication we mirror."""

    slug: str
    name: str
    description: str
    # Matches the href of the download link on the landing page.
    href_pattern: str
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
        href_pattern=r"/dars/data-uses-register/datausesregister_[a-z]+\d{4}\.xlsx$",
    ),
    # Not yet extracted — the sheet layouts differ. Left here so the shape of the
    # extension is obvious: set enabled=True once extract.py handles the layout.
    Register(
        slug="internal-data-uses-register",
        name="Internal Data Uses Register",
        description="NHS England's own internal uses of the data it holds.",
        href_pattern=r"/internal/\d{4}/internaldatausesregister_[a-z]+\d{4}\.xlsx$",
        enabled=False,
    ),
    Register(
        slug="data-sharing-framework-contracts",
        name="Data Sharing Framework Contracts",
        description="Framework contracts that sit above individual data sharing agreements.",
        href_pattern=r"/dars/data-uses-register/datasharingframeworkcontracts_[a-z]+\d{4}\.xlsx$",
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


def fetch(url: str, timeout: int = 300) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def discover(register: Register, landing_html: str | None = None) -> tuple[str, str]:
    """Return `(absolute_url, edition)` for the register's current file.

    `edition` is the month slug lifted from the filename, e.g. ``july2026``.
    """
    html = landing_html or fetch(LANDING_PAGE).decode("utf-8", "replace")
    hrefs = re.findall(r'href="([^"]+\.xlsx)"', html, flags=re.IGNORECASE)
    matches = [h for h in hrefs if re.search(register.href_pattern, h, re.IGNORECASE)]
    if not matches:
        raise SystemExit(
            f"no download link matching {register.href_pattern!r} on {LANDING_PAGE}. "
            "The page layout may have changed — check pipeline/sources.py."
        )
    href = matches[0]
    url = href if href.startswith("http") else f"https://digital.nhs.uk{href}"
    edition_match = re.search(r"_([a-z]+\d{4})\.xlsx$", url, re.IGNORECASE)
    edition = edition_match.group(1).lower() if edition_match else "unknown"
    return url, edition
