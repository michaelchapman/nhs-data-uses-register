"""Add a downloaded register workbook to the committed facts store.

    python -m pipeline.ingest data/raw/datausesregister_august2026.xlsx
    python -m pipeline.ingest data/raw/*.xlsx            # backfill the archive

NHS England's WAF blocks automated downloads (see ``sources``), so workbooks are
fetched by hand from the register page and its release archive, dropped in
``data/raw/`` — which is gitignored — and ingested here. This records what each
edition said in ``data/facts`` (see ``facts``), which is what the site is built
from, and the workbook's checksum in that store's manifest.

Re-running on a file already ingested is safe and writes nothing new.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from pathlib import Path

from . import changes
from . import facts
from . import sources

ROOT = Path(__file__).resolve().parent.parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workbooks", nargs="+", type=Path, help="downloaded .xlsx files")
    parser.add_argument(
        "--register",
        help="register slug; inferred from each filename when omitted",
    )
    parser.add_argument(
        "--source-url",
        help="the URL this workbook came from; derived from the filename when omitted",
    )
    return parser.parse_args(argv)


def resolve_register(path: Path, override: str | None) -> sources.Register:
    if override:
        return sources.registers(override)[0]
    register = sources.register_for_filename(path.stem)
    if register is None:
        raise SystemExit(
            f"{path.name}: cannot tell which register this is. Pass --register, "
            "or rename it to the published filename (e.g. datausesregister_july2026.xlsx)."
        )
    if not register.enabled:
        raise SystemExit(
            f"{path.name} belongs to {register.slug}, which extract.py does not read yet."
        )
    return register


def ingest_one(path: Path, register: sources.Register, source_url: str | None) -> dict:
    """Extract one workbook, record its facts, and return its manifest entry."""
    from .extract import extract

    edition = sources.parse_edition(path.stem)
    payload = path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    ingested = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    url = source_url or sources.asset_url(path.name)

    print(f"{path.name} ({edition}, {len(payload) / 1e6:.1f} MB)")
    data = extract(payload)
    if not data["agreements"]:
        raise SystemExit(
            f"  {path.name}: no agreements found. The sheet layout may differ in this "
            "edition — check the workbook's sheet and column names against extract.py."
        )
    counts = {
        "agreements": len(data["agreements"]),
        "agreement_versions": sum(len(a["versions"]) for a in data["agreements"]),
        "organisations": len(data["organisations"]),
        "datasets": len(data["datasets"]),
    }
    print(
        f"  {counts['agreements']:,} agreements, "
        f"{counts['organisations']:,} organisations, {counts['datasets']:,} datasets"
    )

    versions_by_base = {a["base_reference"]: a["versions"] for a in data["agreements"]}
    recorded = facts.append_edition(register.slug, edition, versions_by_base)
    print(
        f"  facts -> {recorded['new_states']:,} new version states in "
        f"{recorded['files_written']:,} agreement file(s), "
        f"{recorded['new_released_files']:,} newly released file(s)"
    )
    if recorded["redescribed_files"]:
        print(
            f"  note: {recorded['redescribed_files']:,} released file(s) described differently "
            "than before; both descriptions are kept, and each edition reads back the one it "
            "reported. Usually a dataset the register relabelled."
        )
    if recorded["withdrawn_files"]:
        print(
            f"  note: {recorded['withdrawn_files']:,} released file(s) no longer listed; "
            "they are dropped from this edition on."
        )

    return {
        "edition": edition,
        "published": sources.edition_published(edition),
        "source_file": path.name,
        "source_url": url,
        "sha256": digest,
        "bytes": len(payload),
        "ingested": ingested,
        "counts": counts,
    }


def report_changes(register_slug: str, edition: str) -> None:
    """What this edition changed against the one before it."""
    result = changes.diff(register_slug, edition)
    if not result["comparable"]:
        return
    print(
        f"  vs {result['previous_edition']}: +{len(result['added'])} added, "
        f"~{len(result['amended'])} amended, -{len(result['removed'])} removed"
        + (f" (spans {len(result['skipped']) + 1} months)" if result["skipped"] else "")
    )


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    missing = [p for p in args.workbooks if not p.is_file()]
    if missing:
        raise SystemExit("not found: " + ", ".join(str(p) for p in missing))
    if args.source_url and len(args.workbooks) > 1:
        raise SystemExit("--source-url applies to a single workbook")

    # Oldest first, so an edition's changes are reported against the one
    # actually published before it, and a file's `first edition` means the
    # earliest edition that reported it.
    ordered = sorted(args.workbooks, key=lambda p: sources.edition_sort_key(sources.parse_edition(p.stem)))

    registers: set[str] = set()
    for path in ordered:
        register = resolve_register(path, args.register)
        entry = ingest_one(path, register, args.source_url)
        facts.upsert(register.slug, entry)
        report_changes(register.slug, entry["edition"])
        registers.add(register.slug)

    for slug in sorted(registers):
        print(f"manifest -> {relative(facts.manifest_path(slug))}")


if __name__ == "__main__":
    main()
