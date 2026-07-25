"""End-to-end build: discover the current register, extract it, render the site.

    python -m pipeline.run                     # fetch the live register and build
    python -m pipeline.run --workbook a.xlsx   # build from a local copy
    python -m pipeline.run --no-snapshot       # don't record this edition

Run from the repository root.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path

from . import build as build_module
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--register", default="data-uses-register", help="register slug to build")
    parser.add_argument("--workbook", type=Path, help="build from a local .xlsx instead of downloading")
    parser.add_argument("--edition", help="edition label to use with --workbook (e.g. july2026)")
    parser.add_argument("--output", type=Path, default=ROOT / "_site", help="output directory")
    parser.add_argument("--cache", type=Path, default=ROOT / "data" / "raw", help="where downloads are kept")
    parser.add_argument("--no-snapshot", action="store_true", help="do not write an edition fingerprint")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", DEFAULT_SITE_URL))
    parser.add_argument("--base-path", default=os.environ.get("SITE_BASE_PATH", DEFAULT_BASE_PATH))
    return parser.parse_args()


def obtain_workbook(args, register) -> tuple[bytes, str, str]:
    """Return `(bytes, source_url, edition)` from the network or a local file."""
    if args.workbook:
        edition = args.edition or args.workbook.stem.split("_")[-1].lower()
        print(f"using local workbook {args.workbook} (edition {edition})")
        return args.workbook.read_bytes(), args.workbook.as_uri(), edition

    url, edition = sources.discover(register)
    args.cache.mkdir(parents=True, exist_ok=True)
    cached = args.cache / f"{register.slug}_{edition}.xlsx"
    if cached.exists():
        print(f"using cached download {cached} (edition {edition})")
        return cached.read_bytes(), url, edition

    print(f"downloading {url}")
    payload = sources.fetch(url)
    cached.write_bytes(payload)
    print(f"  {len(payload) / 1e6:.1f} MB -> {cached}")
    return payload, url, edition


def main() -> None:
    args = parse_args()
    register = sources.registers(args.register)[0]

    payload, source_url, edition = obtain_workbook(args, register)
    retrieved = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    print("extracting…")
    data = extract_register(payload)
    print(
        f"  {len(data['agreements']):,} agreements, "
        f"{len(data['organisations']):,} organisations, {len(data['datasets']):,} datasets"
    )

    current = snapshot_module.build_snapshot(data, register.slug, edition, source_url, retrieved)
    previous = snapshot_module.previous_snapshot(register.slug, edition)
    changes = snapshot_module.diff(current, previous)
    if changes["comparable"]:
        print(
            f"  vs {changes['previous_edition']}: "
            f"+{len(changes['added'])} added, ~{len(changes['amended'])} amended, "
            f"-{len(changes['removed'])} removed"
        )
    if not args.no_snapshot:
        print(f"  snapshot -> {snapshot_module.write_snapshot(current)}")

    editions = [
        json.loads(path.read_text()) for path in snapshot_module.existing_editions(register.slug)
    ]
    meta = {
        "site_name": "NHS Data Uses Register, readable",
        "site_url": args.site_url.rstrip("/"),
        "base_path": args.base_path.rstrip("/"),
        "repo_url": REPO_URL,
        "register": register.slug,
        "register_name": register.name,
        "edition": edition,
        "retrieved": retrieved,
        "source_url": source_url,
        "source_file": source_url.rsplit("/", 1)[-1],
        "source_page": sources.LANDING_PAGE,
        "today": dt.date.today().isoformat(),
        "editions": [{k: e[k] for k in ("edition", "retrieved", "counts")} for e in editions],
    }

    build_module.build(data, meta, changes, args.output)


def extract_register(payload: bytes) -> dict:
    from .extract import extract

    return extract(payload)


if __name__ == "__main__":
    main()
