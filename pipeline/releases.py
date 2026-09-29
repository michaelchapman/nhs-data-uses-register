"""Files released over time: the agreement timeline, the monthly charts, and
the check they both rest on.

Every count here comes from one edition's view of the files, as each version's
`releases` summarises them, never from the store's rows: a relabelled dataset's
files are stored again under the new name. See docs/plan.md, "Release views",
for what these figures can and cannot say.
"""

from __future__ import annotations

from collections import Counter

from . import aliases
from .references import slugify

# The register lists few files before 2019 (1,727 across 2016-2018), and its
# coverage fills in through 2019: agreements receiving files rise from 28 in
# January to 152 in July, where from 2020 the count has stayed between 87 and
# 271. It was already so in the earliest edition held, and why is not known,
# so a chart starts after it and the months before are left to the table.
CHART_START = "2020-01"


def month_range(start: str, end: str) -> list[str]:
    """Every month from `start` to `end` inclusive, as "YYYY-MM"."""
    year, month = map(int, start.split("-"))
    last = tuple(map(int, end.split("-")))
    months = []
    while (year, month) <= last:
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def last_month(as_of: str) -> str:
    """The last month an edition can report: the one before it was published.
    99% of files first appear in the next month's edition, so it is complete."""
    year, month = map(int, as_of[:7].split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def by_dataset(agreement: dict, alias_map: dict) -> dict[str, dict]:
    """`{dataset page slug: {dataset, slug, months: Counter}}` across every version.

    Keyed on the page a name belongs to, so a dataset relabelled between
    versions is one row. `dataset` is the name as the latest version wrote it.
    """
    rows: dict[str, dict] = {}
    for version in agreement["versions"]:
        for release in version["releases"]:
            slug = slugify(aliases.resolve(release["dataset"], alias_map))
            row = rows.setdefault(slug, {"dataset": release["dataset"], "slug": slug, "months": Counter()})
            row["dataset"] = release["dataset"]
            row["months"].update(release["months"])
    return rows


def check(agreements: list[dict], datasets: list[dict], alias_map: dict) -> None:
    """Files per agreement, dataset and month must add up to what the pages say.

    The timelines and charts are drawn from the months; the tables and totals
    from the per-dataset summaries. If the two ever disagree, stop the build
    rather than publish a chart that contradicts its own page.
    """
    problems = []
    per_dataset: Counter = Counter()
    for agreement in agreements:
        rows = by_dataset(agreement, alias_map)
        monthly = sum(sum(row["months"].values()) for row in rows.values())
        if monthly != agreement["files_released"]:
            problems.append(
                f"{agreement['base_reference']}: {monthly:,} files by month, "
                f"{agreement['files_released']:,} on the page"
            )
        for slug, row in rows.items():
            per_dataset[slug] += sum(row["months"].values())
    for dataset in datasets:
        if per_dataset[dataset["slug"]] != dataset["files_released"]:
            problems.append(
                f"dataset {dataset['slug']}: {per_dataset[dataset['slug']]:,} files by month, "
                f"{dataset['files_released']:,} on the page"
            )
    if problems:
        raise SystemExit("releases: the monthly counts disagree with the pages:\n  " + "\n  ".join(problems))


def _position(month: str, months: list[str]) -> float:
    return 100 * months.index(month) / len(months)


def _years(months: list[str]) -> list[dict]:
    """Where each year starts along an axis, labelled every year or every
    other year so the labels never crowd a narrow timeline."""
    # Januaries only, so labels are evenly spaced; a span that holds none
    # is labelled with its own year.
    starts = [(i, m[:4]) for i, m in enumerate(months) if m.endswith("-01")] or [(0, months[0][:4])]
    step = 1 if len(starts) <= 7 else 2
    return [
        {"left": 100 * i / len(months), "year": year, "label": n % step == 0}
        for n, (i, year) in enumerate(starts)
    ]


def agreement_timeline(agreement: dict, alias_map: dict, as_of: str) -> dict | None:
    """One strip per dataset: a mark for every month with files, the terms of
    the agreement's versions behind them. `None` if no files are recorded.

    The axis runs from the first release or term start, whichever is earlier
    (never before the register's first release month), to the last release or
    term end, never past the last month the edition reports.
    """
    rows = by_dataset(agreement, alias_map)
    if not rows:
        return None
    released = sorted({m for row in rows.values() for m in row["months"]})
    starts = [v["start_date"][:7] for v in agreement["versions"] if v["start_date"]]
    ends = [v["end_date"][:7] for v in agreement["versions"] if v["end_date"]]
    edition_end = last_month(as_of)
    start = max(min([released[0], *starts]), "2016-04")
    end = min(max([released[-1], *ends]), edition_end)
    end = max(end, released[-1])
    months = month_range(start, end)

    def span(first: str, last: str) -> dict | None:
        first, last = max(first, start), min(last, end)
        if first > last:
            return None
        left = _position(first, months)
        return {"left": left, "width": 100 * (months.index(last) + 1) / len(months) - left}

    terms = []
    for version in agreement["versions"]:
        if not version["start_date"]:
            continue
        shown = span(version["start_date"][:7], (version["end_date"] or version["start_date"])[:7])
        if shown:
            terms.append({**shown, "version": version["version"], "start": version["start_date"],
                          "end": version["end_date"]})

    width = 100 / len(months)
    strips = []
    for row in sorted(rows.values(), key=lambda r: (-sum(r["months"].values()), r["dataset"].casefold())):
        strips.append({
            "dataset": row["dataset"],
            "slug": row["slug"],
            "files": sum(row["months"].values()),
            "months": len(row["months"]),
            "marks": [
                {"left": _position(m, months), "width": width, "month": m, "files": n}
                for m, n in sorted(row["months"].items()) if start <= m <= end
            ],
            "by_year": _year_totals(row["months"]),
        })
    return {
        "start": start,
        "end": end,
        "runs_on": max(ends, default="") > edition_end,
        "months": len(months),
        "terms": terms,
        "strips": strips,
        "years": _years(months),
        "table_years": sorted({y for s in strips for y, n in s["by_year"].items() if n}),
        "months_with_files": len(released),
    }


def _year_totals(months: Counter) -> Counter:
    totals: Counter = Counter()
    for month, files in months.items():
        totals[month[:4]] += files
    return totals


def monthly(
    agreements: list[dict], alias_map: dict, dataset_slug: str | None = None, rows: dict | None = None
) -> dict[str, dict]:
    """`{month: {files, agreements}}` across `agreements`, for one dataset page
    if `dataset_slug` is given. `agreements` counts those with a file that month.

    `rows`, `{base reference: by_dataset(agreement)}`, saves working each
    agreement out again for every dataset page that lists it.
    """
    files: Counter = Counter()
    holders: dict[str, set] = {}
    for agreement in agreements:
        found = rows.get(agreement["base_reference"]) if rows is not None else None
        for slug, row in (found if found is not None else by_dataset(agreement, alias_map)).items():
            if dataset_slug is not None and slug != dataset_slug:
                continue
            for month, n in row["months"].items():
                files[month] += n
                holders.setdefault(month, set()).add(agreement["base_reference"])
    return {m: {"files": files[m], "agreements": len(holders[m])} for m in sorted(files)}


def _nice_top(value: int) -> tuple[int, int]:
    """The axis top and tick step: a clean number at or above `value`, in
    three or four steps of 1, 2 or 5 times a power of ten."""
    if value <= 0:
        return 1, 1
    step = 1
    while True:
        for factor in (1, 2, 5):
            candidate = step * factor
            if value / candidate <= 4:
                return candidate * -(-value // candidate), candidate
        step *= 10


def chart(by_month: dict[str, dict], key: str, end: str, start: str = CHART_START) -> dict:
    """Columns for one measure, `files` or `agreements`, from `start` to `end`.

    Only months with a value get a column; each is placed by its position, so
    a sparse series costs a sparse page.
    """
    months = month_range(start, end)
    if not months:
        return {"columns": [], "ticks": [], "years": [], "latest": {"month": end, "value": 0}, "peak": None}
    values = {m: by_month[m][key] for m in months if m in by_month and by_month[m][key]}
    top, step = _nice_top(max(values.values(), default=0))
    width = 100 / len(months)
    peak = max(values, key=lambda m: values[m], default=None)
    return {
        "columns": [
            {"left": _position(m, months), "width": width, "height": 100 * v / top, "month": m, "value": v}
            for m, v in values.items()
        ],
        "ticks": [{"value": v, "bottom": 100 * v / top} for v in range(0, top + 1, step)],
        "years": _years(months),
        "latest": {"month": end, "value": values.get(end, 0)},
        "peak": {"month": peak, "value": values[peak]} if peak else None,
    }
