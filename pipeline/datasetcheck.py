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

Every edition is read from the committed facts store, so this needs none of
the workbooks and takes seconds. Decisions are written to
`data/dataset-aliases.json`, which the build applies when grouping datasets
into pages. A rename joins the group of the name it replaced, keeping that
page's address; the page is titled with whichever name the register uses now.
"""

from __future__ import annotations

import argparse

from . import aliases, compare, facts, orgcheck, sources

PATH = aliases.DATASET_ALIASES_PATH


def gather(by_edition: dict[str, dict[str, set[str]]]) -> list[orgcheck.Candidate]:
    """Rename candidates across every consecutive pair of editions.

    `by_edition` is `{edition: {version reference: dataset names}}`, as
    `facts.dataset_names_by_edition` reads it.
    """
    tally: dict[tuple[str, str], dict] = {}
    previous = None
    for edition in sorted(by_edition, key=sources.edition_sort_key):
        current = by_edition[edition]
        if previous is not None:
            for rename in compare.membership_renames(previous, current):
                entry = tally.setdefault(
                    (rename["was"], rename["now"]),
                    {"versions": 0, "editions": set(), "overlap": rename["overlap"]},
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
                # The name replaced: its page already exists, and merging onto
                # it keeps that page's address.
                canonical=was,
                # A dataset that disappeared while another appeared on every
                # one of its agreements is the same dataset relabelled. Below
                # total overlap something else is going on, so a person looks.
                evidence=(
                    f"renamed in {when}: absent from the register afterwards, and "
                    f"{now} appeared on the same "
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
        help="merge the renames whose agreement lists match exactly, without asking",
    )
    parser.add_argument("--register", default="data-uses-register", help="register slug to check")
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="print each candidate as a GitHub Actions warning and change nothing (CI runs this)",
    )
    args = parser.parse_args(argv)

    by_edition = facts.dataset_names_by_edition(args.register)
    if len(by_edition) < 2:
        raise SystemExit(
            f"the facts store holds {len(by_edition)} edition(s) of {args.register}; "
            "a rename shows only between two. See docs/manual-updates.md."
        )
    print(f"comparing {len(by_edition)} editions for dataset renames")
    candidates = orgcheck.outstanding(gather(by_edition), path=PATH)
    print()

    if args.advisory:
        for c in candidates:
            was, now = c.names
            print(
                f"::warning file={PATH.relative_to(PATH.parent.parent)},title=datasetcheck::"
                f"{was!r} -> {now!r} looks like a rename ({c.label}). "
                "Run python -m pipeline.datasetcheck --review."
            )
        print(f"{len(candidates)} outstanding.")
        return

    if args.auto:
        applied = [c for c in candidates if c.evidence]
        for c in applied:
            was, now = c.names
            aliases.add_alias(was, [was, now], c.evidence or "", path=PATH, source="auto")
            print(f"  merged  {now!r}\n    onto  {aliases.resolve(was, aliases.load_map(PATH))!r}  ({c.evidence})")
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
