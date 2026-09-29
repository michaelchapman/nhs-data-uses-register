"""What changed between editions, worked out from the facts store.

This used to be answered from a digest of each edition written at ingest, which
made every answer a function of the rules in force that day: changing what
counted as an amendment meant re-parsing 63 workbooks, and editions digested
under different rules could not be compared at all. ``facts`` stores what each
edition said, so the same questions are answered here at build time, from the
text, under the alias files as they are now.

Two things follow that digests could not do. A dataset alias reviewed
today corrects the whole archive at the next build. And there is no rule
version, so no comparison is ever refused — the "cannot be compared" gap goes
away with the digests that caused it.

The work is done in two passes, because the text is large and most of it never
changes:

*The indexes say where to look.* Two editions differ in a version exactly when
its state index differs, so `facts.edition_index` — 192 KB an edition — finds
every candidate without reading a word of the register.

*The text says what changed.* Only the candidates are read, each agreement once
however many editions changed it, and only their states are compared, by
`compare.compare_versions`, field by field with the same normalisation the
agreement pages use. A version whose text moved only in typography is not an
amendment, and neither is a dataset the register merely relabelled.

A build wants every edition's changes and every agreement's timeline, and
`every_edition` answers both from that one read. `diff` and `history` answer
one question each, the same way.
"""

from __future__ import annotations

from collections import defaultdict

from . import compare
from . import facts
from . import sources
from .extract import _base_and_version
from .rules import Rules


def skipped_editions(previous: str, current: str) -> list[str]:
    """The months between two editions that have no edition of their own here.

    Editions are monthly, so an empty answer means they are neighbours. A gap
    means a workbook was never added, and whatever changed in the months it
    covered is folded into the later edition.
    """
    before_year, before_month = sources.edition_sort_key(previous)
    after_year, after_month = sources.edition_sort_key(current)
    start = before_year * 12 + before_month - 1
    months = after_year * 12 + after_month - 1 - start
    skipped = []
    for offset in range(1, months):
        year, month = divmod(start + offset, 12)
        skipped.append(f"{sources.MONTHS[month]}{year}")
    return skipped


def missing_editions(editions: list[str]) -> list[str]:
    """Every month between the first and last of `editions` (oldest first) that is absent."""
    return [gap for a, b in zip(editions, editions[1:]) for gap in skipped_editions(a, b)]


def _included(index: dict[str, int], excluded: frozenset[str]) -> dict[str, int]:
    """An edition's index without the agreements `exclusions` leaves out."""
    if not excluded:
        return index
    return {ref: state for ref, state in index.items() if _base_and_version(ref)[0].upper() not in excluded}


def _material(difference: dict | None) -> bool:
    """Whether a difference is a change to the register or only to its typing.

    `compare_versions` reports reformatting separately from substance, so this
    is the one place that decides what counts as an amendment — and it is a
    build-time decision now, free to change without touching what is stored.
    """
    if not difference:
        return False
    return bool(difference["scalars"] or difference["lists"] or difference["prose"])


# How many agreements one edition must reword the same way before the site
# reports it once, as a register-wide edit, instead of once per agreement.
# Across the archive only December 2022 reaches it: "s261(1) and" taken out of
# the legal basis cited for datasets on 639 agreements, accounting for 1,191 of
# that edition's 1,192 amended versions. The next largest rewording in any
# edition touches fewer than 20.
WIDE_EDIT_AGREEMENTS = 50

# Values longer than this are shown by the words that changed, not in full.
LONG_VALUE = 60


def _details(difference: dict, redlines: bool = False) -> list[dict]:
    """What an amendment changed, for a reader: values, rewordings, lists and prose.

    A short value is shown before and after. A long one that was reworded
    rather than replaced — a legal basis with one clause taken out — is shown
    by the words that changed, which is what a reader is looking for in it.
    Prose carries its redline only with `redlines`, for an agreement's own
    page; a changes page lists hundreds and names the field.
    """
    found = []
    for item in difference["scalars"]:
        edits, kept = compare.word_edits(item["before"], item["after"])
        if kept and edits and max(len(item["before"]), len(item["after"])) > LONG_VALUE:
            found.append({"label": item["label"], "kind": "edit",
                          "edits": [{"removed": r, "added": a} for r, a in edits]})
        else:
            found.append({"label": item["label"], "kind": "value", "before": item["before"], "after": item["after"]})
    for item in difference["lists"]:
        found.append({"label": item["label"], "kind": "list", "added": item["added"], "removed": item["removed"]})
    for item in difference["prose"]:
        found.append({"label": item["label"], "kind": "prose", "filled_in": item["filled_in"],
                      "blocks": item["blocks"] if redlines else None, "text": item["text"] if redlines else ""})
    return found


