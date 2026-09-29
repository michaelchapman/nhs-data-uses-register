"""The site's data model, derived from each agreement's versions.

Agreement pages, organisation pages and dataset pages, all worked out from the
versions a workbook or the facts store gives (`assemble`), under the reviewed
alias, lineage and exclusion files (see `rules`). Nothing here is stored, so a
change to one of those files takes effect at the next build.
"""

from __future__ import annotations

import re

from . import aliases, sources
from .names import strip_code
from .records import clean_line
from .references import slugify, version_key
from .rules import Rules


def assemble(versions_by_base: dict[str, list[dict]], rules: Rules | None = None) -> dict:
    """`{agreements, organisations, datasets}` from each agreement's versions.

    Everything but the versions themselves is derived from them, plus the
    reviewed alias files. That is why the facts store keeps only the versions
    (see `facts`): a workbook and a stored edition both arrive here and come
    out the same, and an alias reviewed since the edition was ingested takes
    effect on the next build without a re-ingest.
    """
    rules = rules or Rules.load()
    agreements = [
        build_agreement(base, versions, rules.organisation_aliases, rules.dataset_aliases, rules.lineage)
        for base, versions in versions_by_base.items()
        if base.upper() not in rules.excluded
    ]
    agreements.sort(key=lambda a: (a["organisation"].lower(), a["base_reference"]))
    return {
        "agreements": agreements,
        "organisations": _group_organisations(agreements, rules),
        "datasets": _group_datasets(agreements, rules),
    }


def organisation_slug(name: str, alias_map: dict, organisation_lineage=None) -> str:
    """The organisation page a register name belongs on.

    ODS decides first, for the NHS organisations it knows: every sub-ICB
    location's name goes to its ICB's page, named as ODS names the ICB. The
    reviewed aliases decide for everything else.
    """
    page = organisation_lineage.page(name) if organisation_lineage else None
    if page:
        return slugify(organisation_lineage.page_name(page))
    return slugify(aliases.resolve(name, alias_map))


def _controller_rows(controllers: list[str], slugs: list[str]) -> list[dict]:
    """The data controllers to list, once per organisation page.

    The register can name one ICB as several of its sub-ICB locations, which
    read identically once their codes are dropped.
    """
    rows: dict[str, dict] = {}
    for name, slug in zip(controllers, slugs):
        rows.setdefault(slug or name, {"name": name, "slug": slug, "names": []})["names"].append(name)
    return list(rows.values())


def build_agreement(
    base: str, versions: list[dict], alias_map: dict, dataset_alias_map: dict, organisation_lineage=None
) -> dict:
    """One agreement page's worth of data, derived from its versions."""
    versions.sort(key=lambda v: (version_key(v["version"]), v["start_date"]))
    latest = versions[-1]
    earliest = versions[0]
    dataset_names = sorted({d["name"] for v in versions for d in v["datasets"] if d["name"]})
    starts = [v["start_date"] for v in versions if v["start_date"]]
    ends = [v["end_date"] for v in versions if v["end_date"]]
    # An unversioned reference (no "-vN" suffix) has exactly one version, which
    # is trivially the first. Otherwise the earliest version we hold is only
    # really "the first" if its own number says so — a backfill that starts
    # partway through an agreement's history has an earliest version that
    # isn't v1, and the page needs to say "before", not "from". A v0.x number
    # is the register's numbering for an agreement's first published version:
    # across every edition held, no lower version of one has ever surfaced.
    first_known = (
        earliest["version"] in ("", "1", "1.0") or earliest["version"].split(".")[0] == "0"
    )
    legal_bases = sorted({d["legal_basis"] for v in versions for d in v["datasets"] if d["legal_basis"]})
    # `organisation`/`controllers` stay exactly as the register recorded them —
    # what an agreement page shows is always the literal source text. Only the
    # slugs used for grouping and links go through the alias map, so a
    # human-reviewed merge (see aliases.py) changes which page something links
    # to, never what it displays.
    controller_slugs = [organisation_slug(c, alias_map, organisation_lineage) for c in latest["controllers"]]
    return {
        "base_reference": base,
        "slug": slugify(base),
        "title": latest["title"] or base,
        "organisation": latest["organisation"],
        "organisation_slug": organisation_slug(latest["organisation"], alias_map, organisation_lineage),
        "organisation_type": latest["organisation_type"],
        "commercial": latest["commercial"],
        "sublicensing": latest["sublicensing"],
        "controller_basis": latest["controller_basis"],
        "controllers": latest["controllers"],
        "controller_slugs": controller_slugs,
        "controller_rows": _controller_rows(latest["controllers"], controller_slugs),
        "first_start": min(starts) if starts else "",
        "first_start_known": first_known,
        "latest_start": latest["start_date"],
        "latest_end": latest["end_date"],
        # When the agreement's term ends, which decides whether it is in term.
        # The latest version supersedes the ones before it, so its end date
        # counts even where an older version's is later: a v0.0 record can
        # carry a placeholder end years after the agreement lapsed.
        "coverage_end": latest["end_date"] or (max(ends) if ends else ""),
        "dataset_names": dataset_names,
        # Resolved through the dataset alias map, so a renamed
        # dataset links to one page rather than two.
        "dataset_slugs": [
            slugify(aliases.resolve(n, dataset_alias_map)) for n in dataset_names
        ],
        "legal_bases": legal_bases,
        "files_released": sum(v["files_released"] for v in versions),
        "versions": versions,
        "latest": latest,
    }


