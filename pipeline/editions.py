"""The committed edition store: what the site is built from.

Workbooks cannot be fetched in CI (see ``sources``), so the build input lives in
git instead. Two kinds of file, both gzipped:

``data/editions/<register>/<edition>.json.gz``
    The full normalised extract — everything needed to render the site for that
    edition. Only the newest edition normally needs one; older editions are
    reachable through their fingerprints alone.

``data/snapshots/<register>/<edition>.json.gz``
    The per-edition fingerprint, written by ``snapshot``. Small enough to keep
    one for every edition in NHS England's archive.

``data/editions/<register>/manifest.json`` indexes them: one entry per edition
we have ingested, with the checksum of the workbook it came from.

Only ``agreements`` is stored. ``organisations`` and ``datasets`` are pure
functions of it, and ``agreement["latest"]`` aliases a dict already inside
``agreement["versions"]`` — serialising them would duplicate most of the file.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from . import sources

EDITION_ROOT = Path(__file__).resolve().parent.parent / "data" / "editions"
MANIFEST_NAME = "manifest.json"
# How many editions keep a full extract. The site renders one edition at a time;
# a second is a cheap safety net for rebuilding the previous month.
DEFAULT_KEEP = 1


def register_dir(register_slug: str) -> Path:
    path = EDITION_ROOT / register_slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def extract_path(register_slug: str, edition: str) -> Path:
    return register_dir(register_slug) / f"{edition}.json.gz"


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


def write_extract(register_slug: str, edition: str, data: dict) -> Path:
    path = extract_path(register_slug, edition)
    payload = {"register": register_slug, "edition": edition, "agreements": data["agreements"]}
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=9) as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True, default=_no_aliases)
    return path


def _no_aliases(value):
    raise TypeError(f"edition extracts must be plain JSON, got {type(value).__name__}")


def read_extract(register_slug: str, edition: str) -> dict:
    path = extract_path(register_slug, edition)
    if not path.exists():
        raise SystemExit(
            f"no full extract for the {edition} edition of {register_slug}.\n"
            f"Expected {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}. "
            "Ingest the workbook first:\n"
            f"    python -m pipeline.ingest data/raw/<workbook>.xlsx"
        )
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return rehydrate(json.load(handle)["agreements"])


def rehydrate(agreements: list[dict]) -> dict:
    """Rebuild the derived views that `write_extract` deliberately dropped."""
    from . import aliases as aliases_module
    from .extract import _group_datasets, _group_organisations, resplit_list, slugify

    alias_map = aliases_module.load_map()
    for agreement in agreements:
        # Re-splitting is idempotent (a string with none of the separators just
        # comes back as itself), so this is safe to apply unconditionally rather
        # than tracking whether a given extract predates a particular splitting
        # rule — a committed extract whose controllers were split by an older,
        # narrower rule gets the current rule applied every time it's read.
        for version in agreement["versions"]:
            version["controllers"] = resplit_list(version["controllers"])
        agreement["controllers"] = agreement["versions"][-1]["controllers"]
        agreement["latest"] = agreement["versions"][-1]
        # Always recomputed, never backfilled-if-missing: unlike the fields
        # below, organisation_slug and controller_slugs need to reflect the
        # *current* data/organisation-aliases.json on every read, not whatever
        # was true at ingest time — otherwise reviewing and adding an alias
        # would need a re-ingest to take effect, rather than just a rebuild.
        agreement["organisation_slug"] = slugify(aliases_module.resolve(agreement["organisation"], alias_map))
        agreement["controller_slugs"] = [slugify(aliases_module.resolve(c, alias_map)) for c in agreement["controllers"]]
        # An extract written before a field existed won't have it. Backfilling
        # here — from data the extract does store — means an older committed
        # extract keeps working without a re-ingest, as long as the field is a
        # deterministic function of what's already there.
        if "first_start_known" not in agreement:
            earliest_version = agreement["versions"][0].get("version", "")
            agreement["first_start_known"] = earliest_version in ("", "1", "1.0")
        if "legal_bases" not in agreement:
            agreement["legal_bases"] = sorted(
                {
                    d["legal_basis"]
                    for v in agreement["versions"]
                    for d in v["datasets"]
                    if d.get("legal_basis")
                }
            )
    return {
        "agreements": agreements,
        "organisations": _group_organisations(agreements),
        "datasets": _group_datasets(agreements),
    }


def stored_editions(register_slug: str) -> list[str]:
    """Editions with a full extract on disk, oldest first."""
    editions = [p.name[: -len(".json.gz")] for p in register_dir(register_slug).glob("*.json.gz")]
    return sorted(editions, key=sources.edition_sort_key)


def latest_edition(register_slug: str) -> str | None:
    """The newest edition we can actually build — one with a full extract."""
    editions = stored_editions(register_slug)
    return editions[-1] if editions else None


def prune_extracts(register_slug: str, keep: int = DEFAULT_KEEP) -> list[str]:
    """Drop all but the newest `keep` full extracts. Fingerprints are untouched."""
    editions = stored_editions(register_slug)
    dropped = editions[: max(0, len(editions) - keep)] if keep >= 0 else []
    for edition in dropped:
        extract_path(register_slug, edition).unlink()
    if dropped:
        remaining = set(stored_editions(register_slug))
        entries = read_manifest(register_slug)
        for entry in entries:
            entry["has_full_extract"] = entry["edition"] in remaining
        write_manifest(register_slug, entries)
    return dropped