def _field(item: dict) -> str:
    """The field a change is to: "Datasets: legal basis" for any dataset's legal basis."""
    if item.get("group"):
        return f"{item['group']}: {item['label'].rsplit(': ', 1)[-1]}"
    return item["label"]


def _partial_edits(difference: dict) -> list[tuple[str, str, str]]:
    """`(field, removed, added)` for every rewording of part of a short field."""
    found = []
    for item in difference["scalars"]:
        edits, kept = compare.word_edits(item["before"], item["after"])
        if kept:
            found += [(_field(item),) + edit for edit in edits]
    return found


def _only_rewordings(difference: dict) -> list[tuple[str, str, str]] | None:
    """The rewordings, if rewording parts of fields is all a difference does; else None."""
    if difference["lists"] or difference["prose"]:
        return None
    edits = []
    for item in difference["scalars"]:
        found, kept = compare.word_edits(item["before"], item["after"])
        if not kept or not found:
            return None
        edits += [(_field(item),) + edit for edit in found]
    return edits


def _labels(difference: dict) -> list[str]:
    labels = [item.get("group", item["label"]) for item in difference["scalars"]]
    labels += [item["label"] for item in difference["lists"]]
    labels += [item["label"] for item in difference["prose"]]
    return sorted(set(labels))


def _states(record: dict) -> dict[str, list[dict]]:
    return {version["reference"]: version["states"] for version in record["versions"]}


def _describe(row: dict) -> dict:
    """What a row on the changes page shows: the version's title, under its agreement's organisation.

    The organisation is the agreement's — that of its latest version in the
    edition — because the row links to the agreement page, which shows that
    one. A version's own applicant can differ: DARS-NIC-204580-F5B0C-v0.6 was
    applied for by a hospital trust while the agreement is now a cancer
    alliance's.
    """
    return {"org": row["org"], "title": row["title"]}


def _agreement_organisation(record: dict | None, index: dict[str, int]) -> str:
    """The organisation of the latest version of an agreement that `index` lists."""
    if not record:
        return ""
    from .extract import _version_key

    held = [
        (_version_key(version["version"]), version["states"][index[version["reference"]]].get("start_date", ""),
         version["states"][index[version["reference"]]].get("organisation", ""))
        for version in record["versions"]
        if version["reference"] in index and index[version["reference"]] < len(version["states"])
    ]
    return max(held)[2] if held else ""


def not_comparable(reason: str) -> dict:
    """A `diff` result for an edition with nothing to compare it with.

    `reason` is "first-edition" for the earliest edition held, or
    "not-ingested" for one built straight from a workbook.
    """
    return {
        "comparable": False, "reason": reason, "previous_edition": None,
        "skipped": [], "added": [], "amended": [], "removed": [], "wide_edits": [], "wide_ops": {},
    }


def _maps(rules: Rules, alias_map: dict[str, str] | None) -> tuple:
    """What `compare.compare_versions` compares under: dataset aliases, organisation aliases, lineage.

    `alias_map`, when given, stands in for the dataset aliases.
    """
    return (rules.dataset_aliases if alias_map is None else alias_map), rules.organisation_aliases, rules.lineage


def _indexes(register_slug: str, editions, rules: Rules) -> dict[str, dict[str, int]]:
    return {edition: _included(facts.edition_index(register_slug, edition), rules.excluded) for edition in editions}


# Three steps, so that each agreement's file — the whole of its text, in every
# state it has had — is read once however many editions changed it:
#
# 1. `_ask_edition` and `_timeline` go through the indexes alone and note, for
#    each agreement, which rows describe it and which pairs of its states are
#    to be compared.
# 2. `_read` reads each of those agreements once, one at a time, and answers.
# 3. `_edition_changes` and `_history` assemble the answers.


def _work() -> defaultdict:
    """`{base: {"rows": [(edition, reference, side)], "compare": {(reference, from, to)}}}`."""
    return defaultdict(lambda: {"rows": [], "compare": set()})


def _references(before: dict[str, int], now: dict[str, int]) -> tuple[list[str], list[str], list[str]]:
    """`(new, gone, candidates)`: the references `now` adds, drops, and holds in another state."""
    new = [r for r in now if r not in before]
    gone = [r for r in before if r not in now]
    candidates = [r for r, state in now.items() if r in before and before[r] != state]
    return new, gone, candidates


