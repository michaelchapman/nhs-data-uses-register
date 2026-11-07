"""Render the static site from an extracted register."""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import (
    aliases,
    compare,
    earlier,
    ods,
    onward,
    outputs,
    overviews,
    privacy,
    relations,
    releases,
    search,
    sectors,
    sources,
)
from .model import archive_views, organisation_slug
from .names import display_name, strip_code
from .references import slugify, version_key
from .rules import Rules

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
ASSETS = ROOT / "assets"

def format_date(value: str) -> str:
    if not value:
        return "Not stated"
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.day} {sources.MONTH_NAMES[parsed.month - 1]} {parsed.year}"


def format_month(value: str) -> str:
    if not value or len(value) < 7:
        return "—"
    year, month = value.split("-")[:2]
    return f"{sources.MONTH_NAMES[int(month) - 1]} {year}"


def format_edition(edition: str) -> str:
    return sources.edition_label(edition)


def paragraphs(text: str) -> list[str]:
    """Split register free text into paragraphs, keeping its `~` bullet lines."""
    if not text:
        return []
    return [block.strip() for block in text.split("\n") if block.strip()]


def environment(rules: Rules | None = None) -> Environment:
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
    env.globals["onward_caveat"] = onward.caveat
    env.globals["ods"] = ods.SOURCE
    env.globals["release_chart_start"] = releases.CHART_START
    dataset_aliases = (rules or Rules.load()).dataset_aliases
    # The page a dataset name links to, whichever spelling the register used.
    env.filters["dataset_slug"] = lambda name: slugify(aliases.resolve(name, dataset_aliases))
    # What the page a dataset name links to is titled. `build_site` knows the
    # pages, and replaces this with a lookup of their titles.
    env.filters["dataset_name"] = lambda name: aliases.resolve(name, dataset_aliases)
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


def _sector_counts(values, config: dict) -> list[tuple[str, int]]:
    """`[(sector, count)]` in the order the sectors are listed, leaving out empty ones."""
    tally = Counter(values)
    order = sectors.names(config) + [sectors.OTHER, sectors.NOT_STATED]
    return [(name, tally[name]) for name in order if name in tally]


def _counts(values) -> list[tuple[str, int]]:
    """`[(value, count)]`, commonest first."""
    return sorted(Counter(values).items(), key=lambda kv: (-kv[1], kv[0]))


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


def earlier_views(
    store: dict | None,
    agreements: list[dict],
    organisation_aliases: dict | None = None,
    organisation_lineage=None,
) -> tuple[dict[str, dict], list[dict]]:
    """What the earlier release registers add: `({base: view}, [agreements only they list])`.

    A view of an agreement the site already has leaves out the versions its
    pages already show, and carries `rows`: each remaining version, newest
    first, paired with the version after it, so the page shows only text that
    changed. See `pipeline.earlier`.
    """
    if not store:
        return {}, []
    periods = store["periods"]
    known = {a["base_reference"].upper(): a for a in agreements}
    views: dict[str, dict] = {}
    only: list[dict] = []
    for base, record in store["agreements"].items():
        agreement = known.get(base.upper())
        if agreement is None:
            view = earlier.view(record, periods)
            view["organisation_slug"] = organisation_slug(view["organisation"], organisation_aliases or {},
                                                          organisation_lineage)
            ordered = list(reversed(view["versions"]))
            view["rows"] = [(version, ordered[n - 1] if n else None) for n, version in enumerate(ordered)]
            view["only_earlier"] = True
            only.append(view)
            continue
        held = {v["reference"] for v in agreement["versions"] + agreement.get("dropped_versions", [])}
        view = earlier.view(record, periods, held)
        oldest = agreement["versions"][0] if agreement["versions"] else None
        after_all = {
            "reference": oldest["reference"],
            "texts": {field: oldest.get(field, "") for field in earlier.TEXT_FIELDS},
        } if oldest else None
        rows = []
        for n, version in enumerate(view["earlier_only"]):
            if n:
                newer = view["earlier_only"][n - 1]
            elif oldest and version_key(oldest["version"]) > version_key(version["version"]):
                newer = after_all
            else:
                newer = None
            rows.append((version, newer))
        view["rows"] = rows
        view["only_earlier"] = False
        views[agreement["base_reference"]] = view
    only.sort(key=lambda a: (a["last_listed"], a["base_reference"]), reverse=True)
    return views, only


