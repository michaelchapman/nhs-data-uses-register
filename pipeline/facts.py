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

``data/facts/<register>/editions/<edition>.json``
    Which state each version was in that month: ``{reference: state index}``.
    One line per version, so consecutive editions differ in about a hundred of
    5,613 lines and git stores each as a small delta.

``data/facts/<register>/manifest.json``
    Unchanged from ``editions``: the checksum of the workbook each edition came
    from.

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
from .extract import slugify

FACTS_ROOT = Path(__file__).resolve().parent.parent / "data" / "facts"
AGREEMENTS_DIR = "agreements"
EDITIONS_DIR = "editions"

# Held on the version record rather than repeated in every state, so the two
# can never disagree. `read_edition` puts them back.
VERSION_KEYS = ("reference", "version")


def register_dir(register_slug: str) -> Path:
    return FACTS_ROOT / register_slug


def agreements_dir(register_slug: str) -> Path:
    return register_dir(register_slug) / AGREEMENTS_DIR


def editions_dir(register_slug: str) -> Path:
    return register_dir(register_slug) / EDITIONS_DIR


def edition_path(register_slug: str, edition: str) -> Path:
    return editions_dir(register_slug) / f"{edition}.json"


def _dumps(value) -> str:
    """Stable, readable JSON: one field per line, same bytes every time."""
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False, default=_plain_json) + "\n"


def _plain_json(value):
    raise TypeError(f"the facts store holds plain JSON, got {type(value).__name__}")


def canonical_state(version: dict) -> dict:
    """One version as stored: its fields, minus the two kept on the record.

    `datasets` is sorted by name. Row order in the workbook carries no meaning
    for a set of datasets, and storage should not be sensitive to it — a
    reordered sheet is not a new state.
    """
    state = {key: value for key, value in version.items() if key not in VERSION_KEYS}
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
    counts = {"agreements": 0, "versions": 0, "new_agreements": 0, "new_states": 0, "files_written": 0}
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

    _write_if_changed(
        edition_path(register_slug, edition),
        _dumps({"edition": edition, "register": register_slug, "versions": index}),
    )
    return counts


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
    interchangeable.
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
            versions.append({**state, "reference": record["reference"], "version": record["version"]})
        if versions:
            versions_by_base[stored["base_reference"]] = versions
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
