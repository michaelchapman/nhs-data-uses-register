"""OpenSAFELY projects: analysis run inside NHS England's systems.

    python -m pipeline.opensafely ingest    # fetch the project list into the store
    python -m pipeline.opensafely check     # list organisations with no page to link to

OpenSAFELY runs researchers' code against GP and hospital records where the
records are held, under the NHS OpenSAFELY Data Analytics Service Pilot
Directions, and NHS England approves each project. No file is released, so
none of it is on the Data Uses Register's release sheet. The Bennett Institute
publishes the approved projects at opensafely.org, which this module reads.

Only the facts are stored: each project's number, title, organisation, type,
start date, whether it is one of the COVID-19 projects, and its two addresses.
opensafely.org is © University of Oxford and may be copied only for
non-commercial research and study, so the descriptions stay there and the site
links to them. Study leads are named with an email address, and are left out.

Unlike digital.nhs.uk, opensafely.org answers requests from the build
environment. The fetch still runs by hand, like a workbook ingest, and its
result is committed to ``data/facts/opensafely/projects.json``; the build reads
only that file. A project the list stops showing is kept, marked as no longer
listed, so its link from an organisation page is not lost silently.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "data" / "facts" / "opensafely" / "projects.json"
# OpenSAFELY organisation names mapped by hand onto this site's organisation
# pages, for the names the register's own aliases do not already place.
ORGANISATIONS = ROOT / "data" / "opensafely-organisations.json"

SITE = "https://www.opensafely.org"
LISTING = f"{SITE}/projects/"
USER_AGENT = "healthdatauses.uk (+https://github.com/michaelchapman/nhs-data-uses-register)"
# Seconds between requests: the list is about ten pages and each project one more.
PAUSE = 1.0

MONTHS = {
    name: n
    for n, name in enumerate(
        ("january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"),
        start=1,
    )
}

CARD_RE = re.compile(r'<li\s+class="flex max-w-prose.*?(?=<li\s+class="flex max-w-prose|</ul>)', re.S)
LINK_RE = re.compile(r'<a class="link" href="(?P<url>https://www\.opensafely\.org/project/[^"]+)">(?P<heading>.*?)</a>', re.S)
RUN_BY_RE = re.compile(r"<p[^>]*>\s*(?P<type>.*?)\s+project\s+run\s+by\s+(?P<organisation>.*?)\.?\s*</p>", re.S)
TAG_RE = re.compile(r'<span\s+class="inline-flex[^"]*"\s*>(.*?)</span>', re.S)
NEXT_RE = re.compile(r'href="(?P<url>https://www\.opensafely\.org/projects/page/\d+/)"')
FIELD_RE = re.compile(r"<li>\s*<strong>\s*(?P<label>[^<:]+):\s*</strong>(?P<value>.*?)</li>", re.S)
JOBS_RE = re.compile(r'href="(?P<url>https://jobs\.opensafely\.org/[^"]+)"')


def text(fragment: str) -> str:
    """The words in an HTML fragment, with tags dropped and spaces collapsed."""
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_listing(page: str) -> list[dict]:
    """The projects one page of the list shows, in its order.

    A card that does not read as expected stops the ingest rather than being
    recorded half-read.
    """
    projects = []
    for card in CARD_RE.findall(page):
        link = LINK_RE.search(card)
        run_by = RUN_BY_RE.search(card)
        if not link or not run_by:
            raise ValueError(f"cannot read a project card: {text(card)[:120]!r}")
        heading = text(link["heading"])
        # "POS-2026-3015 : OptiFIT: ..." as well as "Project #11: ...".
        number, _, title = (part.strip() for part in heading.partition(":"))
        if not title:
            raise ValueError(f"no project number in {heading!r}")
        tags = [text(t) for t in TAG_RE.findall(card)]
        projects.append({
            "number": number,
            "title": title,
            "type": text(run_by["type"]),
            "organisation": text(run_by["organisation"]),
            "covid": "COVID-19" in tags,
            "page_url": link["url"],
        })
    return projects


def next_pages(page: str) -> list[str]:
    """The other pages of the list this page links to."""
    return sorted(set(NEXT_RE.findall(page)))


def parse_date(value: str) -> str:
    """``17 September 2026`` -> ``2026-09-17``; empty if it is not a date."""
    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+) (\d{4})", value.strip())
    if not match or match[2].lower() not in MONTHS:
        return ""
    return f"{match[3]}-{MONTHS[match[2].lower()]:02d}-{int(match[1]):02d}"


def parse_project(page: str) -> dict:
    """What a project's own page adds to its card: start date and outputs link.

    The organisation and type are read too, as the page states them, which is
    where the card's line comes from.
    """
    fields = {m["label"].strip(): m["value"] for m in FIELD_RE.finditer(page)}
    jobs = JOBS_RE.search(page)
    start = text(fields.get("Start date", ""))
    return {
        "organisation": text(fields.get("Organisation", "")),
        # An older page puts its outputs link inside the empty type field.
        "type": text(JOBS_RE.sub("", fields.get("Project type", "")).split("<a ")[0]),
        "start_date": parse_date(start),
        "jobs_url": jobs["url"] if jobs else "",
    }


def sort_key(number: str) -> tuple:
    """``Project #11`` before ``Project #210`` before ``POS-2026-3001``."""
    if match := re.fullmatch(r"Project #(\d+)", number):
        return (0, int(match[1]), 0)
    if match := re.fullmatch(r"POS-(\d{4})-(\d+)", number):
        return (1, int(match[1]), int(match[2]))
    return (2, 0, 0, number)