def earlier_organisation_page(name: str, slugs: set[str], organisation_aliases: dict, organisation_lineage) -> tuple[str, bool]:
    """`(page slug, succeeded)` for an organisation the earlier registers name, or ("", False).

    Most earlier-only applicants with no page of their own are CCGs that merged
    before the Data Uses Register began. ODS records who took each over, so the
    agreement is listed on the page of the first successor the site has a page
    for, saying so.
    """
    slug = organisation_slug(name, organisation_aliases, organisation_lineage)
    if slug in slugs:
        return slug, False
    node = organisation_lineage.node(name) if organisation_lineage and name else None
    seen, queue = set(), [node] if node else []
    while queue:
        node = queue.pop(0)
        if node in seen:
            continue
        seen.add(node)
        for later, _ in organisation_lineage.successors(node):
            identity = organisation_lineage.identity(later)
            page = slugify(organisation_lineage.page_name(identity))
            if page in slugs:
                return page, True
            queue.append(later)
    return "", False


def earlier_organisations(earlier_only: list[dict], organisation_aliases: dict, organisation_lineage) -> dict[str, dict]:
    """`{slug: organisation}` for the earlier-only agreements' applicants that have no page.

    Sets each such agreement's `organisation_slug`. Spellings that differ only
    in case or punctuation share a page, titled with the commonest.
    """
    found: dict[str, dict] = {}
    for agreement in earlier_only:
        if agreement["organisation_slug"] or not agreement["organisation"]:
            continue
        slug = organisation_slug(agreement["organisation"], organisation_aliases, organisation_lineage)
        entry = found.setdefault(slug, {"slug": slug, "spellings": Counter(), "types": Counter(), "agreements": []})
        entry["spellings"][agreement["organisation"]] += 1
        if agreement["organisation_type"]:
            entry["types"][agreement["organisation_type"]] += 1
        entry["agreements"].append(agreement)
        agreement["organisation_slug"] = slug
    for entry in found.values():
        spellings, types = entry.pop("spellings"), entry.pop("types")
        entry["name"] = min(spellings, key=lambda n: (-spellings[n], n == n.upper(), n))
        entry["known_as"] = sorted(n for n in spellings if n.casefold() != entry["name"].casefold())
        entry["type"] = types.most_common(1)[0][0] if types else ""
        entry["agreements"].sort(key=lambda a: (a["first_listed"], a["base_reference"]))
        entry["agreement_count"] = len(entry["agreements"])
        entry["last_listed"] = max(a["last_listed"] for a in entry["agreements"])
        entry["last_label"] = max(entry["agreements"], key=lambda a: a["last_listed"])["last_label"]
        entry["dataset_names"] = sorted({n for a in entry["agreements"] for n in a["dataset_names"]}, key=lambda n: (n.casefold(), n))
        entry["datasets"] = sorted(
            {(d["dataset"], d["slug"]) for a in entry["agreements"] for v in a["versions"] for d in v["datasets"]},
            key=lambda pair: pair[0].casefold(),
        )
    return dict(sorted(found.items(), key=lambda kv: kv[1]["name"].casefold()))


