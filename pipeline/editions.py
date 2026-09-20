"""The committed edition store: what the site is built from.

Workbooks cannot be fetched in CI (see ``sources``), so the build input lives in
git instead. Two kinds of file:

``data/editions/<register>/agreements/<slug>.json``
    The newest edition's extract, one uncompressed file per agreement, holding
    that agreement's versions and nothing derived from them. This shape is
    deliberate. Consecutive editions restate almost every version's prose, and
    git can only store that cheaply as a delta between two copies of the same
    file: a gzipped extract has no such delta and cost about 30 MB per edition,
    where these files cost well under 1 MB. Keeping one file per agreement also
    makes ``git log`` on a file that agreement's history.

``data/editions/<register>/extract.json``
    Which edition the files above are. Only the newest is stored; an older one
    is rebuilt from its workbook, or from an earlier commit.

``data/snapshots/<register>/<edition>.json.gz``
    The per-edition fingerprint, written by ``snapshot``. Small enough to keep
    one for every edition in NHS England's archive.

``data/editions/<register>/manifest.json`` indexes what has been ingested: one
entry per edition, with the checksum of the workbook it came from.

Only each agreement's versions are stored. Everything else on an agreement, and
the organisation and dataset views, is a function of them (`extract.assemble`),
so it is rebuilt on every read and is never stale against the alias files.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from . import sources

EDITION_ROOT = Path(__file__).resolve().parent.parent / "data" / "editions"
MANIFEST_NAME = "manifest.json"
EXTRACT_META = "extract.json"
AGREEMENTS_DIR = "agreements"


def register_dir(register_slug: str) -> Path:
    path = EDITION_ROOT / register_slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def agreements_dir(register_slug: str) -> Path:
    return register_dir(register_slug) / AGREEMENTS_DIR


def extract_meta_path(register_slug: str) -> Path:
    return register_dir(register_slug) / EXTRACT_META


def manifest_path(register_slug: str) -> Path:
    return register_dir(register_slug) / MANIFEST_NAME


def read_manifest(register_slug: str) -> list[dict]:
    """Manifest entries, oldest edition first."""
    path = manifest_path(register_slug)
    if not path.exists():
        return []
    entries = json.loads(path.read_text()).get("editions", [])
    return sorted(entries, key=lambda e: sources.edition_sort_key(e["edition"]))


def write_manifest(register_slug: str, entries: list[dict]) -> Path:
    entries = sorted(entries, key=lambda e: sources.edition_sort_key(e["edition"]))
    path = manifest_path(register_slug)
    path.write_text(
        json.dumps({"register": register_slug, "editions": entries}, indent=2, sort_keys=True) + "\n"
    )
    return path


def upsert(register_slug: str, entry: dict) -> list[dict]:
    """Add or replace the manifest entry for `entry["edition"]`."""
    entries = [e for e in read_manifest(register_slug) if e["edition"] != entry["edition"]]
    entries.append(entry)
    write_manifest(register_slug, entries)
    return entries


def manifest_entry(register_slug: str, edition: str) -> dict | None:
    for entry in read_manifest(register_slug):
        if entry["edition"] == edition:
            return entry
    return None


def _agreement_json(agreement: dict) -> str:
    """One agreement as stored: its versions, stable and readable in a diff.

    Indented so a change to one field is one changed line, and sorted so an
    unchanged agreement is byte-identical from one ingest to the next.
    """
    stored = {"base_reference": agreement["base_reference"], "versions": agreement["versions"]}
    return json.dumps(stored, indent=1, sort_keys=True, ensure_ascii=False, default=_no_aliases) + "\n"


def write_extract(register_slug: str, edition: str, data: dict) -> Path:
    """Replace the stored extract with `edition`'s, touching only what changed.

    A file whose content is unchanged is left alone, an agreement no longer in
    the register is removed, and git records the rest as the edition's diff.
    """
    directory = agreements_dir(register_slug)
    directory.mkdir(parents=True, exist_ok=True)
    wanted: dict[str, str] = {}
    for agreement in data["agreements"]:
        name = f"{agreement['slug']}.json"
        if name in wanted:
            raise SystemExit(
                f"two agreements share the file name {name}: "
                f"{agreement['base_reference']} collides with an earlier one"
            )
        wanted[name] = _agreement_json(agreement)
    for path in directory.glob("*.json"):
        if path.name not in wanted:
            path.unlink()
    for name, text in wanted.items():
        path = directory / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
    meta = {"register": register_slug, "edition": edition, "agreements": len(wanted)}
    extract_meta_path(register_slug).write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return directory


def _no_aliases(value):
    raise TypeError(f"edition extracts must be plain JSON, got {type(value).__name__}")


def read_extract(register_slug: str, edition: str) -> dict:
    stored = stored_editions(register_slug)
    if edition not in stored:
        held = f"only the {stored[0]} edition" if stored else "no edition"
        raise SystemExit(
            f"no full extract for the {edition} edition of {register_slug}: the store holds {held}.\n"
            "Build an older edition from its workbook with --workbook, or ingest the workbook:\n"
            f"    python -m pipeline.ingest data/raw/<workbook>.xlsx"
        )
    versions_by_base = {}
    for path in sorted(agreements_dir(register_slug).glob("*.json")):
        stored_agreement = json.loads(path.read_text(encoding="utf-8"))
        versions_by_base[stored_agreement["base_reference"]] = stored_agreement["versions"]
    return rehydrate(versions_by_base)


def rehydrate(versions_by_base: dict[str, list[dict]]) -> dict:
    """Rebuild everything the store leaves out, from each agreement's versions."""
    from .extract import assemble, known_organisation_names, resplit_list, tidy_version

    # The same authoritative list `extract` builds from the workbook, so a
    # rebuild splits controllers the way an ingest does. Re-splitting is
    # idempotent, so an extract written under an older, narrower rule gets the
    # current one applied every time it is read.
    for versions in versions_by_base.values():
        for version in versions:
            tidy_version(version)
    known = known_organisation_names(
        version["organisation"] for versions in versions_by_base.values() for version in versions
    )
    for versions in versions_by_base.values():
        for version in versions:
            version["controllers"] = resplit_list(version["controllers"], known)
    return assemble(versions_by_base)


def stored_editions(register_slug: str) -> list[str]:
    """The edition whose extract is on disk: at most one."""
    path = extract_meta_path(register_slug)
    if not path.exists():
        return []
    return [json.loads(path.read_text())["edition"]]


def latest_edition(register_slug: str) -> str | None:
    """The newest edition we can actually build — the one with a full extract."""
    editions = stored_editions(register_slug)
    return editions[-1] if editions else None


def mark_full_extract(register_slug: str, edition: str) -> None:
    """Record in the manifest that `edition` is the one with a stored extract."""
    entries = read_manifest(register_slug)
    for entry in entries:
        entry["has_full_extract"] = entry["edition"] == edition
    write_manifest(register_slug, entries)
