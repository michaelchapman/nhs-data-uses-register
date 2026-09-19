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

from . import sources

SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent / "data" / "snapshots"

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


def _fingerprint(version: dict) -> str:
    fields = {key: version.get(key, "") for key in FINGERPRINTED}
    fields["datasets"] = sorted(d["name"] for d in version["datasets"])
    payload = json.dumps(fields, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_snapshot(data: dict, register_slug: str, edition: str, source_url: str, retrieved: str) -> dict:
    versions = {}
    for agreement in data["agreements"]:
        for version in agreement["versions"]:
            versions[version["reference"]] = {
                "base": agreement["base_reference"],
                "org": agreement["organisation"],
                "title": version["title"],
                "hash": _fingerprint(version),
            }
    return {
        "register": register_slug,
        "edition": edition,
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
        return {"comparable": False, "previous_edition": None, "added": [], "amended": [], "removed": []}

    old, new = previous["versions"], current["versions"]
    old_bases = {v["base"] for v in old.values()}

    added, amended = [], []
    for reference, version in new.items():
        if reference in old:
            if old[reference]["hash"] != version["hash"]:
                amended.append({"reference": reference, **version})
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

        def event(base: str, kind: str, reference: str) -> None:
            entry = touched.setdefault(
                base, {"edition": edition, "added": [], "amended": [], "removed": []}
            )
            entry[kind].append(reference)

        for reference, version in versions.items():
            base = version["base"]
            index.setdefault(
                base,
                {"first_edition": edition, "first_is_earliest": edition == earliest, "events": []},
            )
            if reference not in previous:
                event(base, "added", reference)
            elif previous[reference]["hash"] != version["hash"]:
                event(base, "amended", reference)
        for reference, version in previous.items():
            if reference not in versions and version["base"] in index:
                event(version["base"], "removed", reference)

        for base, entry in touched.items():
            for kind in ("added", "amended", "removed"):
                entry[kind].sort()
            index[base]["events"].append(entry)
        previous = versions

    for entry in index.values():
        entry["amendments"] = sum(len(e["amended"]) for e in entry["events"])
        # The edition an agreement first appears in always produces an "added"
        # event, which duplicates the "first listed" line the page already
        # shows. Drop it, keeping any later version added in the same edition.
        first = [e for e in entry["events"] if e["edition"] == entry["first_edition"]]
        if first and not (first[0]["amended"] or first[0]["removed"]) and len(first[0]["added"]) == 1:
            entry["events"].remove(first[0])
    return index
