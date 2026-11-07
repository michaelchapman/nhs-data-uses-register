"""Papers linked to agreements, shown on agreement pages.

The links come from a separate review of published papers, not from the
register. That review runs elsewhere and exports one file, committed here as
`data/outputs.json`:

    {
      "register_edition": "november2026",
      "source_commit": "c65350e",
      "exported": "2026-11-07",
      "outputs": [
        {"agreement": "DARS-NIC-00574-V2H1F", "doi": "10.1136/bmj.n1",
         "title": "...", "year": 2024, "basis": "found", "register_cited": true}
      ]
    }

`basis` is why a paper is listed, and only two reasons are shown:

- ``found``: the review found the paper used this agreement's data. It quotes
  the agreement's reference or an identifier the agreement carries, and names
  NHS England data, or a model check confirmed it with a quote from the paper.
- ``unreadable``: the register's own benefit text cites the paper, but its
  full text isn't openly available, so the review couldn't check it.

Any other basis (a probable match, a rejected one, a protocol) stops the build,
so a link that hasn't been decided on can't reach the site by accident. Only
the fields above are read: anything else in the file, such as quotes from a
paper, is ignored.

With no file, agreement pages have no papers section and the About page says
nothing about it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .references import base_and_version

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "outputs.json"

BASES = ("found", "unreadable")
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
TITLE_LIMIT = 400


class OutputsError(ValueError):
    pass


def load(path: Path | None = None) -> dict | None:
    """The checked contents of data/outputs.json, or None if there is none."""
    path = path or PATH
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    for key in ("register_edition", "source_commit", "outputs"):
        if key not in raw:
            raise OutputsError(f"{path.name}: missing {key!r}")
    by_agreement: dict[str, list[dict]] = {}
    seen: set[tuple[str, str]] = set()
    for n, row in enumerate(raw["outputs"], 1):
        where = f"{path.name}: output {n}"
        basis = row.get("basis")
        if basis not in BASES:
            raise OutputsError(f"{where}: basis {basis!r} is not one the site shows ({', '.join(BASES)})")
        doi = (row.get("doi") or "").strip()
        doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", doi, flags=re.IGNORECASE)
        if not DOI.match(doi):
            raise OutputsError(f"{where}: {doi!r} is not a DOI")
        title = " ".join((row.get("title") or "").split())
        if not title:
            raise OutputsError(f"{where}: no title")
        if len(title) > TITLE_LIMIT:
            raise OutputsError(f"{where}: title is over {TITLE_LIMIT} characters")
        base = base_and_version((row.get("agreement") or "").strip())[0].upper()
        if not base:
            raise OutputsError(f"{where}: no agreement reference")
        if (base, doi.lower()) in seen:
            continue
        seen.add((base, doi.lower()))
        year = row.get("year")
        by_agreement.setdefault(base, []).append({
            "doi": doi,
            "url": f"https://doi.org/{doi}",
            "title": title,
            "year": int(year) if year else None,
            "basis": basis,
            "register_cited": bool(row.get("register_cited")) or basis == "unreadable",
        })
    for rows in by_agreement.values():
        rows.sort(key=lambda r: (-(r["year"] or 0), r["title"].lower()))
    return {
        "register_edition": raw["register_edition"],
        "source_commit": raw["source_commit"],
        "exported": raw.get("exported", ""),
        "by_agreement": by_agreement,
    }


def for_agreement(agreement: dict, outputs: dict | None) -> dict | None:
    """The papers listed for `agreement`, split by why they are listed."""
    if not outputs:
        return None
    rows = outputs["by_agreement"].get(agreement["base_reference"].upper())
    if not rows:
        return None
    return {
        "found": [r for r in rows if r["basis"] == "found"],
        "unreadable": [r for r in rows if r["basis"] == "unreadable"],
        "register_edition": outputs["register_edition"],
        "source_commit": outputs["source_commit"],
    }


def stats(outputs: dict | None, references: set[str]) -> dict | None:
    """Counts for the About page, over agreements this edition lists."""
    if not outputs:
        return None
    listed = {ref: rows for ref, rows in outputs["by_agreement"].items() if ref in references}
    found = {ref for ref, rows in listed.items() if any(r["basis"] == "found" for r in rows)}
    return {
        "agreements": len(listed),
        "found_agreements": len(found),
        "found_papers": len({r["doi"].lower() for rows in listed.values() for r in rows if r["basis"] == "found"}),
        "unreadable_papers": len({r["doi"].lower() for rows in listed.values() for r in rows if r["basis"] == "unreadable"}),
        "register_edition": outputs["register_edition"],
    }
