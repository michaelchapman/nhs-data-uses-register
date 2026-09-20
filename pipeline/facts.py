"""The facts store: what every edition said, kept once.

``editions`` stores the newest edition's text and ``snapshot`` stores a digest
of every other edition, which means history is only ever held as a derivative
of whatever the fingerprint rules were on the day it was written. Changing
those rules costs a re-parse of every workbook. This module stores the text of
every edition instead, so a rules change costs a rebuild.

That is affordable because the register barely changes. Across the 63 editions
held, 263,342 version-entries are only 5,702 distinct (agreement, version)
references and 12,439 distinct records — most of the archive is the present
restated. See ``docs/plan-facts-store.md`` for the measurements.

Three kinds of file:

``data/facts/<register>/agreements/<slug>.json``
    Every version of one agreement, and for each version the distinct states it
    has been published in, oldest first. A version's text is usually fixed once
    published; when the register edits one in place, that is a new state
    appended to the list.

``data/facts/<register>/releases/<slug>.json``
    Every file released under that agreement, keyed by the file reference the
    register issues — unique across all 104,451 rows of the September 2026
    edition — grouped by the version, dataset and channel a row belongs to.

    A file can appear more than once. The register relabels a dataset and every
    release row under it follows: between the July 2021 and September 2026
    editions that happened to 33,841 of 104,451 files. Each description records
    the edition it starts from, and a read takes the newest at or before the
    edition being read, so an edition shows the names it used rather than the
    names in force when the file was first seen.

    Releases are kept apart from the states above because they move every month
    by design: 211 of the 2,330 references with releases changed between the
    August and September 2026 editions alone, and folding them into a version's
    text would append a fresh copy of that agreement's prose every month, for a
    counter. The fingerprints left them out for the same reason.

    Each record carries the `channel` it came through, today always a physical
    file released through DARS. The register says nothing about data accessed
    inside a secure environment or shared onward by a recipient, so a second
    source can be added beside these rather than merged into them. See
    ``docs/plan-release-coverage.md``.

``data/facts/<register>/editions/<edition>.json``
    Which state each version was in that month: ``{reference: state index}``.
    One line per version, so consecutive editions differ in about a hundred of
    5,613 lines and git stores each as a small delta.

The checksum of the workbook each edition came from is not here: it is still
``editions.manifest_path``, written by ``ingest``, and it moves beside these
files when the edition store is retired. It records provenance rather than
register content, so moving it is a file move and never a re-parse.

Four properties this file is responsible for keeping:

*Append-only.* States are appended in first-seen order, so an index, once
written, always means the same record and older edition files stay valid. An
ingest rewrites only the agreements whose text actually changed.

*Nothing is deleted.* An agreement that leaves the register keeps its file and
stops appearing in edition indexes. This is the difference from
``editions.write_extract``, which deletes, and it is how history survives.

*A state is a distinct record, not a verdict.* States are told apart by exact
equality of their canonical JSON — no normalising, no hashing, no rule version
to gate comparisons on. Whether two states differ in a way worth calling an
*amendment* is a question for the build, which may change its mind freely.

*Deterministic.* Ingesting the same editions in the same order twice produces
byte-identical files, so a re-ingest that changed nothing shows an empty diff.

Nothing derived is stored. As with ``editions``, the organisation and dataset
views are rebuilt from the versions on every read (`extract.assemble`), so they
are never stale against the alias files.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import sources
from .extract import FILE_RELEASE, slugify, summarise_releases

FACTS_ROOT = Path(__file__).resolve().parent.parent / "data" / "facts"
AGREEMENTS_DIR = "agreements"
EDITIONS_DIR = "editions"
RELEASES_DIR = "releases"

# Held on the version record rather than repeated in every state, so the two
# can never disagree. `read_edition` puts them back.
VERSION_KEYS = ("reference", "version")

# Kept in the release store instead of in a state, and reattached on the way
# out. See the note on `data/facts/<register>/releases/` above.
RELEASE_KEYS = ("releases", "released_files", "files_released")

# A released file is stored as a row rather than an object: 104,451 of them,
# where an object would spend more bytes on repeating four key names than on
# the facts. The group above it names the reference, dataset and channel.
FILE, MONTH, OPT_OUTS, FIRST_EDITION = range(4)


def register_dir(register_slug: str) -> Path:
    return FACTS_ROOT / register_slug


def agreements_dir(register_slug: str) -> Path:
    return register_dir(register_slug) / AGREEMENTS_DIR


def editions_dir(register_slug: str) -> Path:
    return register_dir(register_slug) / EDITIONS_DIR


def releases_dir(register_slug: str) -> Path:
    return register_dir(register_slug) / RELEASES_DIR


def edition_path(register_slug: str, edition: str) -> Path:
    return editions_dir(register_slug) / f"{edition}.json"


def _dumps(value) -> str:
    """Stable, readable JSON: one field per line, same bytes every time."""
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False, default=_plain_json) + "\n"


def _plain_json(value):
    raise TypeError(f"the facts store holds plain JSON, got {type(value).__name__}")


def canonical_state(version: dict) -> dict:
    """One version as stored: its fields, minus those kept elsewhere.

    `datasets` is sorted by name. Row order in the workbook carries no meaning
    for a set of datasets, and storage should not be sensitive to it — a
    reordered sheet is not a new state.
    """
    skip = VERSION_KEYS + RELEASE_KEYS
    state = {key: value for key, value in version.items() if key not in skip}
    if isinstance(state.get("datasets"), list):
        state["datasets"] = sorted(state["datasets"], key=lambda d: (d.get("name", ""), _key(d)))
    return state


def _key(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=_plain_json)


def _write_if_changed(path: Path, text: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _version_sort_key(record: dict) -> tuple:
    from .extract import _version_key

    return (_version_key(record.get("version", "")), record.get("reference", ""))


def read_agreement(register_slug: str, base_reference: str) -> dict | None:
    """The stored record for one agreement, or `None` if it has never appeared."""
    path = agreements_dir(register_slug) / f"{slugify(base_reference)}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def append_edition(register_slug: str, edition: str, versions_by_base: dict[str, list[dict]]) -> dict:
    """Record what `edition` said, and index which state each version was in.

    Adds a state only where the text differs from every state that version has
    already been published in, so re-recording an edition writes nothing.
    Returns counts for the caller to report.
    """
    directory = agreements_dir(register_slug)
    directory.mkdir(parents=True, exist_ok=True)

    index: dict[str, int] = {}
    counts = {
        "agreements": 0, "versions": 0, "new_agreements": 0, "new_states": 0, "files_written": 0,
        "new_released_files": 0, "release_files_written": 0, "redescribed_files": 0,
        "withdrawn_files": 0,
    }
    seen_slugs: dict[str, str] = {}

    for base_reference, versions in sorted(versions_by_base.items()):
        slug = slugify(base_reference)
        if slug in seen_slugs:
            raise SystemExit(
                f"two agreements share the file name {slug}.json: "
                f"{base_reference} collides with {seen_slugs[slug]}"
            )
        seen_slugs[slug] = base_reference

        path = directory / f"{slug}.json"
        stored = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if stored is None:
            stored = {"base_reference": base_reference, "versions": []}
            counts["new_agreements"] += 1
        records = {record["reference"]: record for record in stored["versions"]}

        for version in versions:
            reference = version["reference"]
            record = records.get(reference)
            if record is None:
                record = {"reference": reference, "version": version.get("version", ""), "states": []}
                records[reference] = record
                stored["versions"].append(record)
            state = canonical_state(version)
            wanted = _key(state)
            for position, existing in enumerate(record["states"]):
                if _key(existing) == wanted:
                    break
            else:
                position = len(record["states"])
                record["states"].append(state)
                counts["new_states"] += 1
            index[reference] = position
            counts["versions"] += 1

        stored["versions"].sort(key=_version_sort_key)
        counts["agreements"] += 1
        if _write_if_changed(path, _dumps(stored)):
            counts["files_written"] += 1

    releases_dir(register_slug).mkdir(parents=True, exist_ok=True)
    _append_releases(register_slug, edition, versions_by_base, counts)
    _write_if_changed(
        edition_path(register_slug, edition),
        _dumps({"edition": edition, "register": register_slug, "versions": index}),
    )
    return counts


def _append_releases(register_slug: str, edition: str, versions_by_base: dict, counts: dict) -> None:
    """Add `edition`'s released files to the stored per-agreement history.

    One record per file reference, which the register issues once and never
    reuses — 104,451 rows in the September 2026 edition, 104,451 distinct
    references — so this is append-only by construction and a file already
    stored is left exactly as it was. A file whose details are later reported
    differently is counted rather than overwritten; a fact should not be
    rewritten on the strength of a disagreement nobody has looked at.
    """
    directory = releases_dir(register_slug)
    for base_reference, versions in sorted(versions_by_base.items()):
        reported = [(v, f) for v in versions for f in v.get("released_files") or []]
        path = directory / f"{slugify(base_reference)}.json"
        if not reported and not path.exists():
            continue
        stored = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {"base_reference": base_reference, "releases": []}
        )
        groups = {(r["reference"], r["dataset"], r["channel"]): r for r in stored["releases"]}
        latest = _latest_observations(stored)
        this_edition = sources.edition_sort_key(edition)

        for version, released in reported:
            key = (version["reference"], released["dataset"], released.get("channel", FILE_RELEASE))
            row = [released["file"], released["month"], released["opt_outs_applied"], edition]
            attributes = _differing_attributes(released, version)
            was = latest.get(released["file"])
            if was is not None and was[1] is not None:
                was_key, was_row, was_attributes = was[1]
                if was_key == key and was_row[:FIRST_EDITION] == row[:FIRST_EDITION] \
                        and was_attributes == attributes:
                    continue
                counts["redescribed_files"] += 1
            else:
                counts["new_released_files"] += 1
            group = groups.get(key)
            if group is None:
                group = {"reference": key[0], "dataset": key[1], "channel": key[2], "files": []}
                groups[key] = group
                stored["releases"].append(group)
            group["files"].append(row)
            if attributes:
                group.setdefault("attributes", {})[released["file"]] = attributes
            latest[released["file"]] = (this_edition, (key, row, attributes))

        # A file this edition stopped reporting. The register does withdraw
        # them — three vanished from DARS-NIC-343380-H5Q9K between the December
        # 2022 and January 2023 editions — and without a note of it every later
        # edition would inherit a release its workbook does not list.
        reported_files = {released["file"] for _, released in reported}
        for file_reference, (seen, description) in sorted(latest.items()):
            if description is not None and file_reference not in reported_files:
                stored.setdefault("withdrawn", []).append([file_reference, edition])
                counts["withdrawn_files"] += 1
        if stored.get("withdrawn"):
            stored["withdrawn"].sort(key=lambda w: (w[0], sources.edition_sort_key(w[1])))

        for group in stored["releases"]:
            group["files"].sort(key=lambda r: (r[FILE], sources.edition_sort_key(r[FIRST_EDITION])))
        stored["releases"].sort(key=lambda r: (r["reference"], r["dataset"], r["channel"]))
        if _write_if_changed(path, _dumps(stored)):
            counts["release_files_written"] += 1


def _latest_observations(stored: dict) -> dict:
    """`{file: (edition, description)}` for each file's newest description.

    The description is `(group key, row, attributes)`, or `None` where the
    newest thing said about the file is that an edition stopped reporting it.
    """
    latest: dict[str, tuple] = {}

    def offer(file_reference: str, edition: str, description) -> None:
        seen = sources.edition_sort_key(edition)
        current = latest.get(file_reference)
        if current is None or seen >= current[0]:
            latest[file_reference] = (seen, description)

    for group in stored["releases"]:
        key = (group["reference"], group["dataset"], group["channel"])
        for row in group["files"]:
            offer(row[FILE], row[FIRST_EDITION], (key, row, group.get("attributes", {}).get(row[FILE], {})))
    for file_reference, edition in stored.get("withdrawn", []):
        offer(file_reference, edition, None)
    return latest


def _differing_attributes(released: dict, version: dict) -> dict:
    """A released file's own attributes, kept only when they cannot be inferred.

    737 of 104,451 rows disagree with the `Datasets` sheet, and storing the
    attributes of every row to record that would quadruple the release store.
    A row that agrees is left out and rebuilt from its dataset on the way back.

    Two cases have to be kept all the same: a row that disagrees, and a row
    whose dataset name the version lists more than once with different
    attributes, where "the same as its dataset" does not name one answer.
    """
    from .extract import _attribute_key, _expected_attributes

    expected = _expected_attributes(version.get("datasets", [])).get(released["dataset"], set())
    attributes = released.get("attributes") or {}
    if len(expected) == 1 and _attribute_key(attributes) in expected:
        return {}
    return attributes


def read_releases(register_slug: str, base_reference: str) -> dict:
    """One agreement's whole release record: its groups and its withdrawals."""
    path = releases_dir(register_slug) / f"{slugify(base_reference)}.json"
    if not path.exists():
        return {"base_reference": base_reference, "releases": [], "withdrawn": []}
    return json.loads(path.read_text(encoding="utf-8"))


