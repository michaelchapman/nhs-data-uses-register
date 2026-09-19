"""Compare two agreement versions, field by field.

The register lists every renewal of an agreement as its own row, repeating all
of the free text whether or not a word of it moved. An agreement with eight
versions therefore carries eight copies of a 3,000-word objective, and a reader
wanting to know what the renewal actually changed has to read both and spot the
difference. Everything needed to answer that is already in one edition's
extract, so this module answers it: which fields differ between two versions,
and — for the long free-text fields — where.

Used two ways. `build` renders a version-to-version diff on each agreement
page. `probe` uses the same tokenising and normalisation to compare the *same*
version across two editions, which is the other half of the problem and needs
the stored history proposed in docs/plan-version-diffs.md before the site can
show it.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter

# Long free-text fields, where a word-level redline is worth reading.
PROSE_FIELDS = (
    ("objective", "Objective for processing"),
    ("activities", "Processing activities"),
    ("expected_output", "Expected output"),
    ("expected_benefits", "Expected measurable benefits"),
    ("yielded_benefits", "Benefits reported"),
)

# Short fields, where a before/after pair reads better than a redline.
SCALAR_FIELDS = (
    ("title", "Title"),
    ("organisation", "Applicant organisation"),
    ("organisation_type", "Organisation type"),
    ("controller_basis", "Data controller basis"),
    ("start_date", "Start date"),
    ("end_date", "End date"),
    ("sublicensing", "Sublicensing"),
    ("commercial", "Commercial purposes"),
)

QUOTES = str.maketrans(
    {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
)
# Most non-ASCII text in the register is non-ASCII for some other reason — a
# pound sign, an accent, a maths symbol — and `translate` allocates a new
# string whether or not it has anything to change. Searching first is cheaper.
SMART_PUNCTUATION = re.compile("[‘’“”–—]")


def normalise(text: str) -> str:
    """Fold away differences that are typography rather than substance.

    For comparison only — never for display. The register's free text picks up
    smart quotes, non-breaking spaces, doubled spaces and changes of case
    between editions without the meaning moving, and an amendment count that
    includes those is not measuring anything a reader cares about.

    One definition, used everywhere: `build` decides from it whether a field
    really changed between two versions, and `probe` decides from it whether
    an edition's amendments are substantive. Two definitions that disagreed
    would make those two answers incomparable.
    """
    if not text:
        return ""
    # Every key in QUOTES is non-ASCII and NFKC is the identity on ASCII, so
    # plain ASCII text — most of the register — can skip both, and casefold is
    # just lower. They are the most expensive operations in the comparison.
    if text.isascii():
        return " ".join(text.split()).lower()
    text = unicodedata.normalize("NFKC", text)
    if SMART_PUNCTUATION.search(text):
        text = text.translate(QUOTES)
    # Equivalent to collapsing runs of whitespace and stripping, several times
    # faster than the regex it replaces.
    return " ".join(text.split()).casefold()


def _tokens(text: str) -> list[str]:
    return (text or "").split()


def _paragraphs(text: str) -> list[str]:
    """The register's free text, split the way the page renders it."""
    return [block.strip() for block in (text or "").split("\n") if block.strip()]


def word_runs(before: str, after: str, context: int = 12) -> list[dict]:
    """Word-level diff of one paragraph as `{op, text}` runs, ready to render.

    `op` is `equal`, `insert`, `delete` or `elided`; an `elided` run carries the
    number of unchanged words dropped from the middle of a long stretch.
    """
    old_words, new_words = _tokens(before), _tokens(after)
    matcher = difflib.SequenceMatcher(None, old_words, new_words, autojunk=False)
    out: list[dict] = []

    def emit(op: str, text: str) -> None:
        if not text:
            return
        # Adjacent runs of the same kind happen around an elision; join them so
        # the markup doesn't fragment into neighbouring <ins> elements.
        if out and out[-1]["op"] == op:
            out[-1]["text"] += " " + text
        else:
            out.append({"op": op, "text": text})

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            words = old_words[i1:i2]
            if len(words) > 2 * context + 4:
                emit("equal", " ".join(words[:context]))
                out.append({"op": "elided", "words": len(words) - 2 * context})
                emit("equal", " ".join(words[-context:]))
            else:
                emit("equal", " ".join(words))
            continue
        if tag in ("replace", "delete"):
            emit("delete", " ".join(old_words[i1:i2]))
        if tag in ("replace", "insert"):
            emit("insert", " ".join(new_words[j1:j2]))
    return out


