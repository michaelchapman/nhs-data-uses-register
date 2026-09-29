# NHS Data Access Explorer

[![Build and deploy](https://github.com/michaelchapman/nhs-data-uses-register/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/michaelchapman/nhs-data-uses-register/actions/workflows/build.yml)
[![Site](https://img.shields.io/website?url=https%3A%2F%2Fhealthdatauses.uk&label=healthdatauses.uk)](https://healthdatauses.uk)
[![Edition](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhealthdatauses.uk%2Fmeta.json&query=%24.edition_label&label=edition)](https://healthdatauses.uk/changes/)
[![Agreements](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fhealthdatauses.uk%2Fmeta.json&query=%24.stats.agreements&label=agreements)](https://healthdatauses.uk/agreements/)
[![Code: MIT](https://img.shields.io/badge/code-MIT-blue)](LICENSE)
[![Data: OGL v3.0](https://img.shields.io/badge/data-OGL%20v3.0-blue)](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)

A static site that reformats the [NHS England Data Uses Register](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register)
— published monthly as a 29 MB, three-sheet spreadsheet — into pages you can
read, search, link to and cite.

It is published at **[healthdatauses.uk](https://healthdatauses.uk)**. It is
unofficial. NHS England publishes the data; this repository only rearranges it.

## What it produces

From one edition of the register (~5,500 agreement versions):

- **~1,950 agreement pages** — versions of the same agreement grouped together,
  with purpose, expected outputs, benefits, datasets and file releases joined
  from all three sheets onto one page.
- **~500 organisation pages** and **~210 dataset pages** — the two questions the
  spreadsheet makes hardest: what agreements does this organisation hold, and
  which agreements name this dataset.
- **A "what changed" page** — agreements added, amended or withdrawn since the
  previous edition.
- **Files released over time** — agreements receiving files and files released
  each month, across the register and for each dataset, and a timeline of the
  months each agreement received files, drawn at build time without script.

Pages are plain semantic HTML with no cookies, analytics or third-party
requests. Table filtering and sorting are progressive enhancements: every row is in the
HTML, so the site works with JavaScript disabled. The filters and the sort are
kept in the URL, so a filtered view can be linked to.
The agreements search also reads each agreement's purpose text, through a word
index the build writes to `search/<edition>/` — one small file per first
letter, fetched from the site itself only when someone searches. Without it,
the search falls back to titles and names. Every page has a search box that
leads there, and a search also lists the organisations and datasets whose
names match, from `search/<edition>/names.json`, including the other spellings
merged onto each page.

## Running it locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pipeline.run
.venv/bin/python -m http.server 8000 --directory _site
```

`pipeline.run` builds the newest edition in `data/facts/` and writes the site to
`_site/`. It makes no network requests.

The checks CI runs, with the checkers pinned in `requirements-dev.txt` and
configured in `pyproject.toml`:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m unittest
.venv/bin/ruff check pipeline tests
.venv/bin/mypy
```

Useful flags:

| Flag | Effect |
| --- | --- |
| `--edition september2026` | Build any edition in the store, not only the newest |
| `--workbook path.xlsx` | One-off build from a local file; nothing is ingested or written to `data/` |
| `--base-path /repo-name` | Serve under a subpath (GitHub project pages) |
| `--output dir` | Write somewhere other than `_site/` |

## How it stays current

By hand, once a month. **[docs/manual-updates.md](docs/manual-updates.md) is the
runbook** — it takes about two minutes.

It is not automated, and that is deliberate. `digital.nhs.uk` sits behind a WAF
that refuses requests from datacentre address space: every scheduled build
failed with `HTTP 403`, including one that sent full browser headers and retried
with backoff. The asset URLs are blocked the same way, and so is the National
Archives' copy. Rather than work around a block the publisher put there on
purpose, the download step was removed. The page serves fine in an ordinary
browser, so a person downloads the workbook and runs one command:

```bash
.venv/bin/python -m pipeline.ingest data/raw/datausesregister_august2026.xlsx
git add data/facts && git commit -m "Add the August 2026 edition"
```

`.github/workflows/build.yml` then rebuilds and deploys on push to `main`, from
committed data only. Because it never reaches outside the repository, it cannot
fail the way the scheduled job did.
`.github/workflows/ci.yml` runs the same checks on every pull request, without
deploying: both run `.github/actions/check`, which installs the pinned
requirements, runs the tests, lint and type check, builds the site and checks
its links.

One thing is committed: **`data/facts/<register>/`**, the text of every
edition. Nothing derived is stored — what changed between editions, and the
organisation and dataset views, are worked out at build time — so a new alias or
a change to what counts as an amendment costs a rebuild, and never a re-parse of
the workbooks.

- **`agreements/<slug>.json`** — every version of one agreement, and each
  distinct state a version has been published in. One uncompressed file per
  agreement, deliberately not gzipped or bundled: consecutive editions restate
  almost all of the same prose, and git stores that as a small delta between two
  copies of the same file. `git log` on one of these is that agreement's history.
- **`releases/<slug>.json`** — every file released under an agreement, one row
  per file, and which edition first reported it.
- **`editions/<edition>.json`** — which state each version was in that month.
  About 190 KB, one per edition, kept forever.
- **`manifest.json`** — each workbook's SHA-256, size and source URL, so the file
  that was ingested can be identified.

The whole archive, July 2021 to September 2026, is about 420 MB on disk and
42 MB packed in git; a monthly ingest adds under 1 MB.

The workbooks themselves (29 MB each) are never committed: `data/raw/` is
gitignored.

### Backfilling the archive

NHS England keeps previous editions on the
[release register archive](https://digital.nhs.uk/services/data-access-request-service-dars/data-uses-register/release-register-archive).
Download as many as you want history for into `data/raw/` and ingest them
together — command-line order does not matter, as editions are sorted by the
month in their filename:

```bash
.venv/bin/python -m pipeline.ingest data/raw/*.xlsx
```

Ingesting an edition that is already recorded writes nothing, so a backfill can
be stopped and restarted.

### First-time setup

1. Push this repository to GitHub.
2. Settings → Pages → **Source: GitHub Actions**.
3. Ingest at least one edition and push it.
4. Run the workflow (Actions → Build and deploy → Run workflow).

Using a project page instead of a custom domain or a user page? Set `site-url`
and `base-path` where `.github/workflows/build.yml` runs the check action.

## Layout

```
pipeline/run.py                 builds the site from the facts store (the entry point)
pipeline/sources.py             register definitions, filename and edition rules
pipeline/ingest.py              workbook -> the committed facts store
pipeline/facts.py               the facts store: every edition, its releases and its manifest
pipeline/extract.py             workbook -> agreement versions
pipeline/references.py          base references, version numbers and page slugs
pipeline/records.py             one version record: tidying names, splitting controllers, summarising releases
pipeline/model.py               versions -> agreement, organisation and dataset pages
pipeline/rules.py               the alias, lineage and exclusion files, read once per build
pipeline/changes.py             what changed between editions, worked out from the facts
pipeline/compare.py             field-by-field comparison of two agreement versions
pipeline/build.py               renders the site
pipeline/search.py              the word index behind the agreements search
pipeline/releases.py            files released by month: the build-time check, timelines and charts
pipeline/names.py               shows a name the register wrote in capitals in ordinary case
pipeline/orgcheck.py            finds organisation names that might be duplicates
pipeline/privacy.py             confidential data and opt-outs, for the agreements list's filters
pipeline/sectors.py             groups organisations into sectors, for the Sector filters
pipeline/relations.py           links related organisations that stay separate pages
pipeline/aliases.py             applies reviewed organisation and dataset merges
pipeline/ods.py                 reads NHS organisation records from ODS into a snapshot
pipeline/odscheck.py            finds the ODS code for each NHS name in the register
pipeline/lineage.py             renames and successions between NHS organisations
pipeline/exclusions.py          leaves out published records that are not data sharing
pipeline/datasetcheck.py        finds datasets the register has renamed, from the facts store
pipeline/clichecheck.py         flags LLM-cliché phrasing in the repo's own prose
pipeline/linkcheck.py           finds internal links in a built site that point nowhere
pipeline/templates/             Jinja2 templates
tests/                          unit tests and a synthetic register (python -m unittest)
assets/                         CSS, and the scripts for filtering, search highlighting, citing and printing
.github/actions/check/          the checks and build both workflows run
pyproject.toml                  ruff and mypy settings
requirements.txt                what the build needs, pinned
requirements-dev.txt            the checkers, pinned
data/raw/                       downloaded workbooks (gitignored)
data/facts/                     committed facts: every edition, and the manifest
data/organisation-aliases.json  reviewed organisation-name merges
data/dataset-aliases.json       reviewed dataset-name merges
data/organisation-codes.json    the ODS code for each NHS name, and the evidence
data/excluded-agreements.json   published records the site leaves out, with the reason
data/organisation-sectors.json  organisation types to sectors, and corrections
data/organisation-relations.json related organisations, and why each is linked
data/organisation-successions.json successions recorded by hand where ODS has none
data/ods/organisations.json     the ODS records the site uses (Open Government Licence)
docs/manual-updates.md          the monthly routine
docs/organisation-names.md      reviewing and merging organisation names
docs/plan.md                    what the site is for, and what is left to do
```

## Adding another register

NHS England publishes several registers on the same page. `pipeline/sources.py`
already lists the internal register and the Data Sharing Framework Contracts
with `enabled=False`. To turn one on: check its sheet layout, teach
`extract.py` to read it, then set `enabled=True` and ingest with
`--register <slug>`. The site templates key off the shared agreement model, so a
register with the same shape needs no template changes.

## Caveats

- This is a mirror, and only as current as the last edition somebody added.
  The edition and the date it was added are in the footer of every page. For
  anything consequential, check the source workbook.
- File releases are summarised per dataset on the site. The facts store holds
  every file, but a release row records a file released externally by DARS; it
  does not cover access granted in NHS England's own systems, such as its
  Secure Data Environment and predecessors, or data shared onward by a
  recipient. See [docs/plan.md](docs/plan.md#what-release-data-can-and-cannot-say).
- The register describes what applicants said they intended, not audited
  outcomes.

## Licence

Register content is published by NHS England under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/)
and stays under it. The code in this repository is MIT licensed.
