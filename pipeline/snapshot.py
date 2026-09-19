"""Per-edition fingerprints, so the site can show what changed each month.

The published workbooks are far too large to keep in git. Instead each ingest
writes a small fingerprint file per edition
(`data/snapshots/<register>/<edition>.json.gz`) holding a hash of every
agreement version. Comparing an edition with the one published before it gives
the "new and changed this month" view, and keeping the files in git gives a
durable history — cheap enough that every edition in NHS England's archive can
have one.

Editions are ordered by the month in their label, never by when we ingested
them: a backfill runs through years of archived workbooks in one afternoon, so
ingest timestamps say nothing about publication order.
"""

from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

from . import compare
from . import sources

SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# Bumped whenever the rules below change what counts as a change. Snapshots
# written under different versions are not comparable: every digest moves, so a
# naive comparison reports the entire register as amended. `diff` refuses
# instead, and the fix is to re-ingest the archive so every edition is
# fingerprinted under the same rules. Snapshots written before this existed are
# version 1.
FINGERPRINT_VERSION = 3

# Fields whose change we consider a substantive amendment to an agreement.
FINGERPRINTED = (
    "title",
    "organisation",
    "organisation_type",
    "controller_basis",
    "start_date",
    "end_date",
    "sublicensing",
    "commercial",
    "objective",
    "activities",
    "expected_output",
    "expected_benefits",
    "yielded_benefits",
)


# Two more things a reader would call a change, which the digest used to miss
# entirely: who the data controllers are, and what the register records about
# each dataset beyond its name — a dataset re-classified as sensitive, or its
# legal basis moving to Section 251, used to register as no change at all.
DATASET_ATTRIBUTES = ("name", "legal_basis", "sensitivity", "type_of_data", "confidentiality")

# `releases` and `files_released` stay out on purpose. They move every month by
# design, and folding them in would mark most of the register amended every
# edition, which is the same failure as counting typography.

FIELD_LABELS = {
    **{key: label for key, label in compare.SCALAR_FIELDS},
    **{key: label for key, label in compare.PROSE_FIELDS},
    "controllers": "Data controllers",
    "datasets": "Datasets",
}


def _fingerprints(version: dict) -> dict[str, str]:
    """A digest per field, so a comparison can name what moved.

    Text is normalised before hashing (`compare.normalise`: NFKC, smart
    punctuation folded, whitespace collapsed, case ignored) so that an edition
    which merely reformats the register does not read as thousands of
    amendments. This is not hypothetical — of the 122 amendments between the
    February and March 2026 editions, 105 were typography alone, and the site
    reported all 122. See docs/plan-version-diffs.md §7.

    The same normalisation decides what the agreement pages call a change, so
    the two never disagree.

    One digest per field rather than one for the whole version: the combined
    answer is still just "are these equal", recovered by comparing the maps,
    but the per-field form also says *which* field moved — the difference
    between "122 agreements changed" and "122 agreements had their benefits
    text reformatted". Eight hex characters is ample when the only question
    asked of a digest is whether it equals the one field it is compared with.
    """
    fields: dict[str, object] = {
        key: compare.normalise(version.get(key, "")) for key in FINGERPRINTED
    }
    fields["controllers"] = sorted(compare.normalise(c) for c in version.get("controllers") or [])
    fields["datasets"] = sorted(
        [compare.normalise(dataset.get(key, "")) for key in DATASET_ATTRIBUTES]
        for dataset in version["datasets"]
    )
    return {
        key: hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()[:8]
        for key, value in fields.items()
    }


def _digest(entry: dict):
    """What identifies a version's content, whichever snapshot format holds it.

    Rules v1 and v2 stored a single combined `hash`; v3 stores a digest per
    field. `diff` refuses to compare across rule versions, so both sides of any
    comparison are always the same shape — this only has to read either one.
    """
    return entry["hashes"] if "hashes" in entry else entry.get("hash")