# Below this word-overlap ratio two paragraphs are treated as unrelated rather
# than diffed. A wholesale rewrite word-diffed against its predecessor renders
# as interleaved fragments that read worse than the two paragraphs side by
# side, and the matcher spends most of its time on exactly those pairs.
REWRITE_THRESHOLD = 0.4


def _too_different(before: str, after: str) -> bool:
    """Cheap upper bound on similarity: shared words over total words.

    This is what `SequenceMatcher.quick_ratio` computes, done directly on
    counts. Going through the class would build its full index first, which is
    the very cost this guard exists to avoid — and the bound is never an
    underestimate, so a pair rejected here could not have scored higher.
    """
    old_words, new_words = Counter(_tokens(before)), Counter(_tokens(after))
    total = sum(old_words.values()) + sum(new_words.values())
    if not total:
        return False
    shared = sum((old_words & new_words).values())
    return 2.0 * shared / total < REWRITE_THRESHOLD


def diff_blocks(before: str, after: str) -> list[dict]:
    """Diff two free-text fields, paragraph by paragraph then word by word.

    Diffing thousands of words in one pass is both slow and unreadable: a
    renewal usually rewrites one paragraph and leaves twenty untouched, and a
    word-level matcher over the whole field will happily align stray words
    across unrelated paragraphs to make the edit script shorter. Matching
    paragraphs first keeps each word-level diff inside the paragraph it belongs
    to, drops the untouched ones to a count, and cuts the work to the part that
    actually changed.

    Paragraphs are matched on their normalised form, so one that differs only
    in typography counts as unchanged here as it does everywhere else.

    Blocks are `{op: equal, paragraphs: n}`, `{op: changed, runs: [...]}`,
    or `{op: insert|delete, text: ...}` for a paragraph added or dropped whole.
    """
    old_paragraphs, new_paragraphs = _paragraphs(before), _paragraphs(after)
    matcher = difflib.SequenceMatcher(
        None,
        [normalise(p) for p in old_paragraphs],
        [normalise(p) for p in new_paragraphs],
        autojunk=False,
    )
    blocks: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            if blocks and blocks[-1]["op"] == "equal":
                blocks[-1]["paragraphs"] += i2 - i1
            else:
                blocks.append({"op": "equal", "paragraphs": i2 - i1})
            continue
        if tag == "replace":
            # Pair rewritten paragraphs positionally and diff each pair; any
            # surplus on either side is a paragraph added or removed outright.
            for old, new in zip(old_paragraphs[i1:i2], new_paragraphs[j1:j2]):
                if _too_different(old, new):
                    blocks.append({"op": "delete", "text": old})
                    blocks.append({"op": "insert", "text": new})
                else:
                    blocks.append({"op": "changed", "runs": word_runs(old, new)})
            for extra in old_paragraphs[i1 + min(i2 - i1, j2 - j1) : i2]:
                blocks.append({"op": "delete", "text": extra})
            for extra in new_paragraphs[j1 + min(i2 - i1, j2 - j1) : j2]:
                blocks.append({"op": "insert", "text": extra})
            continue
        for extra in old_paragraphs[i1:i2]:
            blocks.append({"op": "delete", "text": extra})
        for extra in new_paragraphs[j1:j2]:
            blocks.append({"op": "insert", "text": extra})
    return blocks


