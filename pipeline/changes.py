"""What changed between editions, worked out from the facts store.

``snapshot`` answered this from digests written at ingest, which made every
answer a function of the rules in force that day: changing what counted as an
amendment meant re-parsing 63 workbooks, and editions fingerprinted under
different rules could not be compared at all. ``facts`` stores what each
edition said, so the same questions are answered here at build time, from the
text, under the alias files as they are now.

Two things follow that the fingerprints could not do. A dataset alias reviewed
today corrects the whole archive at the next build. And there is no rule
version, so no comparison is ever refused — the "cannot be compared" gap goes
away with the digests that caused it.

The work is done in two passes, because the text is large and most of it never
changes:

*The indexes say where to look.* Two editions differ in a version exactly when
its state index differs, so `facts.edition_index` — 192 KB an edition — finds
every candidate without reading a word of the register.

*The text says what changed.* Only the candidates are read, and only their two
states, which `compare.compare_versions` compares field by field with the same
normalisation the agreement pages use. A version whose text moved only in
typography is not an amendment, and neither is a dataset the register merely
relabelled.
"""

from __future__ import annotations

import json
from collections import defaultdict

from . import aliases
from . import compare
from . import facts
from . import sources
from .extract import _base_and_version, slugify


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


def _material(difference: dict | None) -> bool:
    """Whether a difference is a change to the register or only to its typing.

    `compare_versions` reports reformatting separately from substance, so this
    is the one place that decides what counts as an amendment — and it is a
    build-time decision now, free to change without touching what is stored.
    """
    if not difference:
        return False
    return bool(difference["scalars"] or difference["lists"] or difference["prose"])


def _labels(difference: dict) -> list[str]:
    labels = [item.get("group", item["label"]) for item in difference["scalars"]]
    labels += [item["label"] for item in difference["lists"]]
    labels += [item["label"] for item in difference["prose"]]
    return sorted(set(labels))


def _agreement_records(register_slug: str, bases) -> dict[str, dict]:
    """The stored record of each named agreement, read once."""
    records = {}
    for base in bases:
        path = facts.agreements_dir(register_slug) / f"{slugify(base)}.json"
        if path.exists():
            records[base] = json.loads(path.read_text(encoding="utf-8"))
    return records


def _states(record: dict) -> dict[str, list[dict]]:
    return {version["reference"]: version["states"] for version in record["versions"]}


def _describe(state: dict, organisation: str) -> dict:
    """What a row on the changes page shows: the version's title, under its agreement's organisation.

    The organisation is the agreement's — that of its latest version in the
    edition — because the row links to the agreement page, which shows that
    one, and because the fingerprints this replaces recorded it that way. A
    version's own applicant can differ: DARS-NIC-204580-F5B0C-v0.6 was applied
    for by a hospital trust while the agreement is now a cancer alliance's.
    """
    return {"org": organisation, "title": state.get("title", "")}


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


def diff(
    register_slug: str,
    edition: str,
    previous_edition: str | None = None,
    alias_map: dict[str, str] | None = None,
) -> dict:
    """Agreement-version level changes between `edition` and the one before it."""
    held = facts.stored_editions(register_slug)
    if edition not in held:
        raise SystemExit(f"no stored facts for the {edition} edition of {register_slug}")
    if previous_edition is None:
        position = held.index(edition)
        previous_edition = held[position - 1] if position else None
    if previous_edition is None:
        return {
            "comparable": False, "reason": "first-edition", "previous_edition": None,
            "skipped": [], "added": [], "amended": [], "removed": [],
        }

    if alias_map is None:
        alias_map = aliases.load_map(aliases.DATASET_ALIASES_PATH)
    now = facts.edition_index(register_slug, edition)
    before = facts.edition_index(register_slug, previous_edition)

    new_refs = [r for r in now if r not in before]
    gone_refs = [r for r in before if r not in now]
    candidates = [r for r, state in now.items() if r in before and before[r] != state]

    bases = {_base_and_version(r)[0] for r in new_refs + gone_refs + candidates}
    records = _agreement_records(register_slug, bases)
    states = {base: _states(record) for base, record in records.items()}

    def state_of(reference: str, index: dict) -> dict | None:
        base = _base_and_version(reference)[0]
        versions = states.get(base, {})
        if reference not in versions:
            return None
        return versions[reference][index[reference]]

    def organisation(reference: str, index: dict) -> str:
        return _agreement_organisation(records.get(_base_and_version(reference)[0]), index)

    old_bases = {_base_and_version(r)[0] for r in before}
    added, amended, removed = [], [], []
    for reference in new_refs:
        state = state_of(reference, now)
        base = _base_and_version(reference)[0]
        added.append({
            "reference": reference, "base": base, **_describe(state or {}, organisation(reference, now)),
            # A new version of an agreement we already knew about is a renewal,
            # not a brand new data release.
            "kind": "renewal" if base in old_bases else "new",
        })
    for reference in candidates:
        was, is_now = state_of(reference, before), state_of(reference, now)
        if was is None or is_now is None:
            continue
        difference = compare.compare_versions(was, is_now, alias_map)
        if _material(difference):
            amended.append({
                "reference": reference, "base": _base_and_version(reference)[0],
                **_describe(is_now, organisation(reference, now)), "fields": _labels(difference),
            })
    for reference in gone_refs:
        state = state_of(reference, before)
        removed.append({
            "reference": reference, "base": _base_and_version(reference)[0],
            **_describe(state or {}, organisation(reference, before)),
        })

    order = lambda item: (item["org"].lower(), item["reference"])
    return {
        "comparable": True,
        "previous_edition": previous_edition,
        "skipped": skipped_editions(previous_edition, edition),
        "added": sorted(added, key=order),
        "amended": sorted(amended, key=order),
        "removed": sorted(removed, key=order),
    }