def _ask_edition(work: dict, previous: str, edition: str, indexes: dict) -> None:
    """Note what the changes page for `edition` needs to know."""
    before, now = indexes[previous], indexes[edition]
    new, gone, candidates = _references(before, now)
    for reference in new + candidates:
        work[_base_and_version(reference)[0]]["rows"].append((edition, reference, edition))
    # A version no longer listed is described as the edition before published it.
    for reference in gone:
        work[_base_and_version(reference)[0]]["rows"].append((edition, reference, previous))
    for reference in candidates:
        work[_base_and_version(reference)[0]]["compare"].add((reference, before[reference], now[reference]))


def _read(register_slug: str, work: dict, indexes: dict, maps: tuple) -> tuple[dict, dict]:
    """Read each agreement in `work` once, and answer what was asked of it.

    Returns `(rows, differences)`: `{(edition, reference): {title, org, held}}`
    for each row, and `{(reference, from, to): difference}` for each pair of
    states, leaving out a pair the stored record cannot supply. One agreement
    is held at a time, so the store never sits in memory whole.
    """
    rows: dict[tuple[str, str], dict] = {}
    differences: dict[tuple[str, int, int], dict | None] = {}
    for base in sorted(work):
        record = facts.read_agreement(register_slug, base)
        states = _states(record) if record else {}
        asked = work[base]
        for edition, reference, side in asked["rows"]:
            index = indexes[side]
            versions = states.get(reference, [])
            state = versions[index[reference]] if index[reference] < len(versions) else None
            rows[(edition, reference)] = {
                "title": (state or {}).get("title", ""),
                "org": _agreement_organisation(record, index),
                "held": state is not None,
            }
        for key in sorted(asked["compare"]):
            reference, was, now = key
            versions = states.get(reference, [])
            if was < len(versions) and now < len(versions):
                differences[key] = compare.compare_versions(versions[was], versions[now], *maps)
    return rows, differences


def _edition_changes(previous: str, edition: str, indexes: dict, rows: dict, differences: dict) -> dict:
    """Agreement-version level changes between `edition` and `previous`, from `_read`'s answers."""
    before, now = indexes[previous], indexes[edition]
    new_refs, gone_refs, candidates = _references(before, now)

    old_bases = {_base_and_version(r)[0] for r in before}
    added, amended, removed = [], [], []
    for reference in new_refs:
        base = _base_and_version(reference)[0]
        added.append({
            "reference": reference, "base": base, **_describe(rows[(edition, reference)]),
            # A new version of an agreement we already knew about is a renewal,
            # not a brand new data release.
            "kind": "renewal" if base in old_bases else "new",
        })
    found = []
    for reference in candidates:
        key = (reference, before[reference], now[reference])
        if key not in differences:
            continue
        difference = differences[key]
        if _material(difference):
            found.append((reference, rows[(edition, reference)], difference))

    # The same rewording on enough agreements at once is one edit to the
    # register, reported once: see WIDE_EDIT_AGREEMENTS.
    reworded: dict[tuple, set[str]] = {}
    for reference, _, difference in found:
        for edit in _partial_edits(difference):
            reworded.setdefault(edit, set()).add(_base_and_version(reference)[0])
    wide_ops = {edit: len(bases) for edit, bases in reworded.items() if len(bases) >= WIDE_EDIT_AGREEMENTS}
    wide: dict[tuple, list[dict]] = {}
    for reference, row, difference in found:
        item = {
            "reference": reference, "base": _base_and_version(reference)[0], **_describe(row),
            "fields": _labels(difference), "details": _details(difference),
        }
        edits = _only_rewordings(difference)
        if edits and all(edit in wide_ops for edit in edits):
            wide.setdefault(tuple(sorted(set(edits))), []).append(item)
        else:
            amended.append(item)
    for reference in gone_refs:
        removed.append({
            "reference": reference, "base": _base_and_version(reference)[0],
            **_describe(rows[(edition, reference)]),
        })

    order = lambda item: (item["org"].lower(), item["reference"])
    wide_edits = sorted(
        (
            {
                "edits": [{"field": field, "removed": gone, "added": came} for field, gone, came in edits],
                "agreements": len({item["base"] for item in items}),
                "versions": sorted(items, key=order),
            }
            for edits, items in wide.items()
        ),
        key=lambda w: -len(w["versions"]),
    )
    return {
        "comparable": True,
        "previous_edition": previous,
        "skipped": skipped_editions(previous, edition),
        "added": sorted(added, key=order),
        "amended": sorted(amended, key=order),
        "removed": sorted(removed, key=order),
        "wide_edits": wide_edits,
        # For `history`, which reads one agreement at a time and so cannot
        # count across an edition itself.
        "wide_ops": wide_ops,
    }


