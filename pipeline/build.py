"""Render the static site from an extracted register."""

from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import aliases
from . import compare
from . import sources
from .extract import slugify

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
        "commercial": sum(1 for a in agreements if a["commercial"] == "Yes"),
        "sublicensing": sum(1 for a in agreements if a["sublicensing"] == "Yes"),
        "joint_controller": sum(
            1 for a in agreements if a["controller_basis"].lower().startswith("joint")
        ),
        "organisation_types": _counts(a["organisation_type"] or "Not stated" for a in agreements),
    }


def _counts(values) -> list[tuple[str, int]]:
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))


def write_csvs(data: dict, out: Path, base_url: str) -> list[dict]:
    """Flat CSV extracts — the reusable form the register itself doesn't offer.

    `base_url` is where the site is served, so the `url` column still points at
    the agreement page once the file has been downloaded and opened elsewhere.
    """
    directory = out / "downloads"
    directory.mkdir(parents=True, exist_ok=True)
    written = []

    def dump(name: str, header: list[str], rows) -> None:
        path = directory / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)
        written.append(
            {"name": name, "size_kb": round(path.stat().st_size / 1024), "header": header}
        )

    dump(
        "agreements.csv",
        [
            "base_reference", "reference", "version", "title", "organisation",
            "organisation_type", "data_controllers", "controller_basis", "start_date",
            "end_date", "sublicensing", "commercial", "datasets", "files_released", "url",
        ],
        (
            [
                a["base_reference"], v["reference"], v["version"], v["title"], v["organisation"],
                v["organisation_type"], "; ".join(v["controllers"]), v["controller_basis"],
                v["start_date"], v["end_date"], v["sublicensing"], v["commercial"],
                "; ".join(d["name"] for d in v["datasets"]), v["files_released"],
                f"{base_url}/agreements/{a['slug']}/",
            ]
            for a in data["agreements"]
            for v in a["versions"]
        ),
    )
    dump(
        "datasets.csv",
        [
            "reference", "organisation", "dataset", "type_of_data", "sensitivity",
            "frequency", "legal_basis", "common_law_duty_of_confidentiality",
        ],
        (
            [
                v["reference"], v["organisation"], d["name"], d["type_of_data"],
                d["sensitivity"], d["frequency"], d["legal_basis"], d["confidentiality"],
            ]
            for a in data["agreements"]
            for v in a["versions"]
            for d in v["datasets"]
        ),
    )
    dump(
        "releases.csv",
        ["reference", "organisation", "dataset", "files_released", "first_month", "last_month", "opt_outs_applied"],
        (
            [
                v["reference"], v["organisation"], r["dataset"], r["files"],
                r["first_month"], r["last_month"], r["opt_outs_applied"],
            ]
            for a in data["agreements"]
            for v in a["versions"]
            for r in v["releases"]
        ),
    )
    return written


def version_diffs(agreement: dict) -> dict[str, dict]:
    """What each version changed from the one before it, keyed by reference.

    Both versions are in the same extract, so this needs no stored history —
    unlike the edition-to-edition case, which cannot be answered until the
    amendment log in docs/plan-version-diffs.md exists.
    """
    diffs = {}
    for older, newer in zip(agreement["versions"], agreement["versions"][1:]):
        difference = compare.compare_versions(older, newer)
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
    downloads = write_csvs(data, out, meta["site_url"] + meta["base_path"])
    by_slug = {a["slug"]: a for a in data["agreements"]}

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
        "downloads": downloads,
        "build_time": dt.datetime.now(dt.timezone.utc).strftime("%d %B %Y"),
    }

    def render(template: str, path: str, **kwargs) -> None:
        # kwargs can legitimately override a context key (a historical changes
        # page overrides `meta` to show its own edition, for instance), so merge
        # rather than spread both as separate keyword arguments — spreading both
        # would raise on any key they share.
        _write(out, path, env.get_template(template).render(**{**context, **kwargs}))

    top_organisations = sorted(
        data["organisations"], key=lambda o: (-o["agreement_count"], o["name"].lower())
    )[:15]
    render("index.html", "index.html", agreements=data["agreements"], top_organisations=top_organisations)
    render("agreements.html", "agreements/index.html", agreements=data["agreements"])
    render("organisations.html", "organisations/index.html", organisations=data["organisations"])
    render("datasets.html", "datasets/index.html", datasets=data["datasets"])
    changes_by_slug = {a["base_reference"]: a for a in data["agreements"]}
    render("changes.html", "changes/index.html", by_slug=changes_by_slug)
    # A same-shaped page for every earlier edition pair, so "what changed" isn't
    # limited to the current edition — the fingerprints exist for the whole
    # backfilled history even when only the newest edition has a full extract.
    for entry in changes_history or []:
        if entry["edition"] == meta["edition"]:
            # Identical to /changes/, which already shows it.
            continue
        render(
            "changes.html",
            f"changes/{entry['edition']}/index.html",
            changes=entry,
            by_slug=changes_by_slug,
            meta={**meta, "edition": entry["edition"]},
        )
    render("about.html", "about/index.html")
    render("downloads.html", "downloads/index.html")
    render("not-found.html", "404.html")

    org_slugs = {o["slug"] for o in data["organisations"]}
    for agreement in data["agreements"]:
        render(
            "agreement.html",
            f"agreements/{agreement['slug']}/index.html",
            agreement=agreement,
            change_status={v["reference"]: changed_refs.get(v["reference"]) for v in agreement["versions"]},
            org_slugs=org_slugs,
            history=(history or {}).get(agreement["base_reference"]),
            diffs=version_diffs(agreement),
        )
    for organisation in data["organisations"]:
        render(
            "organisation.html",
            f"organisations/{organisation['slug']}/index.html",
            organisation=organisation,
        )
    for dataset in data["datasets"]:
        render("dataset.html", f"datasets/{dataset['slug']}/index.html", dataset=dataset)

    shutil.copytree(ASSETS, out / "assets", dirs_exist_ok=True)
    (out / ".nojekyll").write_text("")
    _write(out, "meta.json", json.dumps({**meta, "stats": stats}, indent=1))
    _write(out, "sitemap.xml", env.get_template("sitemap.xml").render(
        **context, agreements=data["agreements"],
        organisations=data["organisations"], datasets=data["datasets"],
    ))
    _write(out, "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {meta['site_url']}/sitemap.xml\n")
    print(f"built {sum(1 for _ in out.rglob('*.html')):,} pages into {out}")
    return by_slug
