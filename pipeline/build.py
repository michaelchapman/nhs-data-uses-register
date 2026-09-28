"""Render the static site from an extracted register."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import aliases
from . import compare
from . import lineage
from . import relations
from . import ods
from . import privacy
from . import search
from . import sectors
from .names import display_name, strip_code
from . import sources
from .extract import archive_views, organisation_slug, slugify

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
ASSETS = ROOT / "assets"

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def format_date(value: str) -> str:
    if not value:
        return "Not stated"
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.day} {MONTH_NAMES[parsed.month - 1]} {parsed.year}"


def format_month(value: str) -> str:
    if not value or len(value) < 7:
        return "—"
    year, month = value.split("-")[:2]
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def format_edition(edition: str) -> str:
    return sources.edition_label(edition)


def paragraphs(text: str) -> list[str]:
    """Split register free text into paragraphs, keeping its `~` bullet lines."""
    if not text:
        return []
    return [block.strip() for block in text.split("\n") if block.strip()]


def environment() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["date"] = format_date
    env.filters["month"] = format_month
    env.filters["edition"] = format_edition
    env.filters["paragraphs"] = paragraphs
    env.filters["commas"] = lambda n: f"{n:,}"
    env.filters["slug"] = slugify
    env.filters["org"] = display_name
    env.filters["nocode"] = strip_code
    env.globals["merger_edition"] = sources.MERGER_EDITION
    env.globals["ods"] = ods.SOURCE
    dataset_aliases = aliases.load_map(aliases.DATASET_ALIASES_PATH)
    # The page a dataset name links to, whichever spelling the register used.
    env.filters["dataset_slug"] = lambda name: slugify(aliases.resolve(name, dataset_aliases))
    return env


# Written into every build. `prepare_output` deletes the directory it is given,
# and this is how it tells a previous build from somebody's working directory.
BUILD_MARKER = ".built-by-pipeline"


def prepare_output(out: Path) -> None:
    """Empty `out` ready for a build, refusing to delete anything that isn't one.

    A build starts by removing its output directory, so `--output .` or a
    mistyped path would otherwise delete whatever is there. Only a directory
    that is empty, or that an earlier build left behind, is cleared.
    """
    out = out.resolve()
    if out.exists():
        if not out.is_dir():
            raise SystemExit(f"--output {out} exists and is not a directory")
        if out == ROOT or out in ROOT.parents or (out / ".git").exists():
            raise SystemExit(f"refusing to build into {out}: it contains this repository")
        # Builds made before the marker existed carry these two files instead.
        previous_build = (out / BUILD_MARKER).exists() or (
            (out / ".nojekyll").exists() and (out / "meta.json").exists()
        )
        if any(out.iterdir()) and not previous_build:
            raise SystemExit(
                f"refusing to build into {out}: it is not empty and does not look like a "
                "previous build. Choose an empty or new directory, or delete it yourself."
            )
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / BUILD_MARKER).write_text("Created by pipeline.build; safe to delete and rebuild.\n")


def _write(out: Path, path: str, html: str) -> None:
    target = out / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")


def compute_stats(data: dict, as_of: str) -> dict:
    agreements = data["agreements"]
    active = [a for a in agreements if a["coverage_end"] >= as_of]
    return {
        "agreements": len(agreements),
        "agreement_versions": sum(len(a["versions"]) for a in agreements),
        "active_agreements": len(active),
        "organisations": len(data["organisations"]),
        "datasets": len(data["datasets"]),
        "files_released": sum(a["files_released"] for a in agreements),
        # Release history runs years earlier than the editions held, so the
        # About page names both starts rather than implying one span.
        "first_release_month": min(
            (r["first_month"] for a in agreements for v in a["versions"]
             for r in v["releases"] if r["first_month"]),
            default="",
        ),
        "commercial": sum(1 for a in agreements if a["commercial"] == "Yes"),
        "sublicensing": sum(1 for a in agreements if a["sublicensing"] == "Yes"),
        "joint_controller": sum(
            1 for a in agreements if a["controller_basis"].lower().startswith("joint")
        ),
        "organisation_types": _counts(a["organisation_type"] or "Not stated" for a in agreements),
    }


def _sector_counts(values) -> list[tuple[str, int]]:
    """`[(sector, count)]` in the order the sectors are listed, leaving out empty ones."""
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    order = sectors.names(sectors.load()) + [sectors.OTHER, sectors.NOT_STATED]
    return [(name, tally[name]) for name in order if name in tally]


def _counts(values) -> list[tuple[str, int]]:
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))


def version_diffs(
    agreement: dict,
    dataset_aliases: dict[str, str] | None = None,
    organisation_aliases: dict[str, str] | None = None,
    organisation_lineage=None,
) -> dict[str, dict]:
    """What each version changed from the one before it, keyed by reference.

    Both versions are in the same extract, so this reads nothing more; the
    edition-to-edition case is `changes`, which reads the facts store.
    """
    diffs = {}
    for older, newer in zip(agreement["versions"], agreement["versions"][1:]):
        difference = compare.compare_versions(older, newer, dataset_aliases, organisation_aliases, organisation_lineage)
        if difference:
            diffs[newer["reference"]] = {**difference, "previous": older["reference"]}
    return diffs


def build(
    data: dict,
    meta: dict,
    changes: dict,
    out: Path,
    changes_history: list[dict] | None = None,
    history: dict[str, dict] | None = None,
) -> None:
    env = environment()
    prepare_output(out)

    stats = compute_stats(data, meta["as_of"])
    by_slug = {a["slug"]: a for a in data["agreements"]}
    # Agreements earlier editions listed and this one does not: pages of their
    # own, and never in a count. See `facts.read_archive`.
    archived = data.get("archived", [])
    archive = archive_views(archived, data["organisations"], data["datasets"])
    org_slugs = {o["slug"] for o in data["organisations"] + archive["organisations"]}
    # Page names, so an agreement can say which page its applicant is listed under.
    org_names = {o["slug"]: o["name"] for o in data["organisations"] + archive["organisations"]}
    # Sectors for the Sector filters, from data/organisation-sectors.json.
    for warning in sectors.assign(data["organisations"] + archive["organisations"]):
        print(f"sectors: {warning}")
    stats["agreement_sectors"] = _sector_counts(a["sector"] for a in data["agreements"])
    stats["organisation_sectors"] = _sector_counts(o["sector"] for o in data["organisations"])
    # Confidential data and patient opt-outs, for the agreements list's filters.
    privacy.assign(data["agreements"] + archived)
    stats["privacy"] = privacy.counts(data["agreements"])
    dataset_slugs = {d["slug"] for d in data["datasets"] + archive["datasets"]}
    # Related organisations, from data/organisation-relations.json.
    related_config = relations.load()
    for slug in relations.unknown(related_config, org_slugs):
        print(f"relations: no organisation page for {slug}")
    related = relations.lines(related_config)
    organisation_aliases = aliases.load_map(aliases.ALIASES_PATH)
    organisation_lineage = lineage.load()
    # The page a register name is listed on, for tables that carry only the
    # name as some edition wrote it.
    env.filters["org_slug"] = lambda name: organisation_slug(name, organisation_aliases, organisation_lineage)

    # Attach change status to agreements so detail pages can flag recent activity.
    changed_refs = {
        item["reference"]: {"kind": "amended", "fields": item.get("fields") or []}
        for item in changes.get("amended", [])
    }
    changed_refs.update(
        {
            item["reference"]: {"kind": item.get("kind", "new"), "fields": []}
            for item in changes.get("added", [])
        }
    )

    context = {
        "meta": meta,
        # The edition being built. A historical changes page overrides `meta`
        # to show its own edition, but its list of editions still needs to know
        # which one is current.
        "current_edition": meta["edition"],
        "stats": stats,
        "changes": changes,
        "build_time": dt.datetime.now(dt.timezone.utc).strftime("%d %B %Y"),
    }

    def render(template: str, path: str, **kwargs) -> None:
        # kwargs can legitimately override a context key (a historical changes
        # page overrides `meta` to show its own edition, for instance), so merge
        # rather than spread both as separate keyword arguments — spreading both
        # would raise on any key they share.
        # The page's own address, for its canonical link, and the section of the
        # main menu it belongs to. The 404 page answers at every address, so it
        # has neither.
        page_path = None if path == "404.html" else "/" + path.removesuffix("index.html")
        section = page_path.split("/")[1] if page_path else None
        pages = {"page_path": page_path, "section": section}
        _write(out, path, env.get_template(template).render(**{**context, **pages, **kwargs}))

    top_organisations = sorted(
        data["organisations"], key=lambda o: (-o["agreement_count"], o["name"].lower())
    )[:15]
    render("index.html", "index.html", agreements=data["agreements"], top_organisations=top_organisations)
    # The word index the agreement searches fetch from. An agreement is numbered
    # by its place in the list, and every table row naming it carries the number.
    search.write_index(data["agreements"], out / "search" / meta["edition"])
    # Organisation and dataset names, which the agreements search also shows.
    search.write_names(
        data["organisations"] + archive["organisations"],
        data["datasets"] + archive["datasets"],
        aliases.load_groups(aliases.DATASET_ALIASES_PATH),
        out / "search" / meta["edition"],
    )
    search_numbers = {a["slug"]: n for n, a in enumerate(data["agreements"])}
    render("agreements.html", "agreements/index.html", agreements=data["agreements"], archived=archived,
           org_slugs=org_slugs, search_numbers=search_numbers)
    render("organisations.html", "organisations/index.html", organisations=data["organisations"],
           archived_organisations=archive["organisations"])
    render("datasets.html", "datasets/index.html", datasets=data["datasets"], archived_datasets=archive["datasets"])
    # An agreement no longer listed still has its page, so a row about it links.
    changes_by_slug = {a["base_reference"]: a for a in archived + data["agreements"]}
    render("changes.html", "changes/index.html", by_slug=changes_by_slug, org_slugs=org_slugs)
    # A same-shaped page for every earlier edition pair, so "what changed" isn't
    # limited to the current edition — the facts store holds every edition
    # ingested, so each can have its own page.
    editions = {e["edition"]: e for e in meta.get("editions", [])}
    for entry in changes_history or []:
        if entry["edition"] == meta["edition"]:
            # Identical to /changes/, which already shows it.
            continue
        # The footer cites the workbook the page describes, not the newest one.
        held = editions.get(entry["edition"], {})
        render(
            "changes.html",
            f"changes/{entry['edition']}/index.html",
            changes=entry,
            by_slug=changes_by_slug,
            org_slugs=org_slugs,
            meta={
                **meta,
                "edition": entry["edition"],
                "retrieved": held.get("retrieved", ""),
                "source_file": held.get("source_file", ""),
                "source_url": held.get("source_url", ""),
            },
        )
    render("about.html", "about/index.html")
    render("downloads.html", "downloads/index.html")
    render("not-found.html", "404.html")

    dataset_aliases = aliases.load_map(aliases.DATASET_ALIASES_PATH)
    for agreement in data["agreements"] + archived:
        render(
            "agreement.html",
            f"agreements/{agreement['slug']}/index.html",
            agreement=agreement,
            org_names=org_names,
            change_status={v["reference"]: changed_refs.get(v["reference"]) for v in agreement["versions"]},
            org_slugs=org_slugs,
            # An agreement no longer listed can name a dataset no listed
            # agreement does, which has no page.
            dataset_slugs=dataset_slugs,
            history=(history or {}).get(agreement["base_reference"]),
            diffs=version_diffs(agreement, dataset_aliases, organisation_aliases, organisation_lineage),
        )
    for organisation in data["organisations"] + archive["organisations"]:
        render(
            "organisation.html",
            f"organisations/{organisation['slug']}/index.html",
            organisation=organisation,
            related=related.get(organisation["slug"], []),
            org_names=org_names,
            archived=archive["by_organisation"].get(organisation["slug"], []),
            org_slugs=org_slugs,
            dataset_slugs=dataset_slugs,
            search_numbers=search_numbers,
        )
    # A page a merge retired still answers. Before an alias or ODS moved a name
    # onto another organisation's page, it had a page of its own at the slug of
    # its own spelling; that address now forwards, so a link to it still works.
    page_names = org_names
    retired: dict[str, tuple[str, str]] = {}
    for agreement in data["agreements"] + archived:
        for version in agreement["versions"]:
            for name in [version["organisation"], *version["controllers"]]:
                own, now = slugify(name), organisation_slug(name, organisation_aliases, organisation_lineage)
                if own != now and own not in page_names and now in page_names:
                    retired.setdefault(own, (name, now))
    for own, (name, now) in sorted(retired.items()):
        render("moved.html", f"organisations/{own}/index.html", name=name, target=now, target_name=page_names[now])

    for dataset in data["datasets"] + archive["datasets"]:
        render(
            "dataset.html",
            f"datasets/{dataset['slug']}/index.html",
            dataset=dataset,
            archived=archive["by_dataset"].get(dataset["slug"], []),
            org_slugs=org_slugs,
            search_numbers=search_numbers,
        )

    shutil.copytree(ASSETS, out / "assets", dirs_exist_ok=True)
    (out / ".nojekyll").write_text("")
    _write(out, "meta.json", json.dumps({**meta, "stats": stats}, indent=1))
    _write(out, "sitemap.xml", env.get_template("sitemap.xml").render(
        **context, agreements=data["agreements"] + archived,
        organisations=data["organisations"] + archive["organisations"],
        datasets=data["datasets"] + archive["datasets"],
        changes_editions=[e["edition"] for e in changes_history or [] if e["edition"] != meta["edition"]],
    ))
    _write(
        out, "robots.txt",
        f"User-agent: *\nAllow: /\nSitemap: {meta['site_url']}{meta['base_path']}/sitemap.xml\n",
    )
    print(f"built {sum(1 for _ in out.rglob('*.html')):,} pages into {out}")
    return by_slug