def link_earlier_datasets(views: list[dict], spellings: dict[str, str], alias_map: dict) -> dict[str, dict]:
    """Give each dataset row in the earlier views the slug of its page, and gather them by page.

    Returns `{dataset slug: {"first_start", "first_label", "names", "agreements": [...]}}`, each
    agreement listed once with the first and last period it received the dataset.
    """
    names = {d["dataset"] for view in views for v in view["versions"] for d in v["datasets"]}
    matched = earlier.match_datasets(names, spellings, alias_map)
    by_dataset: dict[str, dict] = {}
    for view in views:
        rows: dict[str, dict] = {}
        for version in view["versions"]:
            for d in version["datasets"]:
                found = matched.get(d["dataset"])
                d["slug"] = found["slug"] if found else ""
                if not found:
                    continue
                row = rows.setdefault(found["slug"], {
                    "base_reference": view["base_reference"], "slug": view["slug"],
                    "organisation": view["organisation"], "first_start": d["first_start"], "first": d["first"],
                    "last_start": d["last_start"], "last": d["last"], "names": set(),
                })
                row["names"].add(d["dataset"])
                if d["first_start"] < row["first_start"]:
                    row["first_start"], row["first"] = d["first_start"], d["first"]
                if d["last_start"] > row["last_start"]:
                    row["last_start"], row["last"] = d["last_start"], d["last"]
        for slug, row in rows.items():
            entry = by_dataset.setdefault(slug, {"agreements": [], "names": set()})
            entry["names"] |= row["names"]
            entry["agreements"].append({**row, "only_earlier": view["only_earlier"]})
    for entry in by_dataset.values():
        entry["agreements"].sort(key=lambda r: (r["first_start"], r["base_reference"]))
        first = entry["agreements"][0]
        entry["first_label"] = first["first"]
        entry["names"] = sorted(entry["names"], key=lambda n: (n.casefold(), n))
    return by_dataset


# Problems a build notices but can still build past, such as a hand-kept file
# naming a page that doesn't exist. `run --strict`, as CI runs it, fails on any.
WARNINGS: list[str] = []


def warn(message: str) -> None:
    WARNINGS.append(message)
    print(message)


