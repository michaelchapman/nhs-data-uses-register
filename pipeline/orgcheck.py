"""Find organisation names that might be the same real organisation.

    python -m pipeline.orgcheck             # list candidates
    python -m pipeline.orgcheck --review    # go through them one at a time
    python -m pipeline.orgcheck --renames   # also find renames between editions

`--review` is the easy path from here to data/organisation-aliases.json: it
shows one candidate at a time and asks what to do —

    [m] merge, choosing which name to keep as canonical
    [i] ignore — remembered, so this candidate won't be suggested again
    [k] skip for now — asked again next run
    [q] quit — anything already decided this run is already saved

Nothing is ever applied without you choosing it here. See
docs/organisation-names.md for the full workflow.
"""

from __future__ import annotations

import argparse
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import aliases
from . import facts
from . import sources

DROP_TOKENS = {"THE", "LIMITED", "LTD", "LLC", "LLP", "PLC", "AND", "&", "CO", "OF"}
CODE_RE = re.compile(r"-\s*([A-Z0-9]{2,6})$")
SIMILARITY_THRESHOLD = 0.55
ROOT = Path(__file__).resolve().parent.parent


def normalize(name: str) -> str:
    n = name.upper().translate(str.maketrans("’‘“”–—", "''\"\"--"))
    n = re.sub(r"[.,'\"]", "", n)
    n = re.sub(r"[-/()]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def token_set(name: str) -> frozenset:
    return frozenset(t for t in normalize(name).split() if t not in DROP_TOKENS)


@dataclass
class Candidate:
    kind: str  # "code", "similarity" or "rename"
    label: str  # why it was flagged, for display
    names: list[str]
    # Set when the evidence is strong enough to merge without asking — a name
    # that left the register while another arrived on exactly its agreements.
    evidence: str | None = None
    # For a rename we know which spelling is current, so the review loop can
    # offer it as the canonical name rather than defaulting to the first.
    canonical: str | None = None


def same_reference_code(names: list[str]) -> list[Candidate]:
    """Names sharing a trailing "- CODE" (an ICB reference, typically) are
    about as close to a guaranteed match as free text gets."""
    by_code: dict[str, list[str]] = defaultdict(list)
    for name in names:
        match = CODE_RE.search(name)
        if match:
            by_code[match.group(1)].append(name)
    return [
        Candidate("code", f'same reference code "{code}"', sorted(set(group)))
        for code, group in sorted(by_code.items())
        if len(set(group)) > 1
    ]


def weighted_similarity(names: list[str]) -> list[Candidate]:
    """Token-overlap similarity, weighted so a word most names share (TRUST,
    COUNCIL, NHS, INTEGRATED CARE BOARD...) counts for much less than a word
    almost nothing else has (a place or company name) — a plain character
    diff ratio flags "Barnsley Council" against "Bolton Council" as strongly
    as it flags a real duplicate, which this is built to avoid."""
    toksets = {n: token_set(n) for n in names}
    df: dict[str, int] = defaultdict(int)
    for ts in toksets.values():
        for t in ts:
            df[t] += 1

    def idf(t: str) -> float:
        return 1.0 / math.log(2 + df[t])

    def score(a: frozenset, b: frozenset) -> float:
        union = a | b
        if not union:
            return 0.0
        return sum(idf(t) for t in a & b) / sum(idf(t) for t in union)

    uniq = sorted(set(names))
    scored = []
    for i, n1 in enumerate(uniq):
        for n2 in uniq[i + 1 :]:
            t1, t2 = toksets[n1], toksets[n2]
            if t1 == t2 or not t1 or not t2:
                continue
            s = score(t1, t2)
            if s >= SIMILARITY_THRESHOLD:
                scored.append((s, n1, n2))
    scored.sort(reverse=True)
    return [Candidate("similarity", f"similarity {s:.2f}", [n1, n2]) for s, n1, n2 in scored]


def already_resolved(names: list[str], alias_map: dict[str, str]) -> bool:
    """True once every name in the candidate already lands on the same page —
    it was merged (this run or a previous one) and doesn't need asking again."""
    resolved = {aliases.resolve(n, alias_map) for n in names}
    return len(resolved) == 1


def outstanding(candidates: list[Candidate], path=None) -> list[Candidate]:
    alias_map = aliases.load_map(path)
    ignored = aliases.load_ignored(path)
    return [
        c
        for c in candidates
        if not already_resolved(c.names, alias_map) and not aliases.is_ignored(c.names, ignored)
    ]


def gather(names: list[str]) -> list[Candidate]:
    return same_reference_code(names) + weighted_similarity(names)


def names_in_workbook(path: Path) -> dict[str, tuple[str, frozenset]]:
    """`{reference: (applicant organisation, controllers)}` from one workbook.

    Only the Agreements sheet is read. A full `extract` also parses Datasets
    and the hundred-thousand-row DataReleases sheet, none of which carries an
    organisation name, and doing that nineteen times to find renames would
    take far longer than the question is worth.
    """
    import openpyxl

    from .extract import _read_sheet, clean, split_list

    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        found = {}
        for row in _read_sheet(workbook, "Agreements"):
            reference = clean(row.get("Reference Number"))
            if reference:
                found[reference] = (
                    clean(row.get("Applicant Organisation")),
                    frozenset(split_list(row.get("Data Controller(s)"))),
                )
        return found
    finally:
        workbook.close()


def renames_between(before: dict, after: dict) -> list[tuple[str, str]]:
    """One-for-one name swaps on the same agreement version.

    A rename is invisible to everything else in this module: `orgcheck`
    compares the names in a single edition, and the old spelling of a renamed
    organisation is not in that edition — it is only in the previous one. So
    the evidence for a rename is a version whose organisation or controller
    changed from exactly one name to exactly one other, which is what this
    looks for. Anything less clear-cut (two names leaving, three arriving) is
    a change of controller rather than a change of name, and is left alone.
    """
    swaps = []
    for reference, (organisation, controllers) in after.items():
        if reference not in before:
            continue
        was_organisation, was_controllers = before[reference]
        if was_organisation and organisation and was_organisation != organisation:
            swaps.append((was_organisation, organisation))
        gone, arrived = was_controllers - controllers, controllers - was_controllers
        if len(gone) == 1 and len(arrived) == 1:
            swaps.append((next(iter(gone)), next(iter(arrived))))
    return swaps


def gather_renames(paths: list[Path]) -> list[Candidate]:
    """Rename candidates across every consecutive pair of editions.

    Workbooks are read oldest first and only the previous edition's names are
    held, so the memory cost is two small maps rather than two extracts.
    """
    ordered = sorted(paths, key=lambda p: sources.edition_sort_key(sources.parse_edition(p.stem)))
    tally: dict[tuple[str, str], dict] = {}
    previous = None
    for path in ordered:
        edition = sources.parse_edition(path.stem)
        print(f"  reading {path.name} …", flush=True)
        current = names_in_workbook(path)
        if previous is not None:
            for swap in renames_between(previous, current):
                entry = tally.setdefault(swap, {"count": 0, "editions": set()})
                entry["count"] += 1
                entry["editions"].add(edition)
        previous = current

    candidates = []
    for (was, now), entry in sorted(tally.items(), key=lambda kv: -kv[1]["count"]):
        when = ", ".join(
            sources.edition_label(e)
            for e in sorted(entry["editions"], key=sources.edition_sort_key)
        )
        candidates.append(
            Candidate(
                "rename",
                f"renamed in {when}, on {entry['count']} agreement version"
                f"{'s' if entry['count'] != 1 else ''}",
                [was, now],
                canonical=now,
            )
        )
    return candidates


def list_mode(candidates: list[Candidate], counts: dict[str, int]) -> None:
    code = [c for c in candidates if c.kind == "code"]
    similarity = [c for c in candidates if c.kind == "similarity"]
    renames = [c for c in candidates if c.kind == "rename"]

    if renames:
        print("=== Renames between editions ===")
        print("One name replaced by one other on the same agreement. The old spelling")
        print("is usually absent from the current edition, so nothing else here finds it.\n")
        for c in renames:
            was, now = c.names
            print(f"  {was!r}")
            print(f"    -> {now!r}  ({c.label})\n")

    print('=== A. Same trailing reference code (e.g. an ICB "- M1J4Y") ===')
    print("Different text, same code — about as certain as this gets.\n")
    for c in code:
        print(f"  {c.label}:")
        for n in c.names:
            print(f"    {n!r}  ({counts[n]} agreements)")
    if not code:
        print("  none outstanding")

    print("\n=== B. Weighted name similarity (needs a human to look) ===")
    print("Ranked highest first. Many of these are genuinely different organisations")
    print("that just share common words (two different councils, two different NHS")
    print("trusts) — that's exactly why this group isn't applied automatically.\n")
    for c in similarity:
        n1, n2 = c.names
        print(f"  {c.label}  {n1!r}  ({counts[n1]})  <->  {n2!r}  ({counts[n2]})")
    if not similarity:
        print("  none outstanding")

    total = len(code) + len(similarity) + len(renames)
    if total:
        print(f"\n{total} outstanding. Run with --review to go through them.")


def prompt(text: str) -> str:
    try:
        return input(text)
    except EOFError:
        return "q"


def review_one(c: Candidate, counts: dict[str, int], index: int, total: int, path=None) -> str:
    """Returns 'quit' to stop the loop, anything else to continue."""
    print(f"\n[{index}/{total}] {c.label}")
    for i, n in enumerate(c.names, start=1):
        # A renamed organisation's old spelling is gone from the current
        # edition, so its agreement count is zero — which reads as "this
        # organisation has nothing" rather than "this name is no longer used".
        if n in counts:
            where = f"{counts[n]} agreements"
        else:
            where = "not in the current edition"
        print(f"  {i}) {n}  ({where})")

    choice = prompt("  [m]erge  [i]gnore  [k]skip  [q]uit > ").strip().lower()

    if choice in ("q", "quit"):
        return "quit"

    if choice in ("i", "ignore"):
        aliases.add_ignored(c.names, path=path)
        print("  ignored — won't be suggested again.")
        return "continue"

    if choice in ("m", "merge"):
        if len(c.names) > 2:
            picked = prompt(f"  merge which? comma-separated 1-{len(c.names)}, or Enter for all: ").strip()
            indices = (
                range(1, len(c.names) + 1)
                if not picked
                else [int(p) for p in re.findall(r"\d+", picked)]
            )
            selected = [c.names[i - 1] for i in indices if 1 <= i <= len(c.names)]
        else:
            selected = c.names
        if len(selected) < 2:
            print("  need at least two to merge — nothing done.")
            return "continue"

        # For a rename the current spelling is known, so it is the default;
        # otherwise fall back to the first, as before.
        default_canonical = c.canonical if c.canonical in selected else selected[0]
        for i, n in enumerate(selected, start=1):
            marker = "  <- current" if n == default_canonical and c.canonical else ""
            print(f"    {i}) {n}{marker}")
        canon_choice = prompt(
            f"  canonical name — 1-{len(selected)}, or [c]ustom, "
            f"Enter for {selected.index(default_canonical) + 1}: "
        ).strip().lower()
        if canon_choice in ("c", "custom"):
            canonical = prompt("  type the canonical name: ").strip()
            if not canonical:
                print("  empty name — nothing done.")
                return "continue"
        elif canon_choice.isdigit() and 1 <= int(canon_choice) <= len(selected):
            canonical = selected[int(canon_choice) - 1]
        else:
            canonical = default_canonical

        reason = prompt("  reason (optional, Enter to skip): ").strip()
        aliases.add_alias(canonical, selected, reason, path=path)
        print(f"  merged onto {canonical!r}.")
        return "continue"

    # skip / anything unrecognised
    return "continue"


def review_mode(candidates: list[Candidate], counts: dict[str, int], path=None) -> None:
    if not candidates:
        print("Nothing outstanding — every candidate has been merged or ignored.")
        return
    print(f"{len(candidates)} candidate(s) to review. Decisions save immediately; quit any time.\n")
    for index, c in enumerate(list(candidates), start=1):
        # Re-check as we go: an earlier merge in this same run can resolve a
        # later candidate that shares a name with it.
        if already_resolved(c.names, aliases.load_map(path)):
            continue
        if review_one(c, counts, index, len(candidates), path=path) == "quit":
            print("\nStopped. Anything already decided is saved; the rest will show up next run.")
            return
    print("\nDone — nothing left outstanding.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", action="store_true", help="go through candidates one at a time")
    parser.add_argument(
        "--auto",
        action="store_true",
        help=(
            "apply the unambiguous candidates without asking — a bracketed "
            "acronym, a legal form, or punctuation and case. Anything that adds "
            "or removes a word of substance is still left for review."
        ),
    )
    parser.add_argument(
        "--renames",
        nargs="*",
        type=Path,
        metavar="WORKBOOK",
        help=(
            "also look for renames across editions, reading workbooks "
            "(default: data/raw/*.xlsx). A renamed organisation cannot be found "
            "within one edition, because its old spelling is only in the previous one."
        ),
    )
    args = parser.parse_args()

    register = sources.registers()[0]
    edition = facts.latest_edition(register.slug)
    if not edition:
        raise SystemExit("nothing ingested — run pipeline.ingest first")
    data = facts.read_extract(register.slug, edition)
    names = sorted({o["name"] for o in data["organisations"]})
    counts = {o["name"]: o["agreement_count"] + o.get("controller_agreement_count", 0) for o in data["organisations"]}
    print(f"{edition}: {len(names)} organisation names\n")

    candidates = gather(names)
    if args.renames is not None:
        workbooks = args.renames or sorted((ROOT / "data" / "raw").glob("*.xlsx"))
        if not workbooks:
            raise SystemExit(
                "no workbooks to compare. Put the published .xlsx files in data/raw/ "
                "or name them on the command line; see docs/manual-updates.md."
            )
        print(f"scanning {len(workbooks)} workbook(s) for renames between editions")
        candidates = gather_renames(workbooks) + candidates
        print()
    candidates = outstanding(candidates)

    if args.auto:
        applied = aliases.auto_merge(
            [(*c.names, c.evidence) for c in candidates if len(c.names) == 2]
        )
        for entry in applied:
            print(f"  merged  {entry['variant']!r}")
            print(f"       ->  {entry['canonical']!r}  ({entry['reason']})")
        candidates = outstanding(candidates)
        print(f"\n{len(applied)} merged automatically; {len(candidates)} left for a person.\n")

    if args.review:
        review_mode(candidates, counts)
    elif not args.auto:
        list_mode(candidates, counts)


if __name__ == "__main__":
    main()
