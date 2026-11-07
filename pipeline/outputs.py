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

A paper with no DOI carries `"pmcid": "PMC123"` instead and links to Europe PMC.
A paper with an empty title is shown by its DOI or PMCID, marked "title not
available".

`basis` is why a paper is listed:

- ``found``: the review found the paper used this agreement's data. It quotes
  the agreement's reference or an identifier the agreement carries, and names
  NHS England data, or a model check confirmed it with a quote from the paper.

The rest are papers the register's own benefit text cites, which the review
did not confirm. Every one is shown, labelled with the review's result
(Michael's decision, 7 November 2026: it is the applicant's public claim):

- ``unreadable``: its full text isn't openly available, so it wasn't checked.
- ``unconfirmed`` (it names NHS England data but nothing ties it to this
  agreement), ``no-nhs-data`` (its open text names none) and ``other-study``
  (a model check found another study's data): all shown as "the review
  couldn't confirm it used this agreement's data", never as a rejection.

Any other basis (a probable match the register doesn't cite, a protocol) stops
the build, so a link that hasn't been decided on can't reach the site by
accident. Only the fields above are read: anything else in the file, such as
quotes from a paper, is ignored.

With no file, agreement pages have no papers section and the About page says
nothing about it.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path

from .references import base_and_version, slugify

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "outputs.json"

# The review's result for a register-cited paper it did not confirm, as the page says it. The three ways a
# read paper can fall short are all shown as "couldn't confirm", not as a rejection (Michael, 7 November 2026).
NOT_CONFIRMED = "couldn't confirm it used this agreement's data"
RESULTS = {
    "unreadable": "full text not openly available, so not checked",
    "unconfirmed": NOT_CONFIRMED,
    "no-nhs-data": NOT_CONFIRMED,
    "other-study": NOT_CONFIRMED,
}
BASES = ("found", *RESULTS)
DOI = re.compile(r"^10\.\d{4,9}/\S+$")
PMCID = re.compile(r"^PMC\d+$")
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
        pmcid = (row.get("pmcid") or "").strip().upper()
        if doi:
            if not DOI.match(doi):
                raise OutputsError(f"{where}: {doi!r} is not a DOI")
            key, url = doi.lower(), f"https://doi.org/{doi}"
        elif PMCID.match(pmcid):
            key, url = pmcid.lower(), f"https://europepmc.org/article/PMC/{pmcid}"
        else:
            raise OutputsError(f"{where}: no DOI or PMCID")
        # A paper with no known title (some the register cites are in no index) is shown by its identifier.
        title = " ".join((row.get("title") or "").split())
        if len(title) > TITLE_LIMIT:
            raise OutputsError(f"{where}: title is over {TITLE_LIMIT} characters")
        base = base_and_version((row.get("agreement") or "").strip())[0].upper()
        if not base:
            raise OutputsError(f"{where}: no agreement reference")
        if (base, key) in seen:
            continue
        seen.add((base, key))
        year = row.get("year")
        by_agreement.setdefault(base, []).append({
            "id": key,
            "doi": doi,
            "pmcid": pmcid if not doi else "",
            "url": url,
            "title": title or (f"doi:{doi}" if doi else pmcid),
            "untitled": not title,
            "year": int(year) if year else None,
            "basis": basis,
            "result": RESULTS.get(basis, ""),
            "register_cited": bool(row.get("register_cited")) or basis != "found",
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
        "cited": [r for r in rows if r["basis"] != "found"],
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
        "found_papers": len({r["id"] for rows in listed.values() for r in rows if r["basis"] == "found"}),
        "cited_papers": len({r["id"] for rows in listed.values() for r in rows if r["basis"] != "found"}
                            - {r["id"] for rows in listed.values() for r in rows if r["basis"] == "found"}),
        "unreadable_papers": len({r["id"] for rows in listed.values() for r in rows if r["basis"] == "unreadable"}),
        "register_edition": outputs["register_edition"],
    }


def papers(outputs: dict | None, agreements: list[dict]) -> list[dict]:
    """Every linked paper once, with the agreements it is linked to.

    A paper is "found" if the review found it used any one agreement's data,
    and "cited" if it is listed only because the register cites it; each
    agreement keeps its own reason. Agreements with no page
    here are left out, and so is a paper left with none.
    """
    if not outputs:
        return []
    pages = {a["base_reference"].upper(): a for a in agreements}
    by_doi: dict[str, dict] = {}
    for ref, rows in outputs["by_agreement"].items():
        agreement = pages.get(ref)
        if not agreement:
            continue
        for r in rows:
            paper = by_doi.setdefault(r["id"], {**r, "basis": "cited", "agreements": []})
            if r["basis"] == "found":
                paper["basis"] = "found"
            paper["register_cited"] = paper["register_cited"] or r["register_cited"]
            paper["agreements"].append({"agreement": agreement, "basis": r["basis"], "result": r["result"]})
    for paper in by_doi.values():
        paper["agreements"].sort(key=lambda link: (link["basis"] != "found", link["agreement"]["base_reference"]))
    for paper in by_doi.values():
        linked = [link["agreement"] for link in paper["agreements"]]
        paper["organisations"] = sorted({a["organisation_slug"] for a in linked})
        # What the agreements released, not what the paper itself used: a
        # paper may use only some of the datasets its agreement names.
        paper["datasets"] = sorted({slug for a in linked for slug in a.get("dataset_slugs", [])})
        paper["sectors"] = sorted({a["sector"] for a in linked if a.get("sector")})
    return sorted(by_doi.values(), key=lambda p: (-(p["year"] or 0), p["title"].lower()))


def by_organisation(papers: list[dict]) -> dict[str, int]:
    """How many papers are linked to each applicant organisation's agreements."""
    counts: dict[str, int] = {}
    for paper in papers:
        for slug in paper["organisations"]:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


def by_dataset(papers: list[dict]) -> dict[str, int]:
    """How many papers are linked to agreements naming each dataset."""
    counts: dict[str, int] = {}
    for paper in papers:
        for slug in paper["datasets"]:
            counts[slug] = counts.get(slug, 0) + 1
    return counts


# The chart of papers by year starts here; the few earlier ones are in its table.
CHART_FROM = 2010


def _nice_top(value: int) -> tuple[int, int]:
    """A round top for the scale, and the step between its ticks."""
    step = 1
    while True:
        for factor in (1, 2, 5):
            candidate = step * factor
            if value / candidate <= 4:
                return candidate * -(-max(value, 1) // candidate), candidate
        step *= 10


def by_year(papers: list[dict], exported: str) -> dict:
    """Papers by year of publication, split by why they are listed, for a chart and its table.

    The year of the export is marked as partial: the review ran part way through it.
    """
    rows: dict[int, dict] = {}
    undated = 0
    for paper in papers:
        if not paper["year"]:
            undated += 1
            continue
        row = rows.setdefault(paper["year"], {"year": paper["year"], "found": 0, "cited": 0})
        row["found" if paper["basis"] == "found" else "cited"] += 1
    partial = int(exported[:4]) if exported[:4].isdigit() else None
    years = sorted(rows)
    table = [{**rows[y], "total": rows[y]["found"] + rows[y]["cited"], "partial": y == partial} for y in years]
    shown = [y for y in range(CHART_FROM, (years[-1] if years else CHART_FROM) + 1)]
    top, step = _nice_top(max((rows[y]["found"] + rows[y]["cited"] for y in shown if y in rows), default=0))
    columns = []
    for y in shown:
        row = rows.get(y, {"found": 0, "cited": 0})
        columns.append({
            "year": y,
            "found": row["found"],
            "cited": row["cited"],
            "found_height": 100 * row["found"] / top,
            "cited_height": 100 * row["cited"] / top,
            "partial": y == partial,
            # Every other year labelled, and every fourth on a phone, counting back from the last.
            "label": (shown[-1] - y) % 2 == 0,
            "major": (shown[-1] - y) % 4 == 0,
        })
    return {
        "columns": columns,
        "ticks": [{"value": v, "bottom": 100 * v / top} for v in range(0, top + 1, step)],
        "table": table[::-1],
        "earlier": sum(r["total"] for r in table if r["year"] < CHART_FROM),
        "undated": undated,
        "partial": partial if partial in rows else None,
    }


def lag(papers: list[dict]) -> dict | None:
    """Years from an agreement's first start to its papers, where that start is known.

    A paper linked to several agreements is measured from the earliest of them.
    An agreement whose earliest version this site holds isn't its first has no
    known start (the register's history starts part way through), so it is left
    out; so is a paper published before its agreement started, which most often
    came from an earlier agreement under another system.
    """
    gaps = []
    for paper in papers:
        starts = [int(link["agreement"]["first_start"][:4]) for link in paper["agreements"]
                  if link["agreement"].get("first_start_known") and link["agreement"].get("first_start")]
        if paper["year"] and starts and paper["year"] >= min(starts):
            gaps.append(paper["year"] - min(starts))
    if len(gaps) < 20:
        return None
    gaps.sort()

    def at(share: float) -> int:
        return gaps[min(len(gaps) - 1, int(share * len(gaps)))]

    return {"papers": len(gaps), "median": at(0.5), "low": at(0.25), "high": at(0.75)}


def coverage(papers: list[dict], agreements: list[dict], sector_names: list[str]) -> list[dict]:
    """For each sector: its agreements, how many have a linked paper, and its papers."""
    with_paper = {link["agreement"]["base_reference"] for p in papers for link in p["agreements"]}
    rows = []
    for name in sector_names:
        these = [a for a in agreements if a.get("sector") == name]
        if not these:
            continue
        rows.append({
            "sector": name,
            "slug": slugify(name),
            "agreements": len(these),
            "with_paper": sum(a["base_reference"] in with_paper for a in these),
            "papers": sum(name in p["sectors"] for p in papers),
        })
    return rows


CSV_COLUMNS = ("title", "year", "doi", "pmcid", "url", "why_listed", "also_cited_in_register",
               "agreements", "organisations", "register_edition")


def as_csv(papers: list[dict], org_names: dict[str, str], register_edition: str) -> str:
    """The papers table as CSV, one row per paper, for people who want to count for themselves."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for p in papers:
        writer.writerow([
            "" if p["untitled"] else p["title"],
            p["year"] or "",
            p["doi"],
            p["pmcid"],
            p["url"],
            "found to have used the data" if p["basis"] == "found" else "cited in the register, not confirmed",
            "yes" if p["register_cited"] else "no",
            "; ".join(link["agreement"]["base_reference"] for link in p["agreements"]),
            "; ".join(org_names.get(slug, slug) for slug in p["organisations"]),
            register_edition,
        ])
    return out.getvalue()