def merge(held: list[dict], listed: list[dict]) -> list[dict]:
    """Every project ever listed, newest facts first, in number order.

    A project the list no longer shows keeps its last facts and is marked
    `listed: false`; one that returns is listed again.
    """
    by_number = {p["number"]: {**p, "listed": False} for p in held}
    for project in listed:
        by_number[project["number"]] = {**project, "listed": True}
    return sorted(by_number.values(), key=lambda p: sort_key(p["number"]))


def load(path: Path | None = None) -> dict:
    """The store, or an empty one if nothing has been ingested."""
    path = path or STORE
    if not path.exists():
        return {"source_url": LISTING, "retrieved": "", "projects": []}
    return json.loads(path.read_text(encoding="utf-8"))


def save(store: dict, path: Path | None = None) -> None:
    path = path or STORE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_organisations(path: Path | None = None) -> dict:
    path = path or ORGANISATIONS
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"pages": {}, "none": {}}


def organisation_pages(projects: list[dict], slug_of, org_slugs: set[str], config: dict) -> dict[str, list[str]]:
    """`{OpenSAFELY organisation name: [organisation page slug, ...]}` for the names that have a page.

    The list writes one free-text organisation per project, often several
    organisations joined ("University of Oxford and London School of Hygiene
    and Tropical Medicine"). The hand-made map decides those, naming every
    organisation with a page; otherwise the name is looked up the way a
    register name is (`slug_of`, which applies the reviewed aliases and ODS),
    and kept only if that page exists.
    """
    pages = {}
    for name in sorted({p["organisation"] for p in projects}):
        if name in config.get("none", {}):
            continue
        slugs = config.get("pages", {}).get(name) or [slug_of(name)]
        found = [slug for slug in slugs if slug in org_slugs]
        if found:
            pages[name] = found
    return pages


def unmatched(projects: list[dict], pages: dict[str, list[str]], config: dict) -> list[str]:
    """Organisation names with no page and no decision recorded, sorted."""
    decided = set(pages) | set(config.get("none", {}))
    return sorted({p["organisation"] for p in projects} - decided)


def by_organisation(projects: list[dict], pages: dict[str, list[str]]) -> dict[str, list[dict]]:
    """`{organisation page slug: [project, ...]}`, each in number order."""
    out: dict[str, list[dict]] = {}
    for project in projects:
        for slug in pages.get(project["organisation"], []):
            out.setdefault(slug, []).append(project)
    return out


