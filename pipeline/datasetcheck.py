"""Find datasets that were renamed between editions, and merge them.

    python -m pipeline.datasetcheck            # list candidates
    python -m pipeline.datasetcheck --review   # decide one at a time
    python -m pipeline.datasetcheck --auto     # apply the unambiguous ones

The register relabels datasets. In January 2023 it appended an acronym to
most of them at once — "Hospital Episode Statistics Admitted Patient Care"
became "... (HES APC)", "Civil Registration - Deaths" became "Civil
Registrations of Death" — which the site recorded as 2,455 amendments and
which silently split each dataset's history across two pages.

This is `orgcheck` for datasets, and it only looks across editions, because
that is where a rename is visible: the old name is absent from the current
edition entirely. Candidates come from `compare.membership_renames`, which
pairs a name that vanished with one that appeared on the same agreements
rather than with one that merely looks similar — the two cannot be told apart
by spelling, since "Mental Health Minimum Data Set" and "Mental Health
Services Data Set" are 79% alike and are different datasets.

Decisions are written to `data/dataset-aliases.json`, which `extract` applies
when grouping datasets into pages.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import aliases
from . import compare
from . import orgcheck
from . import sources

ROOT = Path(__file__).resolve().parent.parent
PATH = aliases.DATASET_ALIASES_PATH


def datasets_in_workbook(path: Path) -> dict[str, set[str]]:
    """`{reference: dataset names}` from the Datasets sheet alone."""
    import openpyxl

    from .extract import _read_sheet, clean

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        found: dict[str, set[str]] = {}
        for row in _read_sheet(workbook, "Datasets"):
            reference = clean(row.get("Reference Number"))
            name = clean(row.get("Dataset"))
            if reference and name:
                found.setdefault(reference, set()).add(name)
        return found
    finally:
        workbook.close()


def gather(paths: list[Path]) -> list[orgcheck.Candidate]:
    """Rename candidates across every consecutive pair of editions."""
    ordered = sorted(paths, key=lambda p: sources.edition_sort_key(sources.parse_edition(p.stem)))
    tally: dict[tuple[str, str], dict] = {}
    previous = None
    for path in ordered:
        edition = sources.parse_edition(path.stem)
        print(f"  reading {path.name} …", flush=True)
        current = datasets_in_workbook(path)
        if previous is not None:
            for rename in compare.membership_renames(previous, current):
                entry = tally.setdefault(
                    (rename["was"], rename["now"]),
                    {
                        "versions": 0,
                        "editions": set(),
                        "overlap": rename["overlap"],
                        "now_label": rename["now"],
                    },
                )
                entry["versions"] += rename["versions"]
                entry["editions"].add(edition)
        previous = current

    candidates = []
    for (was, now), entry in sorted(tally.items(), key=lambda kv: -kv[1]["versions"]):
        when = ", ".join(
            sources.edition_label(e) for e in sorted(entry["editions"], key=sources.edition_sort_key)
        )
        candidates.append(
            orgcheck.Candidate(
                "rename",
                f"renamed in {when}, on {entry['versions']:,} agreement version"
                f"{'s' if entry['versions'] != 1 else ''}"
                f" (agreement lists {entry['overlap']:.0%} the same)",
                [was, now],
                canonical=now,
                # A dataset that disappeared while another appeared on every
                # one of its agreements is the same dataset relabelled. Below
                # total overlap something else is going on, so a person looks.
                evidence=(
                    f"renamed in {when}: absent from the register afterwards, and "
                    f"{entry['now_label']} appeared on the same "
                    f"{entry['versions']:,} agreement versions"
                    if entry["overlap"] >= 1.0
                    else None
                ),
            )
        )
    return candidates


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--review", action="store_true", help="decide candidates one at a time")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="apply the unambiguous ones without asking (acronym, punctuation, legal form)",
    )
    parser.add_argument("workbooks", nargs="*", type=Path, help="default: data/raw/*.xlsx")
    args = parser.parse_args(argv)

    workbooks = args.workbooks or sorted((ROOT / "data" / "raw").glob("*.xlsx"))
    if not workbooks:
        raise SystemExit(
            "no workbooks to compare. Put the published .xlsx files in data/raw/ "
            "or name them on the command line; see docs/manual-updates.md."
        )
    print(f"scanning {len(workbooks)} workbook(s) for dataset renames")
    candidates = orgcheck.outstanding(gather(workbooks), path=PATH)
    print()

    if args.auto:
        applied = aliases.auto_merge(
            [(*c.names, c.evidence) for c in candidates], path=PATH
        )
        for entry in applied:
            print(f"  merged  {entry['variant']!r}\n       ->  {entry['canonical']!r}  ({entry['reason']})")
        print(f"\n{len(applied)} merged automatically; {len(candidates) - len(applied)} left for review.")
        candidates = orgcheck.outstanding(candidates, path=PATH)

    counts: dict[str, int] = {}
    if args.review:
        orgcheck.review_mode(candidates, counts, path=PATH)
    elif not args.auto:
        for c in candidates:
            was, now = c.names
            print(f"  {was!r}\n    -> {now!r}  ({c.label})\n")
        print(f"{len(candidates)} outstanding. --review to decide, --auto for the clear ones.")


if __name__ == "__main__":
    main()
