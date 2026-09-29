"""One version of an agreement as the pipeline holds it, and the rules that tidy it.

A version reaches the pipeline two ways: parsed from a workbook (`extract`) or
read back from the facts store (`facts`). What is here is shared by both, so an
edition comes out the same either way: names tidied by `tidy_version`,
controller lists split by `split_list`, and released files summarised per
dataset by `summarise_releases`.
"""

from __future__ import annotations

import datetime as dt
import re

# How the data reached the applicant. The register records one kind of event —
# a file released externally by DARS — and says nothing about access granted in
# NHS England's own systems, such as its Secure Data Environment, or onward
# sharing by the recipient, so this is named for what it holds rather than for
# "releases" in general. See docs/plan.md, "Release views".
FILE_RELEASE = "file"

# Attributes a release row repeats from the dataset it names, and which differ
# from it on 737 of 104,451 rows.
RELEASE_ATTRIBUTES = ("type_of_data", "sensitivity", "legal_basis", "frequency")


def clean(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    text = str(value).replace("\r\n", "\n").strip()
    # Line breaks are kept: in free text they are paragraphs, and the "~" the
    # register starts a bullet line with stays for `build.paragraphs` to show.
    return re.sub(r"\n{3,}", "\n\n", text)


def clean_line(value) -> str:
    """`clean`, then every run of whitespace — newlines included — as one space.

    For fields that hold a name or a short label. The register leaves double
    spaces and stray line breaks in them ("BCP COUNCIL  [BOURNEMOUTH…]"), which
    HTML hides but which splits one name into two for anything that compares
    the text: an alias lookup, a search, a sort, a CSV.
    """
    return " ".join(clean(value).split())


def tidy_version(version: dict) -> dict:
    """Apply `clean_line` to every name-like field of a version, in place.

    One definition for both ways in: `extract` runs it on a fresh workbook, and
    `facts.rehydrate` runs it on stored facts, so a version written
    before a field was tidied gets the same treatment on the next build without
    a re-ingest. Idempotent. Free text (objective, activities, benefits) is
    left alone: its line breaks are paragraphs.
    """
    for key in ("title", "organisation", "organisation_type", "controller_basis"):
        version[key] = clean_line(version[key])
    version["controllers"] = [c for c in (clean_line(c) for c in version["controllers"]) if c]
    for dataset in version["datasets"]:
        for key in ("name", "type_of_data", "sensitivity", "frequency", "legal_basis", "confidentiality"):
            dataset[key] = clean_line(dataset[key])
    for release in version["releases"]:
        release["dataset"] = clean_line(release["dataset"])
    return version


def attribute_key(attributes) -> tuple:
    """The four attributes a release row repeats from the dataset it names.

    Normalised here rather than by the caller, because the two callers reach
    this from different directions: `extract` compares a release row with a
    dataset straight off the sheet, and `facts` compares one with a dataset
    that `tidy_version` has already cleaned. Without this they would disagree
    about whitespace alone, and the same edition would summarise differently
    depending on whether it came from a workbook or the store.
    """
    attributes = attributes or {}
    return tuple(clean_line(attributes.get(key, "")) for key in RELEASE_ATTRIBUTES)


def expected_attributes(datasets: list[dict]) -> dict:
    """`{dataset name: every set of attributes the version records for it}`.

    A version can list one dataset name twice with different attributes — an
    anonymised and an identifiable cut of "Civil Registrations of Death -
    Secondary Care Cut", say. Keeping all of them means a released file is
    judged against any record of its dataset rather than whichever happened to
    be read last, which otherwise depends on the order the datasets arrive in.
    """
    expected: dict[str, set] = {}
    for dataset in datasets:
        expected.setdefault(dataset["name"], set()).add(attribute_key(dataset))
    return expected


def summarise_releases(released: list[dict], datasets: list[dict]) -> list[dict]:
    """One version's released files, summarised per dataset as the site reads them.

    One definition for both ways in, like `tidy_version`: `extract` reads a
    workbook's release rows and `facts` replays a stored history, and both
    arrive here, so the site sees the same shape either way.

    A file whose month could not be parsed is still counted — it is a file
    released, and dropping it would make the totals disagree with the register
    — but it is left out of the first and last months, which it would otherwise
    blank out.

    `opt_outs_applied` is `"Mixed"` where the register gave both answers for one
    dataset, which it does for 130 of 8,449 pairs. Reporting whichever row came
    first, as this used to, hid that. `opt_out_files` counts the files under
    each answer, which is what the opt-out filter reads (see `privacy`).
    """
    expected = expected_attributes(datasets)
    grouped: dict[tuple, dict] = {}
    for entry in released:
        key = (entry.get("channel", FILE_RELEASE), entry["dataset"])
        summary = grouped.setdefault(
            key, {"files": 0, "months": {}, "opt_outs": {}, "attributes_differ": False}
        )
        summary["files"] += 1
        summary["months"][entry["month"]] = summary["months"].get(entry["month"], 0) + 1
        answer = entry["opt_outs_applied"]
        summary["opt_outs"][answer] = summary["opt_outs"].get(answer, 0) + 1
        if attribute_key(entry.get("attributes")) not in expected.get(entry["dataset"], set()):
            summary["attributes_differ"] = True

    summaries = []
    for (channel, dataset), summary in grouped.items():
        dated = sorted(month for month in summary["months"] if month)
        opt_outs = sorted(value for value in summary["opt_outs"] if value)
        summaries.append({
            "dataset": dataset,
            "channel": channel,
            "files": summary["files"],
            "first_month": dated[0] if dated else "",
            "last_month": dated[-1] if dated else "",
            "months": {month: summary["months"][month] for month in sorted(summary["months"])},
            "opt_outs_applied": opt_outs[0] if len(opt_outs) == 1 else ("Mixed" if opt_outs else ""),
            "opt_out_files": {answer: summary["opt_outs"][answer] for answer in sorted(summary["opt_outs"])},
            "attributes_differ": summary["attributes_differ"],
        })
    summaries.sort(key=lambda r: (-r["files"], r["dataset"]))
    return summaries


# Corporate suffixes that follow a comma inside one organisation's name
# rather than starting the next one: "MCKINSEY & COMPANY, INC. UNITED KINGDOM"
# is one company, and splitting it invented an organisation called "INC.".
# Deliberately excludes the ambiguous short ones — "CO" would break "CO
# DURHAM", and AB/AS/SA are as often words or places as company forms.
CORPORATE_SUFFIX = (
    "INC", "INCORPORATED", "LTD", "LIMITED", "LLC", "LLP", "PLC",
    "GMBH", "CORP", "CORPORATION", "PTY", "PTE", "SARL", "SRL", "BV", "NV",
)

# Multiple controllers are usually separated by ";" or a newline, but the
# register often uses a plain comma instead — "HULL UNIVERSITY TEACHING
# HOSPITALS NHS TRUST, UNIVERSITY OF YORK" is two joint controllers, not one
# organisation with a comma in its name. Split on those commas too, except one
# inside unclosed parentheses or square brackets, so an abbreviation like
# "HEALTHCARE QUALITY IMPROVEMENT PARTNERSHIP (HQIP), NHS ENGLAND - X26" still
# splits after the ")" rather than inside it, and a name that spells its parts
# out in brackets — "BCP COUNCIL [BOURNEMOUTH, CHRISTCHURCH AND POOLE]" — stays
# whole instead of becoming two organisations, one of them called
# "CHRISTCHURCH AND POOLE]".
# Every guard sits immediately after the comma, before any whitespace is
# consumed: with `,\s*` in front of them the engine simply backtracks `\s*`
# to empty, the lookahead then sees a leading space instead of the word it
# was checking for, and the guard silently passes.
LIST_SEPARATOR = re.compile(
    r"\s*;\s*|\n+|"
    r",(?![^(]*\))(?![^\[]*\])"
    r"(?!\s*(?i:" + "|".join(CORPORATE_SUFFIX) + r")\b)"
    r"\s*"
)


def protected_spans(text: str, known: tuple[str, ...]) -> list[tuple[int, int]]:
    """Where in `text` a known organisation name sits, longest match first.

    Longest first so that "NHS Bedfordshire, Luton and Milton Keynes ICB -
    M1J4Y" wins over a shorter name that happens to be a prefix of it.
    """
    spans: list[tuple[int, int]] = []
    lowered = text.lower()
    for name in known:
        start = lowered.find(name.lower())
        while start != -1:
            end = start + len(name)
            if not any(s <= start < e or s < end <= e for s, e in spans):
                spans.append((start, end))
            start = lowered.find(name.lower(), start + 1)
    return spans


def split_list(value, known: tuple[str, ...] = ()) -> list[str]:
    """Split a list-shaped register field, keeping known names whole.

    Some organisations have a comma in their name — "NHS Bristol, North
    Somerset and South Gloucestershire ICB - 15C", "Cumbria, Northumberland,
    Tyne and Wear NHS Foundation Trust" — and no rule about the text around
    the comma tells those apart from two organisations listed together. What
    does tell them apart is that the register names them in full elsewhere:
    Applicant Organisation holds one organisation per row and is never split,
    so the names appearing there are authoritative. Pass them as `known` and
    the commas inside them stop being separators.
    """
    # Horizontal whitespace only: a newline is a separator here. Collapsed so
    # that a known name written with one space matches the same name written
    # with two.
    text = re.sub(r"[^\S\n]+", " ", clean(value))
    if not text:
        return []
    spans = protected_spans(text, known) if known else []
    if not spans:
        return [p.strip() for p in LIST_SEPARATOR.split(text) if p.strip()]
    parts, start = [], 0
    for match in LIST_SEPARATOR.finditer(text):
        if any(s <= match.start() < e for s, e in spans):
            continue
        parts.append(text[start : match.start()])
        start = match.end()
    parts.append(text[start:])
    return [p.strip() for p in parts if p.strip()]


# Names with a comma that the register uses only for data controllers, never
# for an applicant, so Applicant Organisation can't vouch for them. Without
# this, "THE MINISTRY OF HOUSING, COMMUNITIES AND LOCAL GOVERNMENT" became two
# organisations, one of them "COMMUNITIES AND LOCAL GOVERNMENT".
CONTROLLER_COMMA_NAMES = ("Ministry of Housing, Communities and Local Government",)


def known_organisation_names(names) -> tuple[str, ...]:
    """The comma-bearing names to protect, longest first.

    Only names with a comma matter: everything else splits the same either
    way, and checking them all for every controller string would be waste.
    """
    names = {n for n in names if n and "," in n} | set(CONTROLLER_COMMA_NAMES)
    return tuple(sorted(names, key=len, reverse=True))


def resplit_list(items: list[str], known: tuple[str, ...] = ()) -> list[str]:
    """Re-apply `split_list`'s rules to an already-split list.

    For versions stored before the splitting rules changed: their controller
    lists are split by the *old* rules already, so re-joining and re-splitting
    the whole string isn't needed — splitting each existing item again is
    equivalent and cheaper.
    """
    parts = [part for item in items for part in split_list(item, known)]
    # A known name the store holds already split at its comma, because it was
    # stored before the name was known: put the halves back together.
    joined: list[str] = []
    for part in parts:
        if joined and known:
            candidate = f"{joined[-1]}, {part}"
            boundary = len(joined[-1])
            if any(s < boundary < e for s, e in protected_spans(candidate, known)):
                joined[-1] = candidate
                continue
        joined.append(part)
    return joined