def unknown_pages(config: dict, org_slugs: set[str]) -> list[str]:
    """Pages the hand-made map names that do not exist, sorted."""
    return sorted({s for slugs in config.get("pages", {}).values() for s in slugs} - org_slugs)


class FetchError(Exception):
    """A page that did not answer after every retry."""


def fetch(url: str, attempts: int = 4) -> str:
    """One page, retried with backoff: the site answers the odd request with a 500."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read().decode("utf-8")
        except (urllib.error.HTTPError, urllib.error.URLError) as error:
            if attempt == attempts - 1:
                raise FetchError(f"{url}: {error}") from error
            time.sleep(2 ** (attempt + 1))
    raise AssertionError("unreachable")


def ingest(pause: float = PAUSE) -> dict:
    """Read the whole list and every project page, and merge them into the store."""
    seen, queue, listed = set(), [LISTING], []
    while queue:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            page = fetch(url)
        except FetchError as error:
            raise SystemExit(f"cannot read the project list: {error}") from error
        listed.extend(parse_listing(page))
        queue.extend(u for u in next_pages(page) if u not in seen)
        time.sleep(pause)
    if not listed:
        raise SystemExit(f"no projects read from {LISTING}; has the page changed?")
    store = load()
    held = {p["number"]: p for p in store["projects"]}
    for n, project in enumerate(listed, start=1):
        if n % 50 == 0:
            print(f"opensafely: read {n} of {len(listed)} project pages")
        try:
            own = parse_project(fetch(project["page_url"]))
        except FetchError as error:
            # A project page that is broken at source keeps what the list
            # says, and what an earlier ingest read from its page.
            print(f"opensafely: kept the list's facts only: {error}")
            before = held.get(project["number"], {})
            own = {k: before.get(k, "") for k in ("organisation", "type", "start_date", "jobs_url")}
        project["organisation"] = own["organisation"] or project["organisation"]
        project["type"] = own["type"] or project["type"]
        project["start_date"] = own["start_date"]
        project["jobs_url"] = own["jobs_url"]
        time.sleep(pause)
    projects = merge(store["projects"], listed)
    store = {
        "source_url": LISTING,
        "retrieved": dt.date.today().isoformat(),
        "projects": projects,
    }
    save(store)
    gone = sum(1 for p in projects if not p["listed"])
    print(f"opensafely: {len(listed)} projects listed" + (f", {gone} no longer listed" if gone else ""))
    return store


def check() -> int:
    """List OpenSAFELY organisations with no page and no decision. Run after ingesting."""
    from . import run, sources
    from .model import archive_views, organisation_slug
    from .rules import Rules

    rules = Rules.load()
    data, edition, _ = run.from_store(sources.registers()[0], None, rules)
    archive = archive_views(data.get("archived", []), data["organisations"], data["datasets"], rules)
    org_slugs = {o["slug"] for o in data["organisations"] + archive["organisations"]}
    projects = load()["projects"]
    config = load_organisations()
    pages = organisation_pages(
        projects, lambda n: organisation_slug(n, rules.organisation_aliases, rules.lineage), org_slugs, config
    )
    problems = 0
    for slug in unknown_pages(config, org_slugs):
        print(f"no organisation page: {slug}")
        problems += 1
    for name in unmatched(projects, pages, config):
        count = sum(1 for p in projects if p["organisation"] == name)
        print(f"no page decided: {name} ({count} project{'s' if count != 1 else ''})")
        problems += 1
    matched = sum(1 for p in projects if p["organisation"] in pages)
    print(f"{edition}: {matched} of {len(projects)} OpenSAFELY projects link to an organisation page")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("ingest", "check"))
    args = parser.parse_args(argv)
    if args.command == "ingest":
        ingest()
    else:
        raise SystemExit(check())


if __name__ == "__main__":
    main()