def changed_fields(before: dict, after: dict) -> list[str]:
    """Which fields differ, labelled for display. Empty for older snapshots."""
    old, new = before.get("hashes"), after.get("hashes")
    if not old or not new:
        return []
    keys = [key for key in new if old.get(key) != new[key]]
    keys += [key for key in old if key not in new]
    return sorted(FIELD_LABELS.get(key, key) for key in set(keys))


def fingerprint_version(snapshot: dict) -> int:
    """Which rules a snapshot's digests were computed under."""
    return snapshot.get("fingerprint_version", 1)


def build_snapshot(data: dict, register_slug: str, edition: str, source_url: str, retrieved: str) -> dict:
    versions = {}
    for agreement in data["agreements"]:
        for version in agreement["versions"]:
            versions[version["reference"]] = {
                "base": agreement["base_reference"],
                "org": agreement["organisation"],
                "title": version["title"],
                "hashes": _fingerprints(version),
            }
    return {
        "register": register_slug,
        "edition": edition,
        "fingerprint_version": FINGERPRINT_VERSION,
        "source_url": source_url,
        "retrieved": retrieved,
        "counts": {
            "agreements": len(data["agreements"]),
            "agreement_versions": len(versions),
            "organisations": len(data["organisations"]),
            "datasets": len(data["datasets"]),
        },
        "versions": versions,
    }


def snapshot_dir(register_slug: str) -> Path:
    path = SNAPSHOT_ROOT / register_slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def edition_of(path: Path) -> str:
    """The edition label a snapshot file holds, from its name."""
    return path.name.split(".", 1)[0]


def existing_editions(register_slug: str) -> list[Path]:
    """Snapshot files, oldest first, ordered by the edition each one covers.

    Both `.json.gz` and plain `.json` are read; new files are always gzipped.
    """
    directory = snapshot_dir(register_slug)
    by_edition: dict[str, Path] = {}
    for path in sorted(directory.glob("*.json*")):
        if path.suffix not in (".json", ".gz"):
            continue
        # A gzipped file wins over a stale plain one for the same edition.
        edition = edition_of(path)
        if edition not in by_edition or path.name.endswith(".gz"):
            by_edition[edition] = path
    return [by_edition[e] for e in sorted(by_edition, key=sources.edition_sort_key)]


def read_snapshot(path: Path) -> dict:
    if path.name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return json.load(handle)
    return json.loads(path.read_text())


def write_snapshot(snapshot: dict) -> Path:
    directory = snapshot_dir(snapshot["register"])
    path = directory / f"{snapshot['edition']}.json.gz"
    # Compact: one of these lands in git for every edition, forever.
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n"
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        handle.write(payload)
    # An earlier run may have left an uncompressed file for this edition.
    plain = directory / f"{snapshot['edition']}.json"
    if plain.exists():
        plain.unlink()
    return path


def load_snapshot(register_slug: str, edition: str) -> dict | None:
    for path in existing_editions(register_slug):
        if edition_of(path) == edition:
            return read_snapshot(path)
    return None


def previous_snapshot(register_slug: str, edition: str) -> dict | None:
    """The snapshot of the edition published immediately before `edition`.

    Not simply "the last one we wrote": rebuilding or backfilling an older
    edition must compare against what came before *it*, not against whatever
    happens to be newest on disk.
    """
    key = sources.edition_sort_key(edition)
    earlier = [p for p in existing_editions(register_slug) if sources.edition_sort_key(edition_of(p)) < key]
    if not earlier:
        return None
    return read_snapshot(earlier[-1])


