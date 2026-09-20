"""Check that every internal link in a built site points at a page that exists.

    python -m pipeline.linkcheck                       # check _site/
    python -m pipeline.linkcheck _site --base-path /nhs-data-uses-register

Exits non-zero if any link is broken, so CI can gate on it. Checks the page a
link points at and, when it has one, the `#fragment` — an anchor that has been
renamed is as broken as a page that has gone. External links are not followed.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])


def _parse(path: Path) -> _Page:
    page = _Page()
    page.feed(path.read_text(encoding="utf-8"))
    return page


def _target(site: Path, page_url: str, href: str, base_path: str) -> tuple[Path | None, str]:
    """The file `href` resolves to on the built site, and its fragment.

    `None` for a link that leaves the site (another host, `mailto:`) and so is
    not ours to check.
    """
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        return None, ""
    path = unquote(parts.path)
    if not path:
        return site / page_url.lstrip("/"), parts.fragment
    if not path.startswith("/"):
        path = str(PurePosixPath(page_url).parent / path)
    if base_path:
        if path != base_path and not path.startswith(base_path + "/"):
            # Root-relative but outside the base path: it works locally and
            # 404s once deployed, which is exactly what this is here to catch.
            return site / "__outside_base_path__", parts.fragment
        path = path[len(base_path):] or "/"
    path = str(PurePosixPath(path))
    target = site / path.lstrip("/")
    if path.endswith("/") or target.is_dir():
        target = target / "index.html"
    return target, parts.fragment


def check(site: Path, base_path: str = "") -> tuple[dict[str, set[str]], int]:
    """`({broken link: pages containing it}, pages checked)`."""
    base_path = base_path.rstrip("/")
    pages = sorted(site.rglob("*.html"))
    parsed: dict[Path, _Page] = {}

    def page_for(path: Path) -> _Page:
        if path not in parsed:
            parsed[path] = _parse(path)
        return parsed[path]

    broken: dict[str, set[str]] = defaultdict(set)
    for path in pages:
        url = "/" + path.relative_to(site).as_posix()
        for href in page_for(path).links:
            target, fragment = _target(site, url, href, base_path)
            if target is None:
                continue
            if not target.is_file():
                broken[href].add(url)
            elif fragment and target.suffix == ".html" and fragment not in page_for(target).ids:
                broken[href].add(url)
    return broken, len(pages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("site", nargs="?", type=Path, default=ROOT / "_site", help="built site directory")
    parser.add_argument("--base-path", default="", help="the path prefix the site is served under")
    parser.add_argument("--show", type=int, default=20, help="how many broken links to list")
    args = parser.parse_args(argv)

    if not args.site.is_dir():
        raise SystemExit(f"not a directory: {args.site}")
    broken, pages = check(args.site, args.base_path)
    if not broken:
        print(f"linkcheck: {pages:,} pages, no broken internal links")
        return 0

    occurrences = sum(len(found) for found in broken.values())
    print(
        f"linkcheck: {len(broken):,} broken link target(s) across {occurrences:,} link(s) "
        f"in {pages:,} pages",
        file=sys.stderr,
    )
    worst = sorted(broken.items(), key=lambda item: (-len(item[1]), item[0]))
    for href, found in worst[: args.show]:
        print(f"  {href}  ({len(found):,} page(s), e.g. {sorted(found)[0]})", file=sys.stderr)
    if len(worst) > args.show:
        print(f"  … and {len(worst) - args.show:,} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
