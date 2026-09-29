"""Render the site from the committed facts store.

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
from . import changes as changes_module
from . import facts
from . import sources
from .references import version_key
from .rules import Rules

ROOT = Path(__file__).resolve().parent.parent
# Where the site is published: a custom domain, served from its root.
DEFAULT_SITE_URL = "https://healthdatauses.uk"
# Empty means the site is served at the root of its domain, which is what a local
# preview and the custom domain both want. Set SITE_BASE_PATH only to serve it
# under a subpath, as GitHub project pages at <owner>.github.io/<repo>/ would.
DEFAULT_BASE_PATH = ""
REPO_URL = "https://github.com/michaelchapman/nhs-data-uses-register"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--register", default="data-uses-register", help="register slug to build")
    parser.add_argument("--edition", help="edition to build (default: the newest in the store)")
    parser.add_argument("--workbook", type=Path, help="build straight from a local .xlsx; writes nothing to data/")
    parser.add_argument("--output", type=Path, default=ROOT / "_site", help="output directory")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--base-path", default=os.environ.get("SITE_BASE_PATH", DEFAULT_BASE_PATH))
    return parser.parse_args()


def from_store(register, edition: str | None, rules: Rules | None = None) -> tuple[dict, str, dict]:
    """`(data, edition, manifest_entry)` for the edition we are building.

    The review tools call this too, to check their files against the newest
    edition; without `rules` it reads the alias, lineage and exclusion files.
    """
    rules = rules or Rules.load()
    edition = edition or facts.latest_edition(register.slug)
    if not edition:
        raise SystemExit(
            f"nothing ingested for {register.slug}.\n"
            "Download a workbook from the register page and ingest it:\n"
            "    python -m pipeline.ingest data/raw/<workbook>.xlsx\n"
            "See docs/manual-updates.md."
        )
    data = facts.read_extract(register.slug, edition, rules)
    # Agreements and versions earlier editions listed and this one does not,
    # so a page once published keeps its URL. See `facts.read_archive`.
    data["archived"], dropped = facts.read_archive(register.slug, edition, rules)
    for agreement in data["agreements"]:
        agreement["dropped_versions"] = dropped.get(agreement["base_reference"], [])
        # A version numbered after the one now listed as current: the register
        # went back to an older version, and a reader should be told.
        current = version_key(agreement["latest"]["version"])
        agreement["later_dropped"] = [
            v for v in agreement["dropped_versions"] if version_key(v["version"]) > current
        ]
    entry = facts.manifest_entry(register.slug, edition) or {}
    return data, edition, entry


def from_workbook(path: Path, register, rules: Rules) -> tuple[dict, str, dict]:
    from .extract import extract

    edition = sources.parse_edition(path.stem)
    print(f"building straight from {path} (edition {edition}); not ingesting")
    return (
        extract(path.read_bytes(), rules),
        edition,
        {"source_file": path.name, "source_url": sources.asset_url(path.name)},
    )


def main() -> None:
    args = parse_args()
    register = sources.registers(args.register)[0]
    # The alias, lineage and exclusion files, read once for the whole build.
    rules = Rules.load()

    if args.workbook:
        data, edition, entry = from_workbook(args.workbook, register, rules)
    else:
        data, edition, entry = from_store(register, args.edition, rules)
    print(
        f"{edition}: {len(data['agreements']):,} agreements, "
        f"{len(data['organisations']):,} organisations, {len(data['datasets']):,} datasets"
    )

    source_url = entry.get("source_url", "")
    ingested = entry.get("ingested") or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    # A `--workbook` build writes nothing: it is a one-off, and must not leave
    # anything behind in a directory that is committed. What changed between
    # editions comes from the facts store, so a workbook that has not been
    # ingested has nothing to be compared with, and it shows none of the
    # store's editions either: their timelines and changes pages describe a
    # history this workbook is not part of.
    held = facts.stored_editions(register.slug)
    if edition not in held:
        held = []
    # Every edition's changes and every agreement's history, from one read of
    # each agreement in the store.
    if held:
        by_edition_changes, history = changes_module.every_edition(register.slug, rules=rules)
        changes = by_edition_changes[edition]
    else:
        by_edition_changes, history = {}, {}
        changes = changes_module.not_comparable("not-ingested")
    if changes["comparable"]:
        print(
            f"  vs {changes['previous_edition']}: +{len(changes['added'])} added, "
            f"~{len(changes['amended'])} amended, -{len(changes['removed'])} removed"
            + (f" (spans {len(changes['skipped']) + 1} months: {', '.join(changes['skipped'])} not held)"
               if changes["skipped"] else "")
        )

    # The timeline is every edition the facts store holds, which is every
    # edition ingested. Counts come from the manifest, which records them at
    # ingest, so nothing has to be read to describe an edition.
    by_edition = {e["edition"]: e for e in facts.read_manifest(register.slug)}
    known = [
        {
            "edition": held_edition,
            "retrieved": by_edition.get(held_edition, {}).get("ingested", ""),
            # Each edition's own workbook, which its changes page cites.
            "source_file": by_edition.get(held_edition, {}).get("source_file", ""),
            "source_url": by_edition.get(held_edition, {}).get("source_url", ""),
            "counts": by_edition.get(held_edition, {}).get("counts")
            or {"agreement_versions": len(facts.edition_index(register.slug, held_edition))},
        }
        for held_edition in held
    ]
    # A same-shaped changes page for every edition that has one before it, not
    # only the newest.
    changes_history = []
    for held_edition in held[1:]:
        history_entry = by_edition_changes[held_edition]
        history_entry["edition"] = held_edition
        changes_history.append(history_entry)
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
        # What "in term" is judged against: the edition's own date, not the
        # build's, so it doesn't drift as the deployed page ages.
        "as_of": sources.edition_date(edition),
        "editions": known,
        "missing_editions": changes_module.missing_editions(held),
    }

    build_module.build(
        data, meta, changes, args.output, changes_history=changes_history, history=history, rules=rules
    )


if __name__ == "__main__":
    main()