def diff(current: dict, previous: dict | None) -> dict:
    """Agreement-version level changes between two editions."""
    if not previous:
        return {
            "comparable": False,
            "reason": "first-edition",
            "previous_edition": None,
            "added": [],
            "amended": [],
            "removed": [],
        }
    if fingerprint_version(current) != fingerprint_version(previous):
        # Comparing across rule changes would mark every version amended, which
        # is worse than saying nothing: it looks like a real event.
        return {
            "comparable": False,
            "reason": "fingerprint-rules-changed",
            "previous_edition": previous["edition"],
            "previous_fingerprint_version": fingerprint_version(previous),
            "fingerprint_version": fingerprint_version(current),
            "added": [],
            "amended": [],
            "removed": [],
        }

    old, new = previous["versions"], current["versions"]
    old_bases = {v["base"] for v in old.values()}

    added, amended = [], []
    for reference, version in new.items():
        if reference in old:
            if _digest(old[reference]) != _digest(version):
                amended.append(
                    {
                        "reference": reference,
                        **version,
                        "fields": changed_fields(old[reference], version),
                    }
                )
            continue
        added.append(
            {
                "reference": reference,
                **version,
                # A new version of an agreement we already knew about is a renewal,
                # not a brand new data release.
                "kind": "renewal" if version["base"] in old_bases else "new",
            }
        )
    removed = [{"reference": r, **v} for r, v in old.items() if r not in new]

    key = lambda item: (item["org"].lower(), item["reference"])
    return {
        "comparable": True,
        "reason": "",
        "previous_edition": previous["edition"],
        "added": sorted(added, key=key),
        "amended": sorted(amended, key=key),
        "removed": sorted(removed, key=key),
    }


def history_index(register_slug: str) -> dict[str, dict]:
    """When each agreement and each of its versions appeared or changed.

    Every edition's fingerprints are committed, so this reaches back over the
    whole archive even though only the newest edition keeps a full extract.
    Reading all of them costs about a second.

    Returns `{base_reference: {"first_edition", "first_is_earliest", "events"}}`
    with one event per edition in which something happened, oldest first so it
    reads as a timeline under the "first listed" line. Events are grouped by
    edition rather than one per version: NHS England restates every version of
    an agreement at once often enough that the ungrouped list runs to sixteen
    near-identical lines for a single edition's edit.

    An agreement present in the earliest edition we hold may well be older than
    that, so `first_is_earliest` marks the ones whose start we cannot see.
    """
    snapshots = [read_snapshot(path) for path in existing_editions(register_slug)]
    if not snapshots:
        return {}
    earliest = snapshots[0]["edition"]

    index: dict[str, dict] = {}
    previous: dict[str, dict] = {}
    for snapshot in snapshots:
        edition, versions = snapshot["edition"], snapshot["versions"]
        touched: dict[str, dict] = {}

        def event(base: str, kind: str, reference: str, fields: list[str] | None = None) -> None:
            entry = touched.setdefault(
                base, {"edition": edition, "added": [], "amended": [], "removed": [], "fields": []}
            )
            entry[kind].append({"reference": reference, "fields": fields or []})

        for reference, version in versions.items():
            base = version["base"]
            index.setdefault(
                base,
                {"first_edition": edition, "first_is_earliest": edition == earliest, "events": []},
            )
            if reference not in previous:
                event(base, "added", reference)
            elif _digest(previous[reference]) != _digest(version):
                # Naming the fields is the difference between "this was edited"
                # and "the data controller was changed" — the second is what a
                # reader came for, and the register itself never says it.
                event(base, "amended", reference, changed_fields(previous[reference], version))
        for reference, version in previous.items():
            if reference not in versions and version["base"] in index:
                event(version["base"], "removed", reference)

        for base, entry in touched.items():
            for kind in ("added", "amended", "removed"):
                entry[kind].sort(key=lambda item: item["reference"])
            # The union across the edition's amendments, for a one-line summary
            # when several versions were restated together.
            entry["fields"] = sorted({f for item in entry["amended"] for f in item["fields"]})
            index[base]["events"].append(entry)
        previous = versions

    for entry in index.values():
        entry["amendments"] = sum(len(e["amended"]) for e in entry["events"])
        # The edition an agreement first appears in always produces an "added"
        # event, which repeats the "first listed" line the page already shows.
        # Fold its references into that line and drop the event, so the page
        # does not print the same edition twice in a row. An edition that also
        # amended or removed something is left alone: it has more to say.
        first = [e for e in entry["events"] if e["edition"] == entry["first_edition"]]
        if first and not (first[0]["amended"] or first[0]["removed"]):
            entry["first_versions"] = [item["reference"] for item in first[0]["added"]]
            entry["events"].remove(first[0])
        else:
            entry["first_versions"] = []
    return index