def build(
    data: dict,
    meta: dict,
    changes: dict,
    out: Path,
    changes_history: list[dict] | None = None,
    history: dict[str, dict] | None = None,
    rules: Rules | None = None,
    onward_config: dict | None = None,
) -> dict[str, dict]:
    WARNINGS.clear()
    rules = rules or Rules.load()
    env = environment(rules)
    prepare_output(out)

    stats = compute_stats(data, meta["as_of"])
    by_slug = {a["slug"]: a for a in data["agreements"]}
    # Agreements earlier editions listed and this one does not: pages of their
    # own, and never in a count. See `facts.read_archive`.
    archived = data.get("archived", [])
    archive = archive_views(archived, data["organisations"], data["datasets"], rules)
    org_slugs = {o["slug"] for o in data["organisations"] + archive["organisations"]}
    # Page names, so an agreement can say which page its applicant is listed under.
    org_names = {o["slug"]: o["name"] for o in data["organisations"] + archive["organisations"]}
    # Sectors for the Sector filters, from data/organisation-sectors.json.
    sector_config = sectors.load()
    for warning in sectors.assign(data["organisations"] + archive["organisations"], sector_config):
        warn(f"sectors: {warning}")
    stats["agreement_sectors"] = _sector_counts((a["sector"] for a in data["agreements"]), sector_config)
    stats["organisation_sectors"] = _sector_counts((o["sector"] for o in data["organisations"]), sector_config)
    # Confidential data and patient opt-outs, for the agreements list's filters.
    privacy.assign(data["agreements"] + archived)
    stats["privacy"] = privacy.counts(data["agreements"])
    dataset_aliases = rules.dataset_aliases
    # Files by month, checked against the per-dataset totals every page shows
    # before anything is drawn from them. See pipeline/releases.py.
    releases.check(data["agreements"], data["datasets"], dataset_aliases)
    releases.check(archived, archive["datasets"], dataset_aliases)
    release_rows = {a["base_reference"]: releases.by_dataset(a, dataset_aliases) for a in data["agreements"] + archived}
    latest_month = releases.last_month(meta["as_of"])
    dataset_slugs = {d["slug"] for d in data["datasets"] + archive["datasets"]}
    dataset_titles = {d["slug"]: d["name"] for d in data["datasets"] + archive["datasets"]}
    slug_of = env.filters["dataset_slug"]
    env.filters["dataset_name"] = lambda name: dataset_titles.get(slug_of(name), name)
    # Related organisations, from data/organisation-relations.json.
    related_config = relations.load()
    for slug in relations.unknown(related_config, org_slugs):
        warn(f"relations: no organisation page for {slug}")
    related = relations.lines(related_config)
    organisation_aliases = rules.organisation_aliases
    organisation_lineage = rules.lineage
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

    # Papers linked to agreements, from data/outputs.json; see `pipeline.outputs`.
    # With no file there is no papers page, and the menu doesn't offer one.
    output_links = outputs.load()
    all_papers = outputs.papers(output_links, data["agreements"] + archived)
    papers_by_org = outputs.by_organisation(all_papers)
    papers_by_dataset = outputs.by_dataset(all_papers)
    # NHS Digital's release registers from before July 2021; see `pipeline.earlier`.
    # With no store, agreement pages have no earlier section and there is no list.
    earlier_store = earlier.load(excluded=rules.excluded)
    earlier_by_base, earlier_only = earlier_views(
        earlier_store, data["agreements"] + archived, organisation_aliases, organisation_lineage
    )
    # The earliest date any register gives for an agreement: its first
    # version's start, or the first release register listing data released
    # under it, whichever is earlier.
    for agreement in data["agreements"] + archived:
        view = earlier_by_base.get(agreement["base_reference"])
        agreement["since"] = min(
            [d for d in (agreement["first_start"], view["first_listed"] if view else "") if d], default=""
        )
    taken = {a["slug"] for a in data["agreements"] + archived}
    for agreement in [a for a in earlier_only if a["slug"] in taken]:
        warn(f"earlier: {agreement['base_reference']} shares a page address with a listed agreement; left out")
    earlier_only = [a for a in earlier_only if a["slug"] not in taken]
    # The earlier registers' own dataset names, linked to the site's dataset pages where the name says which.
    earlier_by_dataset = link_earlier_datasets(
        list(earlier_by_base.values()) + earlier_only,
        {name: slug for name, slug in earlier.dataset_spellings(data["agreements"] + archived, dataset_aliases).items()
         if slug in dataset_slugs},
        dataset_aliases,
    )
    earlier_by_org: dict[str, list[dict]] = {}
    for agreement in earlier_only:
        page, succeeded = earlier_organisation_page(
            agreement["organisation"], org_slugs, organisation_aliases, organisation_lineage
        )
        agreement["organisation_slug"], agreement["organisation_succeeded"] = page, succeeded
        if page:
            earlier_by_org.setdefault(page, []).append(agreement)
    # Applicants with no page here, and no successor with one, still received
    # data, so each gets a page built from the earlier registers alone.
    pages_before_earlier = dict(org_names)
    earlier_orgs = earlier_organisations(earlier_only, organisation_aliases, organisation_lineage)
    org_slugs |= set(earlier_orgs)
    org_names.update({slug: entry["name"] for slug, entry in earlier_orgs.items()})
    earlier_files = earlier_store["files"] if earlier_store else []
    # The projects and papers sublicensing holders list of their own, from
    # data/onward-registers.json. See pipeline/onward.py.
    onward_config = onward.load() if onward_config is None else onward_config
    for problem in onward.problems(onward_config, data["agreements"], org_slugs):
        warn(f"onward: {problem}")
    onward_by_agreement = onward.by_agreement(onward_config)
    onward_by_org = onward.by_organisation(onward_config)
    onward_slugs = {a["base_reference"].upper(): a["slug"] for a in data["agreements"] + archived}
    stats["onward"] = onward.counts(onward_config)
    context = {
        "meta": meta,
        "papers_page": bool(output_links),
        "earlier_periods": len(earlier_files),
        "earlier_span": earlier.period_label(earlier_files[0]["period_start"], earlier_files[-1]["period_end"])
        if earlier_files else "",
        # The edition being built. A historical changes page overrides `meta`
        # to show its own edition, but its list of editions still needs to know
        # which one is current.
        "current_edition": meta["edition"],
        "stats": stats,
        "changes": changes,
        "build_time": dt.datetime.now(dt.UTC).strftime("%d %B %Y"),
        "onward_kinds": onward.KINDS,
        "onward_checked": onward_config.get("checked", ""),
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
        rules.dataset_groups,
        out / "search" / meta["edition"],
    )
    search_numbers = {a["slug"]: n for n, a in enumerate(data["agreements"])}
    render("agreements.html", "agreements/index.html", agreements=data["agreements"], archived=archived,
           org_slugs=org_slugs, search_numbers=search_numbers, earlier_only=earlier_only, org_names=org_names)
    # AI-written overviews, from data/summaries.json; see `pipeline.overviews`.
    # Agreement pages flag them as AI-generated; the About page names the models.
    overview_entries = overviews.load()
    if earlier_only:
        render("earlier-agreements.html", "agreements/earlier/index.html", agreements=earlier_only, org_slugs=org_slugs,
               org_names=org_names)
        for agreement in earlier_only:
            render("earlier-agreement.html", f"agreements/{agreement['slug']}/index.html", agreement=agreement,
                   rows=agreement["rows"], org_slugs=org_slugs, org_names=org_names,
                   papers=outputs.for_agreement(agreement, output_links),
                   overview=overviews.current(overviews.earlier_source(agreement), overview_entries))
    render("organisations.html", "organisations/index.html", organisations=data["organisations"],
           archived_organisations=archive["organisations"], earlier_organisations=list(earlier_orgs.values()))
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
    by_month = releases.monthly(data["agreements"], dataset_aliases, rows=release_rows)
    files_chart = releases.chart(by_month, "files", latest_month)
    per_agreement = sorted((a["files_released"] for a in data["agreements"]), reverse=True)
    chart_start_year = int(releases.CHART_START[:4])
    render(
        "releases.html",
        "releases/index.html",
        by_month=by_month,
        latest_month=latest_month,
        files_chart=files_chart,
        agreements_chart=releases.chart(by_month, "agreements", latest_month),
        with_files=sum(1 for n in per_agreement if n),
        top_share=f"{sum(per_agreement[:100]) / sum(per_agreement):.0%}" if any(per_agreement) else "none",
        peak_agreements=by_month[files_chart["peak"]["month"]]["agreements"] if files_chart["peak"] else 0,
        chart_start=releases.CHART_START,
        chart_start_year=chart_start_year,
        early_files=sum(row["files"] for month, row in by_month.items() if month < f"{chart_start_year - 1}-01"),
        # The year before the charts start, when the register's records fill in.
        ramp={
            "first_month": f"{chart_start_year - 1}-01",
            "first": by_month.get(f"{chart_start_year - 1}-01", {}).get("agreements", 0),
            "last_month": f"{chart_start_year - 1}-12",
            "last": by_month.get(f"{chart_start_year - 1}-12", {}).get("agreements", 0),
        },
    )
    render(
        "about.html",
        "about/index.html",
        overview_models=overviews.models_used(overview_entries),
        output_stats=outputs.stats(output_links, {a["base_reference"].upper() for a in data["agreements"]}),
        output_lag=outputs.lag(all_papers),
        earlier_stats={
            "agreements": len(earlier_by_base),
            "with_versions": sum(1 for view in earlier_by_base.values() if view["rows"]),
            "versions": sum(len(view["rows"]) for view in earlier_by_base.values()),
            "only": len(earlier_only),
            "skipped": earlier_store["skipped"],
        } if earlier_store else None,
    )
    if output_links:
        render(
            "papers.html",
            "papers/index.html",
            papers=all_papers,
            organisations=sorted(
                papers_by_org.items(), key=lambda item: (-item[1], display_name(org_names.get(item[0], item[0])).lower())
            ),
            org_names=org_names,
            datasets=sorted(
                papers_by_dataset.items(), key=lambda item: (-item[1], dataset_titles.get(item[0], item[0]).lower())
            ),
            dataset_titles=dataset_titles,
            sector_counts=_sector_counts((s for p in all_papers for s in p["sectors"]), sector_config),
            coverage=outputs.coverage(
                all_papers, data["agreements"], [name for name, _ in stats["agreement_sectors"]]
            ),
            by_year=outputs.by_year(all_papers, output_links.get("exported", "")),
            listed_with_papers=sum(
                1 for a in data["agreements"] if outputs.for_agreement(a, output_links)
            ),
            outputs_meta=output_links,
        )
        # The same table as a file, for people who want to count for themselves.
        _write(out, "papers/papers.csv", outputs.as_csv(
            all_papers, {slug: display_name(name) for slug, name in org_names.items()},
            output_links["register_edition"],
        ))
    render("downloads.html", "downloads/index.html", papers_csv=bool(output_links))
    render("not-found.html", "404.html")

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
            timeline=releases.agreement_timeline(agreement, dataset_aliases, meta["as_of"]),
            overview=overviews.current(agreement, overview_entries),
            papers=outputs.for_agreement(agreement, output_links),
            earlier=earlier_by_base.get(agreement["base_reference"]),
            onward=onward_by_agreement.get(agreement["base_reference"].upper()),
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
            paper_count=papers_by_org.get(organisation["slug"], 0),
            earlier_only=earlier_by_org.get(organisation["slug"], []),
            onward=onward_by_org.get(organisation["slug"], []),
            onward_slugs=onward_slugs,
        )
    # A page a merge retired still answers. Before an alias or ODS moved a name
    # onto another organisation's page, it had a page of its own at the slug of
    # its own spelling; that address now forwards, so a link to it still works.
    page_names = pages_before_earlier
    retired: dict[str, tuple[str, str]] = {}
    for agreement in data["agreements"] + archived:
        for version in agreement["versions"]:
            for name in [version["organisation"], *version["controllers"]]:
                own, now = slugify(name), organisation_slug(name, organisation_aliases, organisation_lineage)
                if own != now and own not in page_names and now in page_names:
                    retired.setdefault(own, (name, now))
    for own, (name, now) in sorted(retired.items()):
        render("moved.html", f"organisations/{own}/index.html", name=name, target=now, target_name=page_names[now])
    for slug, entry in earlier_orgs.items():
        if slug in retired:
            warn(f"earlier: {entry['name']} shares a page address with a renamed organisation; left out")
            continue
        render("earlier-organisation.html", f"organisations/{slug}/index.html", organisation=entry,
               dataset_slugs=dataset_slugs)

    for dataset in data["datasets"] + archive["datasets"]:
        dataset_months = releases.monthly(dataset["agreements"], dataset_aliases, dataset["slug"], release_rows)
        render(
            "dataset.html",
            f"datasets/{dataset['slug']}/index.html",
            dataset=dataset,
            by_month=dataset_months,
            files_chart=releases.chart(dataset_months, "files", latest_month) if dataset_months else None,
            agreements_chart=releases.chart(dataset_months, "agreements", latest_month) if dataset_months else None,
            early_files=sum(row["files"] for month, row in dataset_months.items() if month < releases.CHART_START),
            chart_start=releases.CHART_START,
            archived=archive["by_dataset"].get(dataset["slug"], []),
            org_slugs=org_slugs,
            search_numbers=search_numbers,
            paper_count=papers_by_dataset.get(dataset["slug"], 0),
            earlier=earlier_by_dataset.get(dataset["slug"]),
        )

    shutil.copytree(ASSETS, out / "assets", dirs_exist_ok=True)
    (out / ".nojekyll").write_text("")
    # `edition_label` is the edition as a person reads it ("September 2026"),
    # for anything that shows it without formatting it, such as the README's
    # badge.
    _write(out, "meta.json", json.dumps(
        {**meta, "edition_label": sources.edition_label(meta["edition"]), "stats": stats}, indent=1
    ))
    _write(out, "sitemap.xml", env.get_template("sitemap.xml").render(
        **context, agreements=data["agreements"] + archived + earlier_only,
        organisations=data["organisations"] + archive["organisations"] + list(earlier_orgs.values()),
        datasets=data["datasets"] + archive["datasets"],
        changes_editions=[e["edition"] for e in changes_history or [] if e["edition"] != meta["edition"]],
    ))
    _write(
        out, "robots.txt",
        f"User-agent: *\nAllow: /\nSitemap: {meta['site_url']}{meta['base_path']}/sitemap.xml\n",
    )
    print(f"built {sum(1 for _ in out.rglob('*.html')):,} pages into {out}")
    return by_slug
