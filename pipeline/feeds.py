"""Atom feeds of what changed, so people can follow the register without coming back to check.

One feed for the whole register, one entry per edition, at `/changes/feed.xml`;
and one per organisation and per dataset page, one entry per change to an
agreement it names, at `<page>/feed.xml`. They are written at build time from
the same changes the changes pages show, so a feed reader learns of an edition
when the site is rebuilt with it. Nothing is tracked: a feed is a file like any
other page.

An entry's date is its edition's date, not the build's, so rebuilding the same
editions writes the same feeds, and a reader doesn't see old entries as new.
"""

from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

from . import sources
from .names import display_name

# Entries per feed. Feed readers keep what they have already seen, so a feed
# needs only the recent past; the changes pages hold the rest.
SITE_ENTRIES = 24
PAGE_ENTRIES = 50

KINDS = {"added": "Added", "amended": "Amended", "removed": "No longer listed"}


def _date(edition: str) -> str:
    return sources.edition_date(edition) + "T00:00:00Z"


def _tag(meta: dict, path: str) -> str:
    """A stable entry id: the site's domain, and the path the entry is about."""
    host = meta["site_url"].split("://", 1)[-1].split("/", 1)[0]
    return f"tag:{host},2026:{path}"


def _url(meta: dict, path: str) -> str:
    return f"{meta['site_url']}{meta['base_path']}{path}"


def _items(entry: dict) -> list[tuple[str, dict]]:
    return [(kind, item) for kind in KINDS for item in entry.get(kind) or []]


def _describe(kind: str, item: dict) -> str:
    """One change, as a feed entry's title: "Added: COPE study (Bangor University)"."""
    label = KINDS[kind]
    if kind == "added" and item.get("kind") and item["kind"] != "new":
        label = "New version"
    if kind == "amended" and item.get("fields"):
        label = "Amended (" + ", ".join(item["fields"]).lower() + ")"
    org = display_name(item.get("org") or "")
    return f"{label}: {item.get('title') or item['base']}" + (f" ({org})" if org else "")


def _feed(meta: dict, title: str, page_path: str, feed_path: str, entries: list[dict]) -> str:
    updated = entries[0]["updated"] if entries else _date(meta["edition"])
    out = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f"  <title>{escape(title)}</title>",
        f"  <subtitle>{escape('Changes in the NHS England Data Uses Register, as shown on ' + meta['site_name'] + '. Unofficial.')}</subtitle>",
        f"  <id>{escape(_tag(meta, feed_path))}</id>",
        f"  <link rel=\"self\" href={quoteattr(_url(meta, feed_path))}/>",
        f"  <link rel=\"alternate\" type=\"text/html\" href={quoteattr(_url(meta, page_path))}/>",
        f"  <updated>{updated}</updated>",
        f"  <author><name>{escape(meta['site_name'])}</name></author>",
    ]
    for entry in entries:
        out += [
            "  <entry>",
            f"    <title>{escape(entry['title'])}</title>",
            f"    <id>{escape(entry['id'])}</id>",
            f"    <link rel=\"alternate\" type=\"text/html\" href={quoteattr(entry['link'])}/>",
            f"    <updated>{entry['updated']}</updated>",
            f"    <summary>{escape(entry['summary'])}</summary>",
            "  </entry>",
        ]
    out.append("</feed>")
    return "\n".join(out) + "\n"


def _changes_path(edition: str, current: str) -> str:
    return "/changes/" if edition == current else f"/changes/{edition}/"


def site_feed(meta: dict, history: list[dict]) -> str:
    """The register's feed: one entry per edition, newest first."""
    entries = []
    for entry in sorted(history, key=lambda e: sources.edition_date(e["edition"]), reverse=True)[:SITE_ENTRIES]:
        counts = {kind: len(entry.get(kind) or []) for kind in KINDS}
        label = sources.edition_label(entry["edition"])
        summary = (f"{counts['added']:,} added, {counts['amended']:,} amended and {counts['removed']:,} no longer "
                   f"listed since the {sources.edition_label(entry['previous_edition'])} edition."
                   if entry.get("previous_edition") else "The first edition this site holds.")
        entries.append({
            "title": f"{label} edition: {counts['added']:,} added, {counts['amended']:,} amended, {counts['removed']:,} no longer listed",
            "id": _tag(meta, f"/changes/{entry['edition']}/"),
            "link": _url(meta, _changes_path(entry["edition"], meta["edition"])),
            "updated": _date(entry["edition"]),
            "summary": summary,
        })
    return _feed(meta, f"{meta['site_name']}: what changed", "/changes/", "/changes/feed.xml", entries)


def page_entries(history: list[dict], by_base: dict[str, dict], meta: dict) -> dict[str, dict[str, list[dict]]]:
    """`{"organisations": {slug: [entry]}, "datasets": {slug: [entry]}}`, newest first.

    A change belongs to the organisation that applied, every data controller,
    and every dataset the agreement's latest version names.
    """
    pages: dict[str, dict[str, list[dict]]] = {"organisations": {}, "datasets": {}}
    for entry in sorted(history, key=lambda e: sources.edition_date(e["edition"]), reverse=True):
        for kind, item in _items(entry):
            agreement = by_base.get(item["base"])
            if not agreement:
                continue
            feed_entry = {
                "title": _describe(kind, item),
                "id": _tag(meta, f"/changes/{entry['edition']}/{kind}/{item['reference']}"),
                "link": _url(meta, f"/agreements/{agreement['slug']}/"),
                "updated": _date(entry["edition"]),
                "summary": f"{KINDS[kind]} in the {sources.edition_label(entry['edition'])} edition: {item['reference']}.",
            }
            orgs = {agreement.get("organisation_slug"), *(agreement.get("controller_slugs") or [])} - {None, ""}
            for slug in orgs:
                pages["organisations"].setdefault(slug, []).append(feed_entry)
            for slug in set(agreement.get("dataset_slugs") or []):
                pages["datasets"].setdefault(slug, []).append(feed_entry)
    return pages


def page_feed(meta: dict, kind: str, slug: str, name: str, entries: list[dict]) -> str:
    page = f"/{kind}/{slug}/"
    return _feed(meta, f"{name}: changes in the Data Uses Register", page, page + "feed.xml", entries[:PAGE_ENTRIES])
