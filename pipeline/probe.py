"""Compare two editions field by field, without changing anything.

    python -m pipeline.probe data/raw/datausesregister_february2026.xlsx \
                             data/raw/datausesregister_march2026.xlsx

A diagnostic, not part of the build. `snapshot.diff` can only say that an
agreement version changed; this says *which fields* changed, and answers the
two questions docs/plan-version-diffs.md leaves open:

1. How much of the amendment volume is cosmetic? A large share of the 122
   amendments in March 2026 may be whitespace, quote-character or case churn
   rather than substance. Every field is compared twice — as published, and
   after normalisation — so the two counts can be read side by side.
2. Who the data controllers became. Where a list-shaped field changed,
   the departures and arrivals are tallied across the whole edition, so a
   hundred agreements renamed from one organisation to another collapse into
   a single row and genuine one-off transfers stand apart from it. This is
   the question digests cannot answer at all: they say a controller changed,
   never from whom to whom.
3. How much is the current fingerprint missing? `snapshot.FINGERPRINTED` omits
   data controllers entirely and hashes only dataset *names*, so a change of
   controller or of a dataset's legal basis registers as no change at all.
   Those fields are compared too, and reported separately.

Either argument may be a published workbook or a committed extract
(`data/editions/<register>/<edition>.json.gz`), which is much faster to load
where one exists. Order does not matter; editions are sorted oldest first.

Two workbooks is roughly 800 MB of memory — one extract is ~390 MB.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from . import compare
from . import snapshot as snapshot_module
from . import sources

# Compared, normalised and redlined exactly as the agreement pages do it, so
# the two answers are comparable. See pipeline/compare.py.
PROSE = tuple(key for key, _ in compare.PROSE_FIELDS)
normalise = compare.normalise

# Proposed additions to snapshot.FINGERPRINTED, compared here so the cost of
# leaving them out can be counted rather than guessed at. See the plan, §3.
DATASET_ATTRIBUTES = ("name", "legal_basis", "sensitivity", "type_of_data", "confidentiality")

# List-shaped fields, where the useful question is what joined and what left.
MEMBERSHIP = ("controllers", "dataset_names")
FIELD_TITLES = {"controllers": "Data controller changes", "dataset_names": "Dataset changes"}


def comparable(version: dict) -> dict[str, object]:
    """Every field this probe compares, fingerprinted or not."""
    fields: dict[str, object] = {key: version.get(key, "") or "" for key in snapshot_module.FINGERPRINTED}
    # What the fingerprint sees of the datasets today: names alone.
    fields["dataset_names"] = sorted(d["name"] for d in version["datasets"])
    # What it does not see.
    fields["controllers"] = sorted(version.get("controllers", []))
    fields["dataset_attributes"] = sorted(
        tuple(d.get(k, "") for k in DATASET_ATTRIBUTES) for d in version["datasets"]
    )
    return fields


FINGERPRINTED_KEYS = set(snapshot_module.FINGERPRINTED) | {"dataset_names"}
PROPOSED_KEYS = {"controllers", "dataset_attributes"}


def _normalise_value(value: object) -> object:
    if isinstance(value, str):
        return normalise(value)
    if isinstance(value, list):
        return [_normalise_value(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_normalise_value(v) for v in value)
    return value


def changed_fields(before: dict, after: dict) -> tuple[set[str], set[str]]:
    """`(differ as published, differ after normalisation)`."""
    raw, normalised = set(), set()
    for key, new in after.items():
        old = before[key]
        if old == new:
            continue
        raw.add(key)
        if _normalise_value(old) != _normalise_value(new):
            normalised.add(key)
    return raw, normalised


def is_extract(path: Path) -> bool:
    return path.suffix == ".gz" or path.suffix == ".json"


def edition_of(path: Path) -> str:
    """The edition a path names, whether it is a workbook or an extract.

    Workbooks keep their published filename (`datausesregister_july2026.xlsx`),
    which `sources.parse_edition` reads. A committed extract is named for the
    edition alone (`july2026.json.gz`), which it does not — so fall back to the
    bare stem. `edition_sort_key` returns `(0, 0)` rather than raising on input
    it cannot read, so check the result: a mistyped filename must fail here,
    not sort silently to the beginning of time.
    """
    stem = path.name.split(".")[0]
    try:
        return sources.parse_edition(stem)
    except ValueError:
        if sources.edition_sort_key(stem) == (0, 0):
            raise SystemExit(
                f"cannot read an edition from {path.name!r}; expected a published "
                "workbook name (datausesregister_july2026.xlsx) or an extract "
                "named for its edition (july2026.json.gz)"
            ) from None
        return stem.lower()


def load(path: Path) -> tuple[str, dict[str, dict]]:
    """`(edition, {reference: version})` from a workbook or a committed extract."""
    if is_extract(path):
        import gzip
        import json

        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as handle:
            payload = json.load(handle)
        # An extract records its own edition; prefer it over the filename.
        edition = payload.get("edition") or edition_of(path)
        agreements = payload["agreements"]
    else:
        from .extract import extract

        edition = edition_of(path)
        agreements = extract(path.read_bytes())["agreements"]
    versions = {v["reference"]: v for a in agreements for v in a["versions"]}
    return edition, versions


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("editions", nargs=2, type=Path, help="two workbooks or committed extracts")
    parser.add_argument("--show", type=int, default=0, metavar="N", help="print N sample redlines")
    parser.add_argument(
        "--field", action="append", help="restrict --show to these fields (repeatable)"
    )
    parser.add_argument(
        "--transitions",
        type=int,
        default=10,
        metavar="N",
        help="how many distinct controller/dataset changes to list (default 10)",
    )
    args = parser.parse_args(argv)

    unknown = sorted(set(args.field or ()) - set(PROSE))
    if unknown:
        raise SystemExit(
            f"--field takes the long free-text fields only; {', '.join(unknown)} "
            f"{'is' if len(unknown) == 1 else 'are'} not among {', '.join(PROSE)}"
        )

    missing = [p for p in args.editions if not p.is_file()]
    if missing:
        raise SystemExit("not found: " + ", ".join(str(p) for p in missing))

    paths = sorted(args.editions, key=lambda p: sources.edition_sort_key(edition_of(p)))
    (old_edition, old_versions), (new_edition, new_versions) = (load(p) for p in paths)
    if old_edition == new_edition:
        raise SystemExit(f"both files are the {old_edition} edition")
    print(f"{old_edition} ({len(old_versions):,} versions) -> {new_edition} ({len(new_versions):,} versions)\n")

    shared = old_versions.keys() & new_versions.keys()
    print(f"added     {len(new_versions.keys() - old_versions.keys()):5,}")
    print(f"removed   {len(old_versions.keys() - new_versions.keys()):5,}")
    print(f"in both   {len(shared):5,}\n")

    raw_tally, normalised_tally = Counter(), Counter()
    transitions: dict[str, Counter] = {field: Counter() for field in MEMBERSHIP}
    visible_now, cosmetic_only, invisible_now = [], [], []
    samples: list[tuple[int, str, str, str, str]] = []

    for reference in shared:
        before, after = comparable(old_versions[reference]), comparable(new_versions[reference])
        raw, normalised = changed_fields(before, after)
        if not raw:
            continue
        raw_tally.update(raw)
        normalised_tally.update(normalised)

        # Mirror what snapshot.diff would report today, exactly.
        seen_today = bool(raw & FINGERPRINTED_KEYS)
        substantive_today = bool(normalised & FINGERPRINTED_KEYS)
        if seen_today and substantive_today:
            visible_now.append(reference)
        elif seen_today:
            cosmetic_only.append(reference)
        if not seen_today and (normalised & PROPOSED_KEYS):
            invisible_now.append(reference)

        # Who went, who arrived. A digest can say the controllers changed; only
        # the values say whether one organisation was renamed across a hundred
        # agreements or a hundred agreements changed hands.
        for field in normalised & set(MEMBERSHIP):
            was, now = set(before[field]), set(after[field])
            transitions[field][(tuple(sorted(was - now)), tuple(sorted(now - was)))] += 1

        for field in normalised & set(PROSE):
            if args.field and field not in args.field:
                continue
            old_text, new_text = old_versions[reference][field], new_versions[reference][field]
            samples.append((abs(len(new_text) - len(old_text)), reference, field, old_text, new_text))

    amended_now = len(visible_now) + len(cosmetic_only)
    print("As snapshot.diff reports it today")
    print(f"  amended                       {amended_now:5,}")
    print("Of those")
    print(f"  substantive after normalising {len(visible_now):5,}")
    print(f"  cosmetic only                 {len(cosmetic_only):5,}"
          + (f"  ({len(cosmetic_only) / amended_now:.0%} of the amendments)" if amended_now else ""))
    print("\nChanges the current fingerprint cannot see")
    print(f"  controllers or dataset attributes only {len(invisible_now):5,}\n")

    if raw_tally:
        width = max(len(f) for f in raw_tally)
        print(f"{'field':<{width}}  {'as published':>12}  {'normalised':>10}  fingerprinted")
        for field, count in raw_tally.most_common():
            flag = "yes" if field in FINGERPRINTED_KEYS else "NO — proposed"
            print(f"{field:<{width}}  {count:>12,}  {normalised_tally[field]:>10,}  {flag}")

    for field in MEMBERSHIP:
        tally = transitions[field]
        if not tally:
            continue
        label = FIELD_TITLES[field]
        total = sum(tally.values())
        shown = tally.most_common(args.transitions)
        print(f"\n{label} — {total:,} version{'s' if total != 1 else ''} changed, "
              f"{len(tally):,} distinct change{'s' if len(tally) != 1 else ''}")
        for (went, arrived), count in shown:
            print(f"  {count:>5,} ×")
            for name in went:
                print(f"           − {name}")
            for name in arrived:
                print(f"           + {name}")
        if len(tally) > len(shown):
            rest = total - sum(c for _, c in shown)
            print(f"  {rest:>5,} ×  across {len(tally) - len(shown):,} further distinct changes "
                  f"(--transitions {len(tally)} to list them)")

    if args.show and not samples:
        # Samples are drawn from substantive prose changes only, so "nothing to
        # show" is a result, not a bug — say which of the two reasons it is.
        scope = f" in {', '.join(args.field)}" if args.field else ""
        print(f"\nNo substantive prose changes to show{scope}.")
    if args.show and samples:
        samples.sort(reverse=True)
        print(f"\n{'=' * 72}\nSample redlines ([-removed-] {{+added+}})")
        for _, reference, field, old_text, new_text in samples[: args.show]:
            print(f"\n{reference} — {field}\n{'-' * 72}")
            print(compare.redline(old_text, new_text))


if __name__ == "__main__":
    main()