def _canonical_names(rules: Rules) -> dict[str, str]:
    """`{slug: the name a reviewer chose}` for every reviewed organisation merge.

    Cleaned like any other name: the alias file is typed by hand, and a canonical
    copied out of the register keeps the register's double spaces. A page ODS
    decides is named as ODS names the organisation.
    """
    names = {slugify(g["canonical"]): clean_line(g["canonical"]) for g in rules.organisation_groups}
    names.update({slug: name for slug, (name, _) in _lineage_pages(rules.lineage).items()})
    return names


def _lineage_pages(organisation_lineage) -> dict[str, tuple[str, str]]:
    """`{slug: (page name, ODS identity)}` for every organisation page ODS decides."""
    if organisation_lineage is None:
        return {}
    pages = {}
    names = [e["name"] for e in organisation_lineage.entries.values()]
    names += [s["from"] for s in organisation_lineage.successions.values()]
    for name in names:
        identity = organisation_lineage.page(name)
        page_name = organisation_lineage.page_name(identity)
        pages[slugify(page_name)] = (page_name, identity)
    return pages


def _lineage_facts(identity: str, organisation_lineage, slugs: set[str]) -> dict:
    """What ODS says about an organisation page: its sub-ICB locations, predecessors and successors."""
    def linked(rows):
        return [{**row, "slug": slugify(row["name"]) if slugify(row["name"]) in slugs else ""} for row in rows]

    kind, code = identity.split(":", 1)
    return {
        "code": code,
        "ccg": kind == "ccg",
        "sub_icb_locations": organisation_lineage.sub_icb_locations(identity),
        "predecessors": linked(organisation_lineage.predecessors(identity)),
        "successors": linked(organisation_lineage.successors_of(identity)),
    }