def _timeline(editions: list[str], indexes: dict, work: dict) -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """Which agreement changed in which edition, and between which two states.

    Returns `(index, pending)`: each agreement's first appearance, and its
    events, one per version that was added, amended or removed. The pairs of
    states an amendment moved between are added to `work`. No register text is
    read.
    """
    pending: dict[str, list[dict]] = defaultdict(list)
    index: dict[str, dict] = {}
    previous: dict[str, int] = {}
    previous_edition = ""
    earliest = editions[0]
    for edition in editions:
        current = indexes[edition]
        skipped = skipped_editions(previous_edition, edition) if previous_edition else []
        for reference, state in current.items():
            base = _base_and_version(reference)[0]
            index.setdefault(base, {
                "first_edition": edition,
                "first_is_earliest": edition == earliest,
                "first_skipped": skipped,
                "events": [],
            })
            if reference not in previous:
                pending[base].append({"edition": edition, "skipped": skipped, "kind": "added",
                                      "reference": reference, "from": None, "to": state})
            elif previous[reference] != state:
                pending[base].append({"edition": edition, "skipped": skipped, "kind": "amended",
                                      "reference": reference, "from": previous[reference], "to": state})
                work[base]["compare"].add((reference, previous[reference], state))
        for reference, state in previous.items():
            base = _base_and_version(reference)[0]
            if reference not in current and base in index:
                pending[base].append({"edition": edition, "skipped": skipped, "kind": "removed",
                                      "reference": reference, "from": state, "to": None})
        previous, previous_edition = current, edition
    return index, pending


def _history(index: dict, pending: dict, differences: dict, wide: dict) -> dict[str, dict]:
    """Name the fields each amendment moved, and group each agreement's events by edition."""
    for base, events in pending.items():
        by_edition: dict[str, dict] = {}
        for event in events:
            entry = by_edition.setdefault(event["edition"], {
                "edition": event["edition"], "skipped": event["skipped"],
                "added": [], "amended": [], "removed": [], "fields": [], "reorganised": [], "wide": [],
            })
            fields: list[str] = []
            details: list[dict] = []
            key = (event["reference"], event["from"], event["to"])
            if event["kind"] == "amended" and key in differences:
                difference = differences[key]
                # Naming the fields is the difference between "this was
                # edited" and "the data controller was changed" — the
                # second is what a reader came for, and the register itself
                # never says it.
                if not _material(difference):
                    # A rename or an ODS succession is not an amendment,
                    # but the timeline says it happened, once per edition.
                    for item in (difference or {}).get("succeeded", []) + (difference or {}).get("renamed", []):
                        pair = {"label": item["label"], "before": item["before"], "after": item["after"],
                                "date": item.get("date", ""), "source": item.get("source", "ODS"),
                                "kind": "succeeded" if item in (difference or {}).get("succeeded", []) else "renamed"}
                        if item["label"] != "Organisation type" and pair not in entry["reorganised"]:
                            entry["reorganised"].append(pair)
                    continue
                edits = _only_rewordings(difference)
                in_edition = wide.get(event["edition"], {})
                if edits and all(edit in in_edition for edit in edits):
                    entry["wide"].append({
                        "reference": event["reference"],
                        "edits": [{"field": f, "removed": r, "added": a} for f, r, a in sorted(set(edits))],
                        "agreements": max(in_edition[edit] for edit in edits),
                    })
                    continue
                fields = _labels(difference)
                details = _details(difference, redlines=True)
            entry[event["kind"]].append({"reference": event["reference"], "fields": fields, "details": details})
        for entry in by_edition.values():
            for kind in ("added", "amended", "removed"):
                entry[kind].sort(key=lambda item: item["reference"])
            if not (entry["added"] or entry["amended"] or entry["removed"] or entry["reorganised"] or entry["wide"]):
                continue
            # One line per register-wide edit, naming every version it touched.
            merged: dict[tuple, dict] = {}
            for item in entry["wide"]:
                key = tuple((e["field"], e["removed"], e["added"]) for e in item["edits"])
                merged.setdefault(key, {**item, "references": []})["references"].append(item["reference"])
            entry["wide"] = list(merged.values())
            # The union across the edition's amendments, for a one-line summary
            # when several versions were restated together.
            entry["fields"] = sorted({f for item in entry["amended"] for f in item["fields"]})
            index[base]["events"].append(entry)
        index[base]["events"].sort(key=lambda e: sources.edition_sort_key(e["edition"]))

    for entry in index.values():
        entry["amendments"] = sum(len(e["amended"]) for e in entry["events"])
        # The edition an agreement first appears in always produces an "added"
        # event, which repeats the "first listed" line the page already shows.
        # Fold its references into that line and drop the event, so the page
        # does not print the same edition twice. An edition that also amended
        # or removed something is left alone: it has more to say.
        first = [e for e in entry["events"] if e["edition"] == entry["first_edition"]]
        if first and not (first[0]["amended"] or first[0]["removed"] or first[0]["reorganised"] or first[0]["wide"]):
            entry["first_versions"] = [item["reference"] for item in first[0]["added"]]
            entry["events"].remove(first[0])
        else:
            entry["first_versions"] = []
    return index


