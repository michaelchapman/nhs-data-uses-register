"""Check that a built site states each figure the same way on every page.

    python -m pipeline.sitecheck            # check _site/
    python -m pipeline.sitecheck _site

The site shows the same facts in several places: an agreement's files and
status in the agreements list and on its own page, the count of agreements in
term on the home page and in the list, the agreements with papers on the
Papers page and on agreement pages. Each is worked out once, but by different
templates from layers added at different times, so they can drift apart. This
reads the built pages, as a reader would, and exits non-zero on any
disagreement, so CI can gate on it like the link check.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ROW = re.compile(r"<tr data-i=\"\d+\"(?P<attrs>.*?)>(?P<body>.*?)</tr>", re.S)
LINK = re.compile(r'<th scope="row"><a href="(?P<href>[^"]+)"')
CELL = re.compile(r'<td[^>]*data-label="(?P<label>[^"]+)"[^>]*>(?P<value>.*?)</td>', re.S)
TAG = re.compile(r'class="tag tag-(?P<status>[a-z-]+)"')
FACT = re.compile(r"<dt>(?P<label>[^<]+)</dt><dd>(?P<value>.*?)</dd>", re.S)
NUMBER = re.compile(r"[\d,]+")


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _number(fragment: str) -> int | None:
    match = NUMBER.match(_text(fragment))
    return int(match.group().replace(",", "")) if match else None


def list_rows(site: Path) -> list[dict]:
    """The agreements in the register, as the agreements list shows them."""
    page = (site / "agreements" / "index.html").read_text(encoding="utf-8")
    rows = []
    for row in ROW.finditer(page):
        link = LINK.search(row.group("body"))
        if not link:
            continue
        cells = {m.group("label"): m.group("value") for m in CELL.finditer(row.group("body"))}
        tag = TAG.search(cells.get("Status", ""))
        rows.append({
            "href": link.group("href"),
            "files": _number(cells.get("Files", "")),
            "status": tag.group("status") if tag else None,
            "active": 'data-active="yes"' in row.group("attrs"),
        })
    return rows


def check(site: Path, base_path: str = "") -> list[str]:
    problems: list[str] = []
    rows = list_rows(site)
    if not rows:
        return ["agreements list: no agreements found"]

    with_papers = 0
    for row in rows:
        path = site / row["href"].removeprefix(base_path).strip("/") / "index.html"
        if not path.exists():
            problems.append(f"{row['href']}: listed but has no page")
            continue
        page = path.read_text(encoding="utf-8")
        facts = {m.group("label"): m.group("value") for m in FACT.finditer(page)}
        files = _number(facts.get("Files released to date", ""))
        if files != row["files"]:
            problems.append(f"{row['href']}: {row['files']} files in the list, {files} on the page")
        tag = TAG.search(page)
        status = tag.group("status") if tag else None
        if status != row["status"]:
            problems.append(f"{row['href']}: status {row['status']} in the list, {status} on the page")
        # An overview written while the agreement ran must say, once it has
        # ended, that its term has passed.
        if 'class="overview-text"' in page and status != "in-term" and "read the summary as what it was for" not in page:
            problems.append(f"{row['href']}: an ended agreement's overview doesn't say its term has passed")
        if 'id="papers"' in page:
            with_papers += 1

    home = (site / "index.html").read_text(encoding="utf-8")
    in_term = sum(1 for row in rows if row["active"])
    stated = re.search(r'stat-number">([\d,]+)</span><span class="stat-label">data sharing agreements in term, of ([\d,]+)', home)
    if not stated:
        problems.append("home page: no count of agreements in term")
    else:
        if int(stated.group(1).replace(",", "")) != in_term:
            problems.append(f"home page: {stated.group(1)} in term, the list has {in_term}")
        if int(stated.group(2).replace(",", "")) != len(rows):
            problems.append(f"home page: {stated.group(2)} listed, the list has {len(rows)}")

    papers = site / "papers" / "index.html"
    if papers.exists():
        page = papers.read_text(encoding="utf-8")
        facts = {m.group("label"): m.group("value") for m in FACT.finditer(page)}
        stated_papers = _number(facts.get("Agreements with a linked paper", ""))
        if stated_papers != with_papers:
            problems.append(f"papers page: {stated_papers} agreements with a paper, agreement pages show {with_papers}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("site", nargs="?", type=Path, default=ROOT / "_site")
    parser.add_argument("--base-path", default="")
    args = parser.parse_args(argv)
    problems = check(args.site, args.base_path.rstrip("/"))
    for problem in problems:
        print(problem)
    print(f"sitecheck: {len(list_rows(args.site)):,} agreements, "
          + (f"{len(problems):,} problem(s)" if problems else "every figure agrees"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