def released_files_as_at(stored: dict, edition: str, datasets_by_reference: dict) -> dict:
    """`{version reference: released files}`, in the shape `extract` produces.

    Files first reported by a later edition are left out, so an edition built
    from the store shows the release history that edition actually had rather
    than everything known since.
    """
    from .extract import RELEASE_ATTRIBUTES

    cutoff = sources.edition_sort_key(edition)
    # A file can be described more than once: the register relabels a dataset
    # and every release row under it follows. Each description records the
    # edition it starts from, so the one to use is the newest at or before the
    # edition being read.
    chosen: dict[str, tuple] = {}
    for group in stored["releases"]:
        for row in group["files"]:
            seen = sources.edition_sort_key(row[FIRST_EDITION])
            if seen > cutoff:
                continue
            current = chosen.get(row[FILE])
            if current is None or seen >= current[0]:
                chosen[row[FILE]] = (seen, group, row)
    # An edition that stopped reporting a file drops it from that edition on,
    # unless a later one within the cutoff reported it again.
    for file_reference, edition_withdrawn in stored.get("withdrawn", []):
        seen = sources.edition_sort_key(edition_withdrawn)
        current = chosen.get(file_reference)
        if current is not None and cutoff >= seen >= current[0]:
            del chosen[file_reference]

    by_reference: dict[str, list[dict]] = {}
    for file_reference, (_, group, row) in chosen.items():
        datasets = {d["name"]: d for d in datasets_by_reference.get(group["reference"], [])}
        shared = datasets.get(group["dataset"], {})
        own = group.get("attributes", {}).get(file_reference)
        by_reference.setdefault(group["reference"], []).append({
            "file": file_reference,
            "dataset": group["dataset"],
            "month": row[MONTH],
            "channel": group["channel"],
            "opt_outs_applied": row[OPT_OUTS],
            # Where the file did not disagree with its dataset, its attributes
            # *are* the dataset's; only the exceptions are kept.
            "attributes": own or {key: shared.get(key, "") for key in RELEASE_ATTRIBUTES},
        })
    for released in by_reference.values():
        released.sort(key=lambda f: f["file"])
    return by_reference


