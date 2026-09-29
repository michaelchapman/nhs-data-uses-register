"""The word index behind the agreements search.

An agreement's subject is in its purpose text — the objective, activities,
expected outputs and benefits — which runs to a median of 21,000 characters.
That is far too much to put in the page, so it is indexed here instead: one
JSON file per first character of a word, mapping each word to the agreements
whose latest version uses it. The page fetches only the files a search needs.
See docs/plan.md, "Searching the purpose text".

The index matches words, not substrings: across this much text, "ai" as a
substring is in almost every agreement ("maintain", "detail"). How a search
term is matched against the words (whole word or start of a word) is decided
in assets/filter.js; this module decides what the words are.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import sources
from .names import display_name
from .references import slugify

# The text a search looks through: what the agreements table already searched,
# plus the latest version's purpose text. Only the latest version, since that is
# what the agreement's page shows; a match in superseded text couldn't be seen.
PROSE_FIELDS = ("objective", "activities", "expected_output", "expected_benefits", "yielded_benefits")

APOSTROPHES = re.compile(r"['’]")
WORD = re.compile(r"[a-z0-9]+")
# An acronym's plural as the register writes it: capitals, then a lower-case s.
ACRONYM_PLURAL = re.compile(r"\b([A-Z][A-Z0-9]*[A-Z])s\b")
ACRONYM = re.compile(r"\b([A-Z][A-Z0-9]*[A-Z])\b")

# A word in more than this share of agreements is stored as a bitset, which is
# smaller than a list of that many agreement numbers.
DENSE = 1 / 12


def words(text: str) -> set[str]:
    """The distinct words in `text`, as the search box splits a query.

    Apostrophes are dropped rather than split on, so "King's" is "kings".
    filter.js splits a search term the same way.
    """
    return set(WORD.findall(APOSTROPHES.sub("", text).lower()))


def agreement_text(agreement: dict) -> str:
    latest = agreement["latest"]
    return " ".join(
        [agreement["title"], agreement["base_reference"], agreement["organisation"], *agreement["dataset_names"]]
        + [latest.get(field) or "" for field in PROSE_FIELDS]
    )


def build_index(agreements: list[dict]) -> dict[str, dict[str, str]]:
    """`{first character: {word: postings}}` for `agreements`, in list order.

    An agreement is numbered by its position in `agreements`, which is the
    order the agreements table is rendered in; each row carries its number.

    Short search terms match whole words, so "GP" would miss "GPs". Letting
    any short word also match itself plus "s" would have "ha" find "has", so
    only acronyms are matched in the plural, judged from how each agreement's
    own text writes the word: "GPs" also indexes as "gp", and "GP" in capitals
    also as "gps" (once any agreement writes "GPs"). Judged per agreement, not
    by spelling, because the register has both "MRIs" (scans) and "MRIS" (a
    service), which look the same once lower-cased.
    """
    texts = [APOSTROPHES.sub("", agreement_text(a)) for a in agreements]
    acronyms = {m.group(1).lower() for text in texts for m in ACRONYM_PLURAL.finditer(text)}

    postings: dict[str, list[int]] = {}
    for number, text in enumerate(texts):
        found = words(text)
        found |= {m.group(1).lower() for m in ACRONYM_PLURAL.finditer(text)}
        found |= {m.group(1).lower() + "s" for m in ACRONYM.finditer(text) if m.group(1).lower() in acronyms}
        for word in found:
            postings.setdefault(word, []).append(number)

    shards: dict[str, dict[str, str]] = {}
    for word in sorted(postings):
        shards.setdefault(word[0], {})[word] = encode(postings[word], len(agreements))
    return shards


def encode(numbers: list[int], total: int) -> str:
    """Agreement numbers, ascending, as compact text.

    Sparse: the gaps between numbers in hexadecimal, comma-separated ("3,1,a"
    is 2, 3, 13). Dense: "x" and a bitset in hexadecimal, bit n for agreement n;
    "x" because it is not a hexadecimal digit, as a first gap of 11 ("b") is.
    """
    if len(numbers) > total * DENSE:
        bits = 0
        for number in numbers:
            bits |= 1 << number
        return "x" + format(bits, "x")
    gaps, previous = [], -1
    for number in numbers:
        gaps.append(format(number - previous, "x"))
        previous = number
    return ",".join(gaps)


def decode(postings: str) -> list[int]:
    """The inverse of `encode`, as filter.js reads it."""
    if postings.startswith("x"):
        bits = int(postings[1:], 16)
        return [n for n in range(bits.bit_length()) if bits >> n & 1]
    numbers, previous = [], -1
    for gap in postings.split(","):
        previous += int(gap, 16)
        numbers.append(previous)
    return numbers


def write_index(agreements: list[dict], directory: Path) -> int:
    """Write one file per first character into `directory`; returns the count.

    `directory` is named for the edition, so a browser holding one edition's
    files never uses them to search another.
    """
    directory.mkdir(parents=True, exist_ok=True)
    shards = build_index(agreements)
    for key, entries in shards.items():
        (directory / f"{key}.json").write_text(
            json.dumps({"agreements": len(agreements), "words": entries}, separators=(",", ":")),
            encoding="utf-8",
        )
    return len(shards)


def names(organisations: list[dict], datasets: list[dict], dataset_groups: list[dict]) -> dict:
    """The organisation and dataset names a search is also matched against.

    Each entry is `[name, slug, agreements, other names, controller of, last listed]`,
    busiest first. Other names are the spellings merged onto the page, so
    "Addenbrooke's Hospital" finds Cambridge University Hospitals. `agreements`
    counts those the organisation applied for; `controller of` those naming it
    only as a data controller, which is all some organisations have. `last
    listed` is, for a page no longer in the register, the last edition that
    named it ("January 2023"), and empty otherwise; such a page's agreements
    are not counted, and it comes last.
    """
    def entries(pages: list[dict], others) -> list[list]:
        rows = []
        for page in pages:
            name = display_name(page["name"])
            other = sorted({display_name(n) for n in others(page)} - {name}, key=str.lower)
            gone = page.get("archived")
            rows.append([
                name, page["slug"], 0 if gone else page["agreement_count"], other,
                0 if gone else len(page.get("controller_agreements") or []),
                sources.edition_label(gone["last_edition"]) if gone else "",
            ])
        return sorted(rows, key=lambda row: (bool(row[5]), -row[2], -row[4], row[0].lower()))

    # By page address: a dataset page is titled with the register's current
    # spelling, which need not be the alias file's canonical.
    variants: dict[str, list[str]] = {}
    for group in dataset_groups:
        variants.setdefault(slugify(group["canonical"]), []).extend(group.get("variants", []))
    return {
        "organisations": entries(organisations, lambda o: o.get("known_as") or []),
        "datasets": entries(datasets, lambda d: [*variants.get(d["slug"], []), *d.get("known_as", [])]),
    }


def write_names(organisations: list[dict], datasets: list[dict], dataset_groups: list[dict], directory: Path) -> None:
    """Write `names.json` beside the word index. No word starts with "names"
    as a file name, since the word files are named by one character."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "names.json").write_text(
        json.dumps(names(organisations, datasets, dataset_groups), separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
