"""Render the site from the committed edition store.

    python -m pipeline.run                        # build the newest ingested edition
    python -m pipeline.run --edition june2026     # build an older one
    python -m pipeline.run --workbook a.xlsx      # one-off, without ingesting

Editions get into the store with `python -m pipeline.ingest`; workbooks are
downloaded by hand because NHS England's WAF blocks automated requests. See
docs/manual-updates.md.

Run from the repository root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

from . import build as build_module
from . import editions as editions_module
from . import snapshot as snapshot_module
from . import sources

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SITE_URL = "https://michaelchapman.github.io"
# Empty means the site is served at the root of its domain, which is what a local
# preview and a custom domain both want. GitHub project pages live under
# /<repo>/, so the deploy workflow sets SITE_BASE_PATH to match.
DEFAULT_BASE_PATH = ""
REPO_URL = "https://github.com/michaelchapman/nhs-data-uses-register"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--register", default="data-uses-register", help="register slug to build")
    parser.add_argument("--edition", help="edition to build (default: the newest in the store)")
    parser.add_argument("--workbook", type=Path, help="build straight from a local .xlsx, without ingesting")
    parser.add_argument("--output", type=Path, default=ROOT / "_site", help="output directory")
    parser.add_argument("--no-snapshot", action="store_true", help="do not write an edition fingerprint")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--base-path", default=os.environ.get("SITE_BASE_PATH", DEFAULT_BASE_PATH))
    return parser.parse_args()


def from_store(register, edition: str | None) -> tuple[dict, str, dict]:
    """`(data, edition, manifest_entry)` for the edition we are building."""
    edition = edition or editions_module.latest_edition(register.slug)
    if not edition:
        raise SystemExit(
            f"nothing ingested for {register.slug}.\n"
            "Download a workbook from the register page and ingest it:\n"
            "    python -m pipeline.ingest data/raw/<workbook>.xlsx\n"
            "See docs/manual-updates.md."
        )
    data = editions_module.read_extract(register.slug, edition)
    entry = editions_module.manifest_entry(register.slug, edition) or {}
    return data, edition, entry


def from_workbook(path: Path, register) -> tuple[dict, str, dict]:
    from .extract import extract

    edition = sources.parse_edition(path.stem)
    print(f"building straight from {path} (edition {edition}); not ingesting")
    return (
        extract(path.read_bytes()),
        edition,
        {"source_file": path.name, "source_url": sources.asset_url(path.name)},
    )


def main() -> None:
    args = parse_args()
    register = sources.registers(args.register)[0]

    if args.workbook:
        data, edition, entry = from_workbook(args.workbook, register)
    else:
        data, edition, entry = from_store(register, args.edition)
    print(
        f"{edition}: {len(data['agreements']):,} agreements, "
        f"{len(data['organisations']):,} organisations, {len(data['datasets']):,} datasets"
    )

    source_url = entry.get("source_url", "")
    ingested = entry.get("ingested") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    current = snapshot_module.load_snapshot(register.slug, edition)
    if current is None:
        current = snapshot_module.build_snapshot(data, register.slug, edition, source_url, ingested)
        if not args.no_snapshot:
            print(f"  snapshot -> {snapshot_module.write_snapshot(current)}")
    stored_version = snapshot_module.fingerprint_version(current)
    if stored_version < snapshot_module.FINGERPRINT_VERSION:
        print(
            f"  warning: the {edition} fingerprint was written under rules v{stored_version}; "
            f"this code writes v{snapshot_module.FINGERPRINT_VERSION}. Its amendment counts are "
            "whatever those older rules produced. Re-ingest the archive to refresh them "
            "(docs/manual-updates.md lists what each version changed).",
            file=sys.stderr,
        )

    changes = snapshot_module.diff(current, snapshot_module.previous_snapshot(register.slug, edition))
    if changes["comparable"]:
        print(
            f"  vs {changes['previous_edition']}: +{len(changes['added'])} added, "
            f"~{len(changes['amended'])} amended, -{len(changes['removed'])} removed"
        )
    elif changes.get("reason") == "fingerprint-rules-changed":
        print(
            f"  vs {changes['previous_edition']}: not compared — that edition was fingerprinted "
            f"under rules v{changes['previous_fingerprint_version']} and this one under "
            f"v{changes['fingerprint_version']}. Every digest differs between rule versions, so a "
            "comparison would report the whole register as amended. Re-ingest both editions.",
            file=sys.stderr,
        )

    # The timeline is every edition we hold a fingerprint for, which reaches
    # further back than the manifest: fingerprints predate the edition store,
    # and a fingerprints-only backfill writes no manifest extract.
    by_edition = {e["edition"]: e for e in editions_module.read_manifest(register.slug)}
    fingerprints = [snapshot_module.read_snapshot(p) for p in snapshot_module.existing_editions(register.slug)]
    known = [
        {
            "edition": fp["edition"],
            "retrieved": by_edition.get(fp["edition"], {}).get("ingested") or fp.get("retrieved", ""),
            "counts": fp["counts"],
        }
        for fp in fingerprints
    ]
    # A same-shaped changes page for every edition that has one before it, not
    # only the newest — the fingerprints (unlike the full extract) go back over
    # the whole backfilled archive, so this doesn't need to wait for anything.
    changes_history = []
    for i in range(1, len(fingerprints)):
        entry = snapshot_module.diff(fingerprints[i], fingerprints[i - 1])
        entry["edition"] = fingerprints[i]["edition"]
        changes_history.append(entry)
    meta = {
        "site_name": "NHS Data Access Explorer",
        "site_url": args.site_url.rstrip("/"),
        "base_path": args.base_path.rstrip("/"),
        "repo_url": REPO_URL,
        "register": register.slug,
        "register_name": register.name,
        "edition": edition,
        # When we ingested this edition, not when the build ran: the site is only
        # as current as the last workbook someone added by hand.
        "retrieved": ingested,
        "source_url": source_url,
        "source_file": entry.get("source_file", ""),
        "source_page": sources.LANDING_PAGE,
        "archive_page": sources.ARCHIVE_PAGE,
        "today": dt.date.today().isoformat(),
        "editions": known,
    }

    # Every edition's fingerprints are committed, so an agreement's history
    # reaches back over the whole archive even though only the newest edition
    # keeps a full extract.
    history = snapshot_module.history_index(register.slug)
    build_module.build(
        data, meta, changes, args.output, changes_history=changes_history, history=history
    )


if __name__ == "__main__":
    main()