def diff(
    register_slug: str,
    edition: str,
    previous_edition: str | None = None,
    alias_map: dict[str, str] | None = None,
    rules: Rules | None = None,
) -> dict:
    """Agreement-version level changes between `edition` and the one before it."""
    held = facts.stored_editions(register_slug)
    if edition not in held:
        raise SystemExit(f"no stored facts for the {edition} edition of {register_slug}")
    if previous_edition is None:
        position = held.index(edition)
        previous_edition = held[position - 1] if position else None
    if previous_edition is None:
        return not_comparable("first-edition")

    rules = rules or Rules.load()
    indexes = _indexes(register_slug, (previous_edition, edition), rules)
    work = _work()
    _ask_edition(work, previous_edition, edition, indexes)
    rows, differences = _read(register_slug, work, indexes, _maps(rules, alias_map))
    return _edition_changes(previous_edition, edition, indexes, rows, differences)


def history(
    register_slug: str,
    alias_map: dict[str, str] | None = None,
    wide: dict[str, dict[tuple, int]] | None = None,
    rules: Rules | None = None,
) -> dict[str, dict]:
    """When each agreement and each of its versions appeared or changed.

    `{base_reference: {"first_edition", "first_is_earliest", "events"}}`, with
    one event per edition in which something happened, oldest first so it reads
    as a timeline. Events are grouped by edition rather than one per version:
    NHS England restates every version of an agreement at once often enough
    that the ungrouped list runs to sixteen near-identical lines for one edit.

    An agreement present in the earliest edition held may well be older than
    that, so `first_is_earliest` marks the ones whose start we cannot see.

    `wide` is `{edition: {rewording: agreements}}`, the register-wide edits
    `diff` found in each edition. An amendment that is only those is recorded
    under `wide`, not `amended`.
    """
    editions = facts.stored_editions(register_slug)
    if not editions:
        return {}
    rules = rules or Rules.load()
    indexes = _indexes(register_slug, editions, rules)
    work = _work()
    index, pending = _timeline(editions, indexes, work)
    _, differences = _read(register_slug, work, indexes, _maps(rules, alias_map))
    return _history(index, pending, differences, wide or {})


def every_edition(
    register_slug: str, alias_map: dict[str, str] | None = None, rules: Rules | None = None
) -> tuple[dict[str, dict], dict[str, dict]]:
    """`({edition: diff}, history)` for every edition held, reading each agreement once.

    The same answers as `diff` for each edition after the first and `history`
    with their register-wide edits, for a build, which wants them all: asked
    one edition at a time, an agreement amended in many editions is read once
    for each of them.
    """
    editions = facts.stored_editions(register_slug)
    if not editions:
        return {}, {}
    rules = rules or Rules.load()
    indexes = _indexes(register_slug, editions, rules)
    pairs = list(zip(editions, editions[1:]))
    work = _work()
    for previous, edition in pairs:
        _ask_edition(work, previous, edition, indexes)
    index, pending = _timeline(editions, indexes, work)
    rows, differences = _read(register_slug, work, indexes, _maps(rules, alias_map))
    diffs = {edition: _edition_changes(previous, edition, indexes, rows, differences) for previous, edition in pairs}
    timeline = _history(index, pending, differences, {edition: d["wide_ops"] for edition, d in diffs.items()})
    return {editions[0]: not_comparable("first-edition"), **diffs}, timeline
