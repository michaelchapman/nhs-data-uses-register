"""Find organisation names that might be the same real organisation.

    python -m pipeline.orgcheck

Prints candidates in three groups, roughly most to least certain. Nothing
here is applied automatically — this is the first half of the workflow in
docs/organisation-names.md: read the output, decide, and add anything real to
data/organisation-aliases.json yourself.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

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


def same_reference_code(names: list[str]) -> dict[str, list[str]]:
    """Names sharing a trailing "- CODE" (an ICB reference, typically) are
    about as close to a guaranteed match as free text gets."""
    by_code: dict[str, list[str]] = defaultdict(list)
    for name in names:
        match = CODE_RE.search(name)
        if match:
            by_code[match.group(1)].append(name)
    return {code: sorted(set(group)) for code, group in by_code.items() if len(set(group)) > 1}


def weighted_similarity(names: list[str]) -> list[tuple[float, str, str]]:
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
    pairs = []
    for i, n1 in enumerate(uniq):
        for n2 in uniq[i + 1 :]:
            t1, t2 = toksets[n1], toksets[n2]
            if t1 == t2 or not t1 or not t2:
                continue
            s = score(t1, t2)
            if s >= SIMILARITY_THRESHOLD:
                pairs.append((s, n1, n2))
    return sorted(pairs, reverse=True)


def main() -> None:
    register = sources.registers()[0]
    edition = editions_module.latest_edition(register.slug)
    if not edition:
        raise SystemExit("nothing ingested — run pipeline.ingest first")
    data = editions_module.read_extract(register.slug, edition)
    names = sorted({o["name"] for o in data["organisations"]})
    counts = {o["name"]: o["agreement_count"] + o.get("controller_agreement_count", 0) for o in data["organisations"]}
    print(f"{edition}: {len(names)} organisation names\n")

    print("=== A. Same trailing reference code (e.g. an ICB \"- M1J4Y\") ===")
    print("Different text, same code — about as certain as this gets.\n")
    code_groups = same_reference_code(names)
    for code, group in sorted(code_groups.items()):
        print(f"  code {code}:")
        for n in group:
            print(f"    {n!r}  ({counts[n]} agreements)")
    if not code_groups:
        print("  none")

    print("\n=== B. Weighted name similarity (needs a human to look) ===")
    print("Ranked highest first. Many of these are genuinely different organisations")
    print("that just share common words (two different councils, two different NHS")
    print("trusts) — that's exactly why this group isn't applied automatically.\n")
    for score, n1, n2 in weighted_similarity(names):
        print(f"  {score:.2f}  {n1!r}  ({counts[n1]})  <->  {n2!r}  ({counts[n2]})")


if __name__ == "__main__":
    main()