def redline(before: str, after: str, limit: int = 60, max_blocks: int = 10) -> str:
    """The same diff as plain text, for terminal output.

    Capped twice over, because a wholesale rewrite otherwise prints the entire
    new text and scrolls away the summary it was meant to illustrate: `limit`
    truncates any single changed run, and `max_blocks` stops after that many
    changed paragraphs. Neither applies to the HTML rendering, which collapses
    behind a <details> and can afford the length.
    """

    def cap(text: str) -> str:
        words = text.split()
        if len(words) <= limit:
            return text
        return " ".join(words[:limit]) + f" … (+{len(words) - limit:,} more words)"

    parts = []
    blocks = diff_blocks(before, after)
    changed = [b for b in blocks if b["op"] != "equal"]
    if len(changed) > max_blocks:
        cut = changed[max_blocks]
        blocks = blocks[: blocks.index(cut)]
        blocks.append({"op": "truncated", "count": len(changed) - max_blocks})
    for block in blocks:
        if block["op"] == "truncated":
            parts.append(f"[… {block['count']} further changed paragraph(s) not shown …]")
        elif block["op"] == "equal":
            parts.append(f"[… {block['paragraphs']} paragraph(s) unchanged …]")
        elif block["op"] == "insert":
            parts.append("{+" + cap(block["text"]) + "+}")
        elif block["op"] == "delete":
            parts.append("[-" + cap(block["text"]) + "-]")
        else:
            for run in block["runs"]:
                if run["op"] == "elided":
                    parts.append(f"[… {run['words']:,} words …]")
                elif run["op"] == "equal":
                    parts.append(run["text"])
                elif run["op"] == "insert":
                    parts.append("{+" + cap(run["text"]) + "+}")
                else:
                    parts.append("[-" + cap(run["text"]) + "-]")
    return " ".join(parts)


def _dataset_names(version: dict) -> set[str]:
    return {d["name"] for d in version["datasets"] if d["name"]}


def compare_versions(before: dict, after: dict) -> dict | None:
    """What changed between two versions of one agreement. `None` if nothing did.

    Two fields are reported that `snapshot.FINGERPRINTED` leaves out — the data
    controllers, and which datasets are named — because both are changes a
    reader would want flagged and neither is visible anywhere else on the page.
    """
    scalars, lists, prose, unchanged, cosmetic = [], [], [], [], []

    for key, label in SCALAR_FIELDS:
        old, new = before.get(key, "") or "", after.get(key, "") or ""
        if old == new:
            continue
        if normalise(old) == normalise(new):
            cosmetic.append(label)
            continue
        scalars.append({"label": label, "before": old, "after": new})

    for key, label in (("controllers", "Data controllers"),):
        old, new = set(before.get(key) or []), set(after.get(key) or [])
        if old != new:
            lists.append({"label": label, "added": sorted(new - old), "removed": sorted(old - new)})
    old_datasets, new_datasets = _dataset_names(before), _dataset_names(after)
    if old_datasets != new_datasets:
        lists.append(
            {
                "label": "Datasets",
                "added": sorted(new_datasets - old_datasets),
                "removed": sorted(old_datasets - new_datasets),
            }
        )

    for key, label in PROSE_FIELDS:
        old, new = before.get(key, "") or "", after.get(key, "") or ""
        if old == new:
            if old:
                unchanged.append(label)
            continue
        if normalise(old) == normalise(new):
            cosmetic.append(label)
            continue
        if not old or not new:
            # Text added where there was none, or removed entirely. A redline of
            # one side against nothing is just the text, so say which it is.
            prose.append({"label": label, "filled_in": bool(new), "blocks": None, "text": new or old})
            continue
        prose.append({"label": label, "filled_in": None, "blocks": diff_blocks(old, new), "text": ""})

    if not (scalars or lists or prose or cosmetic):
        return None
    return {
        "scalars": scalars,
        "lists": lists,
        "prose": prose,
        "unchanged": unchanged,
        "cosmetic": sorted(set(cosmetic)),
    }