def edition_index(register_slug: str, edition: str) -> dict[str, int]:
    """`{version reference: state index}` for one edition."""
    path = edition_path(register_slug, edition)
    if not path.exists():
        raise SystemExit(
            f"no stored facts for the {edition} edition of {register_slug}.\n"
            "Ingest its workbook:\n"
            f"    python -m pipeline.ingest data/raw/<workbook>.xlsx"
        )
    return json.loads(path.read_text(encoding="utf-8"))["versions"]


def read_edition(register_slug: str, edition: str) -> dict[str, list[dict]]:
    """`{base reference: versions}` exactly as `edition` published them.

    The shape `extract.extract` returns for a workbook and `editions.rehydrate`
    expects, so an edition read from here and one parsed from its workbook are
    interchangeable. The releases kept out of the states are put back here, as
    that edition reported them.
    """
    index = edition_index(register_slug, edition)
    versions_by_base: dict[str, list[dict]] = {}
    for path in sorted(agreements_dir(register_slug).glob("*.json")):
        stored = json.loads(path.read_text(encoding="utf-8"))
        versions = []
        for record in stored["versions"]:
            position = index.get(record["reference"])
            if position is None:
                continue
            try:
                state = record["states"][position]
            except IndexError:
                raise SystemExit(
                    f"{path.name} has {len(record['states'])} state(s) for "
                    f"{record['reference']}, but the {edition} edition wants "
                    f"state {position}. The store is inconsistent; re-ingest it."
                ) from None
            version = {**state, "reference": record["reference"], "version": record["version"]}
            # Stored in plain character order, which is deterministic but puts
            # "MRIS - Cause of Death Report" ahead of "Medicines dispensed…".
            # A reader means alphabetical, so present it that way. Sorting again
            # on the way out costs nothing and needs no re-parse to change.
            if isinstance(version.get("datasets"), list):
                version["datasets"] = sorted(
                    version["datasets"], key=lambda d: (d.get("name", "").casefold(), _key(d))
                )
            versions.append(version)
        if not versions:
            continue
        base_reference = stored["base_reference"]
        datasets_by_reference = {v["reference"]: v.get("datasets", []) for v in versions}
        released = released_files_as_at(
            read_releases(register_slug, base_reference), edition, datasets_by_reference
        )
        for version in versions:
            files = released.get(version["reference"], [])
            version["released_files"] = files
            # Summarised against the datasets as *this* edition described them,
            # so a file whose own attributes differ is judged against the
            # dataset record it was released under.
            version["releases"] = summarise_releases(files, version.get("datasets", []))
            version["files_released"] = sum(r["files"] for r in version["releases"])
        versions_by_base[base_reference] = versions
    return versions_by_base


def stored_editions(register_slug: str) -> list[str]:
    """Every edition the store holds, oldest first."""
    directory = editions_dir(register_slug)
    if not directory.exists():
        return []
    editions = [path.stem for path in directory.glob("*.json")]
    return sorted(editions, key=sources.edition_sort_key)


def latest_edition(register_slug: str) -> str | None:
    editions = stored_editions(register_slug)
    return editions[-1] if editions else None
