"""Find organisation names that might be the same real organisation.

    python -m pipeline.orgcheck            # list candidates
    python -m pipeline.orgcheck --review   # go through them one at a time

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

from . import aliases
from . import editions as editions_module
from . import sources

DROP_TOKENS = {"THE", "LIMITED", "LTD", "LLC", "LLP", "PLC", "AND", "&", "CO", "OF"}
CODE_RE = re.compile(r"-\s*([A-Z0-9]{2,6})$")
SIMILARITY_THRESHOLD = 0.55


def normalize(name: str) -> str:
    n = name.upper().translate(str.maketrans("’‘“”–—", "''\"\"--"))
    n = re.sub(r"[.,'\"]", "", n)
    n = re.sub(r"[-/()]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def token_set(name: str) -> frozenset:
    return frozenset(t for t in normalize(name).split() if t not in DROP_TOKENS)


@dataclass
class Candidate:
    kind: str  # "code" or "similarity"
    label: str  # why it was flagged, for display
    names: list[str]


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


def outstanding(candidates: list[Candidate]) -> list[Candidate]:
    alias_map = aliases.load_map()
    ignored = aliases.load_ignored()
    return [
        c
        for c in candidates
        if not already_resolved(c.names, alias_map) and not aliases.is_ignored(c.names, ignored)
    ]


def gather(names: list[str]) -> list[Candidate]:
    return same_reference_code(names) + weighted_similarity(names)


def list_mode(candidates: list[Candidate], counts: dict[str, int]) -> None:
    code = [c for c in candidates if c.kind == "code"]
    similarity = [c for c in candidates if c.kind == "similarity"]

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

    if code or similarity:
        print(f"\n{len(code) + len(similarity)} outstanding. Run with --review to go through them.")


def prompt(text: str) -> str:
    try:
        return input(text)
    except EOFError:
        return "q"


def review_one(c: Candidate, counts: dict[str, int], index: int, total: int) -> str:
    """Returns 'quit' to stop the loop, anything else to continue."""
    print(f"\n[{index}/{total}] {c.label}")
    for i, n in enumerate(c.names, start=1):
        print(f"  {i}) {n}  ({counts.get(n, 0)} agreements)")

    choice = prompt("  [m]erge  [i]gnore  [k]skip  [q]uit > ").strip().lower()

    if choice in ("q", "quit"):
        return "quit"

    if choice in ("i", "ignore"):
        aliases.add_ignored(c.names)
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

        for i, n in enumerate(selected, start=1):
            print(f"    {i}) {n}")
        canon_choice = prompt(f"  canonical name — 1-{len(selected)}, or [c]ustom, Enter for 1: ").strip().lower()
        if canon_choice in ("c", "custom"):
            canonical = prompt("  type the canonical name: ").strip()
            if not canonical:
                print("  empty name — nothing done.")
                return "continue"
        elif canon_choice.isdigit() and 1 <= int(canon_choice) <= len(selected):
            canonical = selected[int(canon_choice) - 1]
        else:
            canonical = selected[0]

        reason = prompt("  reason (optional, Enter to skip): ").strip()
        aliases.add_alias(canonical, selected, reason)
        print(f"  merged onto {canonical!r}.")
        return "continue"

    # skip / anything unrecognised
    return "continue"


def review_mode(candidates: list[Candidate], counts: dict[str, int]) -> None:
    if not candidates:
        print("Nothing outstanding — every candidate has been merged or ignored.")
        return
    print(f"{len(candidates)} candidate(s) to review. Decisions save immediately; quit any time.\n")
    for index, c in enumerate(list(candidates), start=1):
        # Re-check as we go: an earlier merge in this same run can resolve a
        # later candidate that shares a name with it.
        if already_resolved(c.names, aliases.load_map()):
            continue
        if review_one(c, counts, index, len(candidates)) == "quit":
            print("\nStopped. Anything already decided is saved; the rest will show up next run.")
            return
    print("\nDone — nothing left outstanding.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--review", action="store_true", help="go through candidates one at a time")
    args = parser.parse_args()

    register = sources.registers()[0]
    edition = editions_module.latest_edition(register.slug)
    if not edition:
        raise SystemExit("nothing ingested — run pipeline.ingest first")
    data = editions_module.read_extract(register.slug, edition)
    names = sorted({o["name"] for o in data["organisations"]})
    counts = {o["name"]: o["agreement_count"] + o.get("controller_agreement_count", 0) for o in data["organisations"]}
    print(f"{edition}: {len(names)} organisation names\n")

    candidates = outstanding(gather(names))
    if args.review:
        review_mode(candidates, counts)
    else:
        list_mode(candidates, counts)


if __name__ == "__main__":
    main()