def _group_organisations(agreements: list[dict], rules: Rules) -> list[dict]:
    alias_map = rules.organisation_aliases
    dataset_alias_map = rules.dataset_aliases
    organisation_lineage = rules.lineage
    lineage_pages = _lineage_pages(organisation_lineage)
    reviewed_names = {aliases.name_key(clean_line(g["canonical"])) for g in rules.organisation_groups}
    # The exact text a reviewer wrote as `canonical` in the alias file, keyed
    # by its own slug. Falling back to `aliases.resolve()` per agreement isn't
    # enough on its own: whichever raw name happens to be processed first
    # becomes the display name, which is only the reviewer's chosen spelling
    # by coincidence if the register's own text already matches it.
    canonical_by_slug = _canonical_names(rules)

    # Group by the already-canonical `organisation_slug`, not by the raw
    # `organisation` text: a human-reviewed alias means two different strings
    # in the register belong on one page. `known_as` collects every raw
    # spelling actually seen, so the merge is always visible on the page
    # rather than silently applied.
    grouped: dict[str, dict] = {}
    for agreement in agreements:
        raw_name = agreement["organisation"] or "Unnamed organisation"
        slug = agreement["organisation_slug"]
        canonical_name = canonical_by_slug.get(slug) or aliases.resolve(raw_name, alias_map)
        entry = grouped.setdefault(
            slug,
            {
                "name": canonical_name,
                "slug": slug,
                "type": agreement["organisation_type"],
                "agreements": [],
                "controller_agreements": [],
                "known_as": set(),
                # Distinguishes a human-reviewed merge (data/organisation-aliases.json)
                # from two spellings that were never really different — a curly vs
                # straight apostrophe — which slugify() already treats as one
                # organisation without anyone having to review anything.
                "reviewed_merge": slug in canonical_by_slug and slug not in lineage_pages,
            },
        )
        if raw_name != entry["name"]:
            entry["known_as"].add(raw_name)
        entry.setdefault("raw_names", set()).add(raw_name)
        entry["agreements"].append(agreement)

    # An organisation can also appear only as a data controller on someone else's
    # agreement, never as the applicant — this matches controller free text
    # against organisation names by slug, so it's approximate: a controller
    # recorded under a different spelling won't be matched unless that spelling
    # is in the alias file. Track membership by base_reference rather than
    # comparing agreement dicts, which is both faster and correct regardless of
    # dict identity.
    by_slug = {entry["slug"]: entry for entry in grouped.values()}
    seen_refs = {slug: {a["base_reference"] for a in entry["agreements"]} for slug, entry in by_slug.items()}
    for agreement in agreements:
        applicant_slug = agreement["organisation_slug"]
        for controller, controller_slug in zip(agreement["controllers"], agreement["controller_slugs"]):
            if not controller_slug or controller_slug == applicant_slug:
                continue
            found = by_slug.get(controller_slug)
            if found is not None:
                entry = found
            else:
                canonical_controller = canonical_by_slug.get(controller_slug) or aliases.resolve(controller, alias_map)
                entry = {
                    "name": canonical_controller,
                    "slug": controller_slug,
                    "type": "",
                    "agreements": [],
                    "controller_agreements": [],
                    "known_as": set(),
                    "reviewed_merge": controller_slug in canonical_by_slug and controller_slug not in lineage_pages,
                }
                grouped[controller_slug] = entry
                by_slug[controller_slug] = entry
                seen_refs[controller_slug] = set()
            if controller != entry["name"]:
                entry["known_as"].add(controller)
            entry.setdefault("raw_names", set()).add(controller)
            if agreement["base_reference"] not in seen_refs[controller_slug]:
                entry["controller_agreements"].append(agreement)
                seen_refs[controller_slug].add(agreement["base_reference"])

    slugs = set(grouped)
    for entry in grouped.values():
        page = lineage_pages.get(entry["slug"])
        entry["lineage"] = _lineage_facts(page[1], organisation_lineage, slugs) if page else None
        entry["agreement_count"] = len(entry["agreements"])
        entry["controller_agreement_count"] = len(entry["controller_agreements"])
        all_agreements = entry["agreements"] + entry["controller_agreements"]
        entry["files_released"] = sum(a["files_released"] for a in entry["agreements"])
        # Canonical dataset names, so a renamed dataset counts once and links to
        # the one page it has, rather than to a page for each old spelling.
        entry["dataset_names"] = sorted(
            {aliases.resolve(n, dataset_alias_map) for a in all_agreements for n in a["dataset_names"]}
        )
        # An organisation named only as a data controller has no agreements of
        # its own, so its latest end date is that of the agreements naming it.
        entry["latest_end"] = max(
            (a["coverage_end"] for a in entry["agreements"] or entry["controller_agreements"]), default=""
        )
        entry["commercial"] = any(a["commercial"] == "Yes" for a in entry["agreements"])
        # Codes are shown only where they explain lineage, which the sub-ICB
        # location list does; here they would only make one name look like two.
        entry["known_as"] = sorted({strip_code(n) for n in entry["known_as"]} - {strip_code(entry["name"])})
        # Named as ODS names it, where the register never uses that name: a
        # reviewer's chosen spelling does not count, as that is the register's.
        raw_names = {aliases.name_key(strip_code(n)) for n in entry.pop("raw_names", set())}
        entry["named_in_register"] = not (
            entry["slug"] in lineage_pages
            and aliases.name_key(strip_code(entry["name"])) not in raw_names
            and aliases.name_key(entry["name"]) not in reviewed_names
        )
    return sorted(grouped.values(), key=lambda o: o["name"].lower())


def _dataset_organisations(agreements: list[dict], canonical_by_slug: dict[str, str]) -> list[dict]:
    """Who receives a dataset: `{slug, name, agreements, ends}`, busiest first.

    `ends` holds each agreement's end date, so a page can tell which of an
    organisation's agreements are in term in the edition it shows.
    """
    rows: dict[str, dict] = {}
    for agreement in agreements:
        slug = agreement["organisation_slug"]
        row = rows.setdefault(
            slug,
            {
                "slug": slug,
                "name": canonical_by_slug.get(slug) or agreement["organisation"] or "Unnamed organisation",
                "agreements": 0,
                "ends": [],
            },
        )
        row["agreements"] += 1
        row["ends"].append(agreement["coverage_end"])
    return sorted(rows.values(), key=lambda r: (-r["agreements"], r["name"].lower()))