def history(register_slug: str, alias_map: dict[str, str] | None = None) -> dict[str, dict]:
    """When each agreement and each of its versions appeared or changed.

    `{base_reference: {"first_edition", "first_is_earliest", "events"}}`, with
    one event per edition in which something happened, oldest first so it reads
    as a timeline. Events are grouped by edition rather than one per version:
    NHS England restates every version of an agreement at once often enough
    that the ungrouped list runs to sixteen near-identical lines for one edit.

    An agreement present in the earliest edition held may well be older than
    that, so `first_is_earliest` marks the ones whose start we cannot see.
    """
    editions = facts.stored_editions(register_slug)
    if not editions:
        return {}
    if alias_map is None:
        alias_map = aliases.load_map(aliases.DATASET_ALIASES_PATH)
    indexes = {edition: facts.edition_index(register_slug, edition) for edition in editions}
    earliest = editions[0]

    # Pass one, over the indexes alone: which agreement changed in which
    # edition, and between which two states. No register text is read.
    pending: dict[str, list[dict]] = defaultdict(list)
    index: dict[str, dict] = {}
    previous: dict[str, int] = {}
    previous_edition = ""
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
        for reference, state in previous.items():
            base = _base_and_version(reference)[0]
            if reference not in current and base in index:
                pending[base].append({"edition": edition, "skipped": skipped, "kind": "removed",
                                      "reference": reference, "from": state, "to": None})
        previous, previous_edition = current, edition

    # Pass two, one agreement at a time: name the fields each amendment moved.
    # Held one record at a time so the whole archive never sits in memory.
    for base, events in pending.items():
        states = _states(_agreement_records(register_slug, [base]).get(base, {"versions": []}))
        by_edition: dict[str, dict] = {}
        for event in events:
            entry = by_edition.setdefault(event["edition"], {
                "edition": event["edition"], "skipped": event["skipped"],
                "added": [], "amended": [], "removed": [], "fields": [],
            })
            fields: list[str] = []
            if event["kind"] == "amended":
                version = states.get(event["reference"], [])
                if event["from"] < len(version) and event["to"] < len(version):
                    difference = compare.compare_versions(
                        version[event["from"]], version[event["to"]], alias_map
                    )
                    # Naming the fields is the difference between "this was
                    # edited" and "the data controller was changed" — the
                    # second is what a reader came for, and the register itself
                    # never says it.
                    if not _material(difference):
                        continue
                    fields = _labels(difference)
            entry[event["kind"]].append({"reference": event["reference"], "fields": fields})
        for entry in by_edition.values():
            for kind in ("added", "amended", "removed"):
                entry[kind].sort(key=lambda item: item["reference"])
            if not (entry["added"] or entry["amended"] or entry["removed"]):
                continue
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
        if first and not (first[0]["amended"] or first[0]["removed"]):
            entry["first_versions"] = [item["reference"] for item in first[0]["added"]]
            entry["events"].remove(first[0])
        else:
            entry["first_versions"] = []
    return index
