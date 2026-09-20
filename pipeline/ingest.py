"""Add a downloaded register workbook to the committed edition store.

    python -m pipeline.ingest data/raw/datausesregister_august2026.xlsx
    python -m pipeline.ingest data/raw/*.xlsx            # backfill the archive

NHS England's WAF blocks automated downloads (see ``sources``), so workbooks are
fetched by hand from the register page and its release archive, dropped in
``data/raw/`` — which is gitignored — and ingested here. This writes the small
files that *are* committed: a fingerprint for every edition, and a full extract
for the newest one — one file per agreement — which is what the site is built from.

Re-running on a file already ingested is safe; it overwrites in place.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import sys
from pathlib import Path

from . import editions as editions_module
from . import snapshot as snapshot_module
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
    parser.add_argument(
        "--fingerprints-only",
        action="store_true",
        help="write fingerprints but no full extract (backfilling history alone)",
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


def ingest_one(
    path: Path, register: sources.Register, source_url: str | None
) -> tuple[dict, dict]:
    """Extract one workbook and write its fingerprint.

    Returns `(manifest_entry, extracted_data)`.
    """
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
    print(
        f"  {len(data['agreements']):,} agreements, "
        f"{len(data['organisations']):,} organisations, {len(data['datasets']):,} datasets"
    )

    current = snapshot_module.build_snapshot(data, register.slug, edition, url, ingested)
    previous = snapshot_module.previous_snapshot(register.slug, edition)
    changes = snapshot_module.diff(current, previous)
    if changes["comparable"]:
        print(
            f"  vs {changes['previous_edition']}: +{len(changes['added'])} added, "
            f"~{len(changes['amended'])} amended, -{len(changes['removed'])} removed"
        )
    elif changes.get("reason") == "fingerprint-rules-changed":
        # The common case for this is ingesting one new edition after the
        # fingerprint rules changed, while the rest of the archive still holds
        # digests from the old ones. Nothing is wrong with either file; they
        # simply cannot be compared until both sides agree.
        print(
            f"  vs {changes['previous_edition']}: not compared — fingerprint rules "
            f"v{changes['previous_fingerprint_version']} vs v{changes['fingerprint_version']}. "
            "Re-ingest the whole archive so every edition uses the current rules:\n"
            "    python -m pipeline.ingest data/raw/*.xlsx",
            file=sys.stderr,
        )
    print(f"  fingerprint -> {relative(snapshot_module.write_snapshot(current))}")

    return {
        "edition": edition,
        "published": sources.edition_published(edition),
        "source_file": path.name,
        "source_url": url,
        "sha256": digest,
        "bytes": len(payload),
        "ingested": ingested,
        "counts": current["counts"],
        "has_full_extract": False,
    }, data


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

    # Oldest first, so each edition's diff compares against the one before it.
    ordered = sorted(args.workbooks, key=lambda p: sources.edition_sort_key(sources.parse_edition(p.stem)))

    # Only the newest edition of each register keeps a full extract, and
    # `ordered` runs oldest first, so the last one seen for a register is the
    # one to write. Holding every extract until the end instead — which is what
    # this used to do — costs 393 MB each: a 19-workbook backfill retained
    # about 7.5 GB, and swapped or died on a smaller machine. Keeping just the
    # latest per register bounds it at roughly two.
    latest: dict[str, tuple[dict, dict]] = {}
    for path in ordered:
        register = resolve_register(path, args.register)
        entry, data = ingest_one(path, register, args.source_url)
        editions_module.upsert(register.slug, entry)
        # Replacing the entry releases the previous edition's extract.
        latest[register.slug] = (entry, data)

    if args.fingerprints_only:
        print("fingerprints only; no full extract written")
        for slug in latest:
            # Re-ingesting rewrote the manifest entry; keep it saying which
            # edition the store still holds an extract for.
            if editions_module.latest_edition(slug):
                editions_module.mark_full_extract(slug, editions_module.latest_edition(slug))
        return

    for slug, (newest, data) in latest.items():
        held = editions_module.latest_edition(slug)
        if held and sources.edition_sort_key(newest["edition"]) < sources.edition_sort_key(held):
            # The store keeps one extract, and it should be the newest.
            print(
                f"not replacing the {held} extract with the older {newest['edition']}; "
                "its fingerprint was written"
            )
            editions_module.mark_full_extract(slug, held)
            continue
        directory = editions_module.write_extract(slug, newest["edition"], data)
        print(f"extract -> {relative(directory)}/ ({len(data['agreements']):,} agreements, edition {newest['edition']})")
        newest["has_full_extract"] = True
        editions_module.upsert(slug, newest)
        # Only the newest edition keeps an extract; the manifest says which.
        editions_module.mark_full_extract(slug, newest["edition"])
        print(f"manifest -> {relative(editions_module.manifest_path(slug))}")


if __name__ == "__main__":
    main()