def _group_datasets(agreements: list[dict], rules: Rules) -> list[dict]:
    canonical_by_slug = _canonical_names(rules)
    # Datasets get relabelled at least as often as organisations — NHS England
    # appended acronyms across the whole register in January 2023 — and a
    # rename would otherwise split one dataset's history across two pages.
    # Reviewed merges live in data/dataset-aliases.json; see datasetcheck.
    alias_map = rules.dataset_aliases
    grouped: dict[str, dict] = {}
    listed: set[tuple[str, str]] = set()
    for agreement in agreements:
        for raw_name in agreement["dataset_names"]:
            name = aliases.resolve(raw_name, alias_map)
            entry = grouped.setdefault(
                name,
                {"name": name, "slug": slugify(name), "agreements": [], "attributes": {}},
            )
            # An agreement that spans a rename names both spellings, and both
            # resolve to this entry: list it once, or its files count twice.
            if (name, agreement["base_reference"]) not in listed:
                listed.add((name, agreement["base_reference"]))
                entry["agreements"].append(agreement)
            for version in agreement["versions"]:
                for dataset in version["datasets"]:
                    if aliases.resolve(dataset["name"], alias_map) != name:
                        continue
                    for key in ("type_of_data", "sensitivity", "legal_basis", "frequency"):
                        if dataset[key]:
                            # Values differ across agreements only by stray whitespace
                            # more often than they differ in substance.
                            value = re.sub(r"\s+", " ", dataset[key]).strip()
                            # A dataset with several legal bases lists them in one
                            # cell joined by ";", giving dozens of combinations
                            # that differ by one clause. Keep each basis once.
                            values = [v.strip() for v in value.split(";")] if key == "legal_basis" else [value]
                            entry["attributes"].setdefault(key, set()).update(v for v in values if v)
    for name, entry in grouped.items():
        entry["agreement_count"] = len(entry["agreements"])
        # Counted by canonical slug, not raw name, so two aliased spellings of
        # the same organisation count once rather than twice.
        entry["organisations"] = sorted({a["organisation_slug"] for a in entry["agreements"]})
        entry["files_released"] = sum(
            r["files"]
            for a in entry["agreements"]
            for v in a["versions"]
            for r in v["releases"]
            # Release rows carry the name as the register wrote it, which for a
            # renamed dataset is not the canonical name the entry is keyed on.
            if aliases.resolve(r["dataset"], alias_map) == name
        )
        entry["attributes"] = {k: sorted(v) for k, v in entry["attributes"].items()}
        entry["organisation_rows"] = _dataset_organisations(entry["agreements"], canonical_by_slug)
    return sorted(grouped.values(), key=lambda d: (-d["agreement_count"], d["name"].lower()))


def archive_views(
    archived: list[dict], organisations: list[dict], datasets: list[dict], rules: Rules | None = None
) -> dict:
    """Organisation and dataset pages for agreements no longer in the register.

    An organisation or dataset that only departed agreements name would
    otherwise lose its page when they leave, though their pages still name it.
    Returns:

    - `organisations`, `datasets`: pages for those named only by departed
      agreements, each marked `archived` with the last edition that named it;
    - `by_organisation`, `by_dataset`: `{slug: [agreement]}`, the departed
      agreements naming each page that is still current, for a section of its
      own.

    None of it is counted in the site's figures, which come from the
    agreements still listed.
    """
    rules = rules or Rules.load()
    order = lambda a: sources.edition_sort_key(a["archived"]["last_edition"])
    current_organisations = {o["slug"] for o in organisations}
    current_datasets = {d["slug"] for d in datasets}

    by_organisation, archived_organisations = {}, []
    for entry in _group_organisations(archived, rules):
        named = list({a["base_reference"]: a for a in entry["agreements"] + entry["controller_agreements"]}.values())
        if entry["slug"] in current_organisations:
            by_organisation[entry["slug"]] = named
        else:
            entry["archived"] = {"last_edition": max(named, key=order)["archived"]["last_edition"]}
            archived_organisations.append(entry)

    by_dataset, archived_datasets = {}, []
    for entry in _group_datasets(archived, rules):
        if entry["slug"] in current_datasets:
            by_dataset[entry["slug"]] = entry["agreements"]
        else:
            entry["archived"] = {"last_edition": max(entry["agreements"], key=order)["archived"]["last_edition"]}
            archived_datasets.append(entry)

    # Lineage links were worked out within each group; an archived CCG's
    # successor may well be a current page, and the other way round.
    slugs = current_organisations | {o["slug"] for o in archived_organisations}
    for entry in organisations + archived_organisations:
        for row in (entry.get("lineage") or {}).get("predecessors", []) + (entry.get("lineage") or {}).get("successors", []):
            row["slug"] = slugify(row["name"]) if slugify(row["name"]) in slugs else ""
    return {
        "organisations": archived_organisations,
        "datasets": archived_datasets,
        "by_organisation": by_organisation,
        "by_dataset": by_dataset,
    }
